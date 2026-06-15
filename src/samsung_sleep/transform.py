"""Сборка сырого экспорта в аккуратные таблицы.

build_all(export, config) -> SleepData со всеми таблицами как list[dict].
Логика намеренно совпадает с проверенной версией: combined-ночи не задваиваются,
сутки сна режутся по полуночи, «дыры» без пульса трактуются как снятые часы.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .config import Config
from .loader import Export
from .timeutils import (epoch_ms, fmt_minute, from_epoch_ms, parse_dt,
                        parse_minute, parse_offset, rnd)
from .vitals import VitalsIndex

STAGE_NAMES = {"40001": "awake", "40002": "light", "40003": "deep", "40004": "rem"}

EXERCISE_TYPES = {
    "1001": "walking", "1002": "running", "11007": "cycling",
    "13001": "hiking", "14001": "swimming", "0": "custom",
}

_S = "com.samsung.health.sleep."   # префикс колонок основной таблицы сна
_E = "com.samsung.health.exercise."

# имена выходных таблиц в порядке, в каком их удобно показывать/писать
TABLE_NAMES = ["sleep_sessions", "nights", "daily_sleep", "data_gaps",
               "sleep_stages", "daily_context", "watch_off_hours"]


@dataclass
class SleepData:
    """Результат обработки одного экспорта: все таблицы + профиль + конфиг."""

    sleep_sessions: list[dict]
    nights: list[dict]
    daily_sleep: list[dict]
    data_gaps: list[dict]
    sleep_stages: list[dict]
    daily_context: list[dict]
    watch_off_hours: list[dict]
    profile: dict = field(default_factory=dict)
    config: Config = field(default_factory=Config)

    def tables(self) -> dict[str, list[dict]]:
        return {name: getattr(self, name) for name in TABLE_NAMES}

    @property
    def date_range(self) -> tuple[str, str]:
        dates = [s["sleep_date"] for s in self.sleep_sessions if s.get("sleep_date")]
        return (min(dates), max(dates)) if dates else ("", "")


def stage_summary(segments: list[dict]) -> dict:
    """segments: [{stage, start(ms), end(ms)}] -> минуты по стадиям и awake-сегменты.

    awakening_count / longest_awake_min описывают awake ВНУТРИ одной сессии — это
    микропробуждения, размеченные трекером (Samsung держит их в рамках одной сессии).
    Реальную разрывность сна считаем не отсюда, а из числа самих сессий (см. build_all)."""
    mins: dict[str, float] = defaultdict(float)
    awakenings, longest_awake = 0, 0.0
    for s in segments:
        d = (s["end"] - s["start"]) / 60000
        mins[s["stage"]] += d
        if s["stage"] == "awake":
            awakenings += 1
            longest_awake = max(longest_awake, d)
    total = sum(mins.values())
    asleep = total - mins["awake"]
    out = {
        "sleep_min": asleep, "awake_min": mins["awake"],
        "light_min": mins["light"], "deep_min": mins["deep"], "rem_min": mins["rem"],
        "awakening_count": awakenings, "longest_awake_min": longest_awake,
    }
    for k in ("light", "deep", "rem"):
        out[f"{k}_pct_of_sleep"] = 100 * mins[k] / asleep if asleep else None
    return out


def build_all(export: Export, config: Config | None = None) -> SleepData:
    config = config or Config()

    sleep = export.load_table("com.samsung.shealth.sleep")
    combined = export.load_table("com.samsung.shealth.sleep_combined")
    stages_raw = export.load_table("com.samsung.health.sleep_stage")
    if not sleep:
        raise ValueError("В экспорте нет таблицы com.samsung.shealth.sleep")

    # сегменты стадий по sleep_id
    stages_by_sleep: dict[str, list[dict]] = defaultdict(list)
    for r in stages_raw:
        st, en = parse_dt(r["start_time"]), parse_dt(r["end_time"])
        if st and en:
            stages_by_sleep[r["sleep_id"]].append(
                {"stage": STAGE_NAMES.get(r["stage"], r["stage"]),
                 "start": epoch_ms(st), "end": epoch_ms(en),
                 "offset": r.get("time_offset", "")})

    # части combined-ночей
    parts_by_combined: dict[str, list[str]] = defaultdict(list)
    for r in sleep:
        if r.get("combined_id"):
            parts_by_combined[r["combined_id"]].append(r[_S + "datauuid"])

    vitals = VitalsIndex(export)
    boundary = timedelta(hours=config.sleep_day_boundary_hour)

    def build_row(r: dict, kind: str, prefix: str) -> dict | None:
        st = parse_dt(r.get(prefix + "start_time", ""))
        en = parse_dt(r.get(prefix + "end_time", ""))
        if not st or not en:
            return None
        off = parse_offset(r.get(prefix + "time_offset", "UTC+0000"))
        uid = r.get(prefix + "datauuid", "")
        seg_ids = parts_by_combined[uid] if kind == "combined_night" else [uid]
        segs = [s for sid in seg_ids for s in stages_by_sleep.get(sid, [])]
        stg = stage_summary(segs)
        win_st, win_en = epoch_ms(st), epoch_ms(en)
        local_st, local_en = st + off, en + off
        row = {
            "session_id": uid,
            "record_kind": kind,
            "combined_id": r.get("combined_id", ""),
            "sleep_date": (local_st - boundary).date().isoformat(),
            "start_local": fmt_minute(local_st),
            "end_local": fmt_minute(local_en),
            "time_offset": r.get(prefix + "time_offset", ""),
            "in_bed_min": rnd((win_en - win_st) / 60000, 0),
            "sleep_min": rnd(stg["sleep_min"], 0) if segs else "",
            "sleep_score": r.get("sleep_score", ""),
            "efficiency_pct": r.get("efficiency", ""),
            "latency_min": rnd(int(r["sleep_latency"]) / 60000, 0) if r.get("sleep_latency") else "",
            "sleep_cycles": r.get("sleep_cycle", ""),
            "physical_recovery_pct": r.get("physical_recovery", ""),
            "mental_recovery_pct": r.get("mental_recovery", ""),
            "movement_awakening_pct": r.get("movement_awakening", ""),
            "awake_min": rnd(stg["awake_min"], 0) if segs else "",
            "light_min": rnd(stg["light_min"], 0) if segs else "",
            "deep_min": rnd(stg["deep_min"], 0) if segs else "",
            "rem_min": rnd(stg["rem_min"], 0) if segs else "",
            "light_pct_of_sleep": rnd(stg["light_pct_of_sleep"]) if segs else "",
            "deep_pct_of_sleep": rnd(stg["deep_pct_of_sleep"]) if segs else "",
            "rem_pct_of_sleep": rnd(stg["rem_pct_of_sleep"]) if segs else "",
            "awakening_count": stg["awakening_count"] if segs else "",
            "longest_awake_min": rnd(stg["longest_awake_min"], 0) if segs else "",
        }
        v = vitals.for_window(win_st, win_en)
        row.update({
            "hr_min": rnd(v["hr_min"], 0), "hr_avg": rnd(v["hr_avg"], 0),
            "hr_max": rnd(v["hr_max"], 0),
            "hrv_rmssd_avg": rnd(v["hrv_rmssd_avg"]),
            "hrv_sdnn_avg": rnd(v["hrv_sdnn_avg"]),
            "resp_rate_avg": rnd(v["resp_rate_avg"]),
            "spo2_min": rnd(v["spo2_min"], 0), "spo2_avg": rnd(v["spo2_avg"]),
            "skin_temp_avg": rnd(v["skin_temp_avg"]),
            "skin_temp_min": rnd(v["skin_temp_min"]),
            "skin_temp_max": rnd(v["skin_temp_max"]),
        })
        return row

    # --- sleep_sessions -----------------------------------------------------
    sessions: list[dict] = []
    for r in sleep:
        kind = "part_of_combined" if r.get("combined_id") else "session"
        row = build_row(r, kind, _S)
        if row:
            sessions.append(row)
    for r in combined:
        row = build_row(r, "combined_night", "")
        if row:
            sessions.append(row)
    sessions.sort(key=lambda x: x["start_local"])

    # --- nights (сутки сна, без дублей combined) ----------------------------
    by_day: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        if s["record_kind"] != "part_of_combined":
            by_day[s["sleep_date"]].append(s)
    # физические сессии сна для разрывности: одиночные + куски combined (но НЕ обёртку
    # combined — она дублирует свои куски). Это и есть «сессии сна», что показывают часы.
    bouts_by_day: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        if s["record_kind"] in ("session", "part_of_combined"):
            bouts_by_day[s["sleep_date"]].append(s)
    nights: list[dict] = []
    for day in sorted(by_day):
        rows = by_day[day]
        main = max(rows, key=lambda x: x["in_bed_min"] or 0)

        def total(col, rows=rows):
            vals = [r[col] for r in rows if r[col] != ""]
            return rnd(sum(float(v) for v in vals), 0) if vals else ""

        # разрывность берём из самих сессий Samsung: сколько было отдельных сессий сна
        # и какая самая длинная непрерывная (longest_block_min = самая длинная сессия).
        bouts = bouts_by_day.get(day, [])
        sleep_bouts = len(bouts) if bouts else len(rows)
        block_vals = [float(b["sleep_min"]) for b in bouts if b["sleep_min"] != ""]
        longest_block = rnd(max(block_vals), 0) if block_vals else ""

        nights.append({
            "sleep_date": day,
            "sessions_count": sleep_bouts,
            "total_in_bed_min": total("in_bed_min"),
            "total_sleep_min": total("sleep_min"),
            "total_deep_min": total("deep_min"),
            "total_rem_min": total("rem_min"),
            "total_awake_min": total("awake_min"),
            "longest_block_min": longest_block,
            "main_start_local": main["start_local"],
            "main_end_local": main["end_local"],
            "main_in_bed_min": main["in_bed_min"],
            "main_sleep_score": main["sleep_score"],
            "main_efficiency_pct": main["efficiency_pct"],
            "main_latency_min": main["latency_min"],
            "main_deep_pct": main["deep_pct_of_sleep"],
            "main_rem_pct": main["rem_pct_of_sleep"],
            "main_awakening_count": main["awakening_count"],
            "main_hr_min": main["hr_min"],
            "main_hrv_rmssd_avg": main["hrv_rmssd_avg"],
            "main_resp_rate_avg": main["resp_rate_avg"],
            "main_spo2_min": main["spo2_min"],
            "main_skin_temp_avg": main["skin_temp_avg"],
        })

    # --- покрытие ношения часов + сон по календарным дням -------------------
    worn = vitals.worn_hours()
    first_worn = min((d for d, _h in worn), default="0000")
    real = [s for s in sessions if s["record_kind"] != "part_of_combined"
            and s["start_local"][:10] >= first_worn]

    day_sleep: dict[str, dict] = defaultdict(lambda: {"in_bed": 0.0, "sleep": 0.0, "n": 0})
    for s in real:
        st, en = parse_minute(s["start_local"]), parse_minute(s["end_local"])
        in_bed = float(s["in_bed_min"] or 0)
        ratio = float(s["sleep_min"]) / in_bed if s["sleep_min"] and in_bed else 1.0
        cur = st
        while cur < en:
            day_end = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            chunk = (min(en, day_end) - cur).total_seconds() / 60
            d = day_sleep[cur.date().isoformat()]
            d["in_bed"] += chunk
            d["sleep"] += chunk * ratio
            d["n"] += 1
            cur = min(en, day_end)

    worn_by_day: dict[str, int] = defaultdict(int)
    for d, _h in worn:
        if d >= first_worn:
            worn_by_day[d] += 1

    days_with_data = sorted(set(day_sleep) | set(worn_by_day))
    daily_sleep: list[dict] = []
    watch_off_hours: list[dict] = []
    if days_with_data:
        cur_d = datetime.fromisoformat(days_with_data[0]).date()
        last_d = datetime.fromisoformat(days_with_data[-1]).date()
        while cur_d <= last_d:
            day = cur_d.isoformat()
            ds, wh = day_sleep.get(day), worn_by_day.get(day, 0)
            quality = ("watch_not_worn" if wh <= config.not_worn_max_hours
                       else "partial_wear" if wh < config.partial_max_hours else "ok")
            daily_sleep.append({
                "date": day,
                "recorded_sleep_min": rnd(ds["sleep"], 0) if ds else 0,
                "recorded_in_bed_min": rnd(ds["in_bed"], 0) if ds else 0,
                "sessions_touching_day": ds["n"] if ds else 0,
                "watch_worn_hours": wh,
                "data_quality": quality,
            })
            for hh in range(24):
                if (day, hh) not in worn:
                    watch_off_hours.append({"date": day, "hour": hh})
            cur_d += timedelta(days=1)

    # --- разрывы записи -----------------------------------------------------
    data_gaps = _build_gaps(real, worn, config)

    # --- гипнограмма --------------------------------------------------------
    stage_rows: list[dict] = []
    for sid, segs in stages_by_sleep.items():
        for s in sorted(segs, key=lambda x: x["start"]):
            off = parse_offset(s["offset"])
            st = from_epoch_ms(s["start"]) + off
            en = from_epoch_ms(s["end"]) + off
            stage_rows.append({
                "session_id": sid,
                "stage": s["stage"],
                "start_local": st.strftime("%Y-%m-%d %H:%M:%S"),
                "end_local": en.strftime("%Y-%m-%d %H:%M:%S"),
                "duration_min": rnd((s["end"] - s["start"]) / 60000),
            })
    stage_rows.sort(key=lambda x: x["start_local"])

    # --- дневной контекст ---------------------------------------------------
    daily_context = _build_daily_context(export)

    profile = _read_profile(export)

    return SleepData(
        sleep_sessions=sessions, nights=nights, daily_sleep=daily_sleep,
        data_gaps=data_gaps, sleep_stages=stage_rows, daily_context=daily_context,
        watch_off_hours=watch_off_hours, profile=profile, config=config,
    )


def _build_gaps(real: list[dict], worn: set[tuple[str, int]], config: Config) -> list[dict]:
    gaps: list[dict] = []
    win_s = config.watch_off_window_hours * 3600
    chrono = sorted(real, key=lambda s: s["start_local"])
    for a, b in zip(chrono, chrono[1:]):
        g0, g1 = parse_minute(a["end_local"]), parse_minute(b["start_local"])
        gap_h = (g1 - g0).total_seconds() / 3600
        if gap_h < config.gap_min_hours:
            continue
        off_windows: list[tuple[datetime, datetime]] = []
        run_start, prev_off = None, False
        h = g0.replace(minute=0, second=0, microsecond=0)
        while h < g1:
            is_off = (h.date().isoformat(), h.hour) not in worn
            if is_off and not prev_off:
                run_start = h
            if not is_off and prev_off and run_start is not None:
                if (h - run_start).total_seconds() >= win_s:
                    off_windows.append((run_start, h))
            prev_off = is_off
            h += timedelta(hours=1)
        if prev_off and run_start is not None and (g1 - run_start).total_seconds() >= win_s:
            off_windows.append((run_start, g1))
        off_total = sum((w1 - w0).total_seconds() / 3600 for w0, w1 in off_windows)
        gaps.append({
            "no_sleep_record_from": a["end_local"],
            "no_sleep_record_to": b["start_local"],
            "gap_hours": rnd(gap_h),
            "watch_off_hours": rnd(off_total),
            "watch_off_windows": "; ".join(
                f"{w0:%m-%d %H:%M}-{w1:%m-%d %H:%M}" for w0, w1 in off_windows),
            "interpretation": ("часы не носились - сон в это время мог быть, но не записан"
                               if off_total >= config.watch_off_for_sleep_hours
                               else "часы носились - бодрствование реально"),
        })
    return gaps


def _build_daily_context(export: Export) -> list[dict]:
    day_rows: dict[str, dict] = {}
    for r in export.load_table("com.samsung.shealth.activity.day_summary"):
        dt = parse_dt(r.get("day_time", ""))
        if not dt:
            continue
        day = dt.date().isoformat()
        steps = int(r["step_count"] or 0)
        cur = day_rows.setdefault(day, {"date": day, "steps": 0, "distance_km": "",
                                        "active_min": "", "calories_active": ""})
        if steps >= cur["steps"]:  # на день есть строки от разных устройств - берём полнее
            cur.update({
                "steps": steps,
                "distance_km": rnd(float(r["distance"] or 0) / 1000, 2),
                "active_min": rnd(int(r["active_time"] or 0) / 60000, 0),
                "calories_active": rnd(float(r["calorie"] or 0), 0),
            })
    ex_by_day: dict[str, list] = defaultdict(list)
    for r in export.load_table("com.samsung.shealth.exercise"):
        st = parse_dt(r.get(_E + "start_time", ""))
        if not st:
            continue
        off = parse_offset(r.get(_E + "time_offset", "UTC+0000"))
        day = (st + off).date().isoformat()
        dur_min = int(r.get(_E + "duration") or 0) / 60000
        ex_by_day[day].append((EXERCISE_TYPES.get(r.get(_E + "exercise_type", ""),
                                                  "type_" + (r.get(_E + "exercise_type") or "?")),
                               dur_min))
    nap_by_day: dict[str, float] = defaultdict(float)
    nap_cnt: dict[str, int] = defaultdict(int)
    for r in export.load_table("com.samsung.shealth.vitality.nap_data"):
        st, en = parse_dt(r.get("start_time", "")), parse_dt(r.get("end_time", ""))
        if not st or not en:
            continue
        off = parse_offset(r.get("time_offset", "UTC+0000"))
        day = (st + off).date().isoformat()
        nap_by_day[day] += (en - st).total_seconds() / 60
        nap_cnt[day] += 1
    for day in set(ex_by_day) | set(nap_by_day):
        day_rows.setdefault(day, {"date": day, "steps": 0, "distance_km": "",
                                  "active_min": "", "calories_active": ""})
    for day, cur in day_rows.items():
        exs = ex_by_day.get(day, [])
        cur["exercise_count"] = len(exs)
        cur["exercise_min"] = rnd(sum(d for _, d in exs), 0) if exs else ""
        cur["exercise_types"] = ";".join(sorted({t for t, _ in exs}))
        cur["nap_count"] = nap_cnt.get(day, 0)
        cur["nap_min"] = rnd(nap_by_day[day], 0) if day in nap_by_day else ""
    return sorted(day_rows.values(), key=lambda x: x["date"])


def _read_profile(export: Export) -> dict:
    profile = {}
    for r in export.load_table("com.samsung.health.user_profile"):
        k = r.get("key", "")
        v = r.get("text_value") or r.get("int_value") or r.get("float_value") or ""
        if k in ("birth_date", "gender", "height", "weight") and v:
            profile[k] = v
    return profile
