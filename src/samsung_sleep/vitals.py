"""Физиология во время сна: пульс, HRV, дыхание, сатурация, температура кожи.

Каждая таблица хранит агрегат в CSV, а поминутные значения — в JSON-бинах.
VitalsIndex загружает все ряды один раз и отдаёт сводку за произвольное окно времени.
"""

from __future__ import annotations

from .loader import Export
from .timeutils import epoch_ms, mean, parse_dt, parse_offset

_HR = "com.samsung.health.heart_rate."
_O2 = "com.samsung.health.oxygen_saturation."


class BinSeries:
    """Бины одной таблицы (hrv/temp/дыхание/пульс), лениво подгружаемые из JSON."""

    def __init__(self, export: Export, table: str, rows: list[dict],
                 file_col: str = "binning_data",
                 start_col: str = "start_time", end_col: str = "end_time"):
        self.export = export
        self.table = table
        self.records: list[tuple[int, int, str]] = []
        for r in rows:
            st, en = parse_dt(r.get(start_col, "")), parse_dt(r.get(end_col, ""))
            if st and en and r.get(file_col):
                self.records.append((epoch_ms(st), epoch_ms(en), r[file_col]))
        self._cache: dict[str, list] = {}

    def bins_in(self, win_st: int, win_en: int) -> list[dict]:
        out = []
        for st, en, fname in self.records:
            if st >= win_en or en <= win_st:
                continue
            if fname not in self._cache:
                self._cache[fname] = self.export.load_json(self.table, fname) or []
            for b in self._cache[fname]:
                b_st = b.get("start_time", b.get("time"))
                b_en = b.get("end_time", b_st)
                if b_st is not None and b_st < win_en and b_en > win_st:
                    out.append(b)
        return out


class VitalsIndex:
    """Все физиологические ряды экспорта + сводка за окно и карта ношения часов."""

    def __init__(self, export: Export):
        self.hrv = BinSeries(export, "com.samsung.health.hrv",
                             export.load_table("com.samsung.health.hrv"))
        self.temp = BinSeries(export, "com.samsung.health.skin_temperature",
                              export.load_table("com.samsung.health.skin_temperature"))
        self.resp = BinSeries(export, "com.samsung.health.respiratory_rate",
                              export.load_table("com.samsung.health.respiratory_rate"))
        self.hr_rows = export.load_table("com.samsung.shealth.tracker.heart_rate")
        self.hr_bins = BinSeries(export, "com.samsung.shealth.tracker.heart_rate",
                                 self.hr_rows, start_col=_HR + "start_time",
                                 end_col=_HR + "end_time")
        self.hr_points: list[tuple[int, float]] = []  # одиночные замеры без бинов
        for r in self.hr_rows:
            if not r.get("binning_data") and r.get(_HR + "heart_rate"):
                t = parse_dt(r.get(_HR + "start_time", ""))
                if t:
                    self.hr_points.append((epoch_ms(t), float(r[_HR + "heart_rate"])))
        self.spo2_points: list[tuple[int, float]] = []
        for r in export.load_table("com.samsung.shealth.tracker.oxygen_saturation"):
            t = parse_dt(r.get(_O2 + "start_time", ""))
            if t and r.get(_O2 + "spo2"):
                self.spo2_points.append((epoch_ms(t), float(r[_O2 + "spo2"])))

    def for_window(self, win_st: int, win_en: int) -> dict:
        """Сводка физиологии за окно [win_st, win_en) в epoch ms."""
        out: dict = {}
        bins = self.hrv.bins_in(win_st, win_en)
        out["hrv_rmssd_avg"] = mean([b["rmssd"] for b in bins if b.get("rmssd")])
        out["hrv_sdnn_avg"] = mean([b["sdnn"] for b in bins if b.get("sdnn")])
        t = [b["mean"] for b in self.temp.bins_in(win_st, win_en) if b.get("mean")]
        out["skin_temp_avg"] = mean(t)
        out["skin_temp_min"] = min(t) if t else None
        out["skin_temp_max"] = max(t) if t else None
        rr = [b["respiratory_rate"] for b in self.resp.bins_in(win_st, win_en)
              if b.get("respiratory_rate")]  # нули = нет сигнала, отброшены
        out["resp_rate_avg"] = mean(rr)
        h = [b["heart_rate"] for b in self.hr_bins.bins_in(win_st, win_en) if b.get("heart_rate")]
        h += [v for ts, v in self.hr_points if win_st <= ts < win_en]
        out["hr_avg"] = mean(h)
        out["hr_min"] = min(h) if h else None
        out["hr_max"] = max(h) if h else None
        sp = [v for ts, v in self.spo2_points if win_st <= ts < win_en]
        out["spo2_avg"] = mean(sp)
        out["spo2_min"] = min(sp) if sp else None
        return out

    def worn_hours(self) -> set[tuple[str, int]]:
        """Множество (дата, час) локального времени, когда часы были на руке (есть пульс)."""
        from datetime import timedelta
        worn: set[tuple[str, int]] = set()
        for r in self.hr_rows:
            st = parse_dt(r.get(_HR + "start_time", ""))
            en = parse_dt(r.get(_HR + "end_time", "")) or st
            if not st:
                continue
            off = parse_offset(r.get(_HR + "time_offset", "UTC+0000"))
            h = (st + off).replace(minute=0, second=0, microsecond=0)
            while h <= en + off:
                worn.add((h.date().isoformat(), h.hour))
                h += timedelta(hours=1)
        return worn
