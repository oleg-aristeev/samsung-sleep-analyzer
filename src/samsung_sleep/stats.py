"""Сводные статистики и корреляции «день → ночь».

Чистый Python (без pandas) — чтобы числа можно было вставлять и в llm_context,
и в графики, и легко покрывать тестами. Корреляция — обычный Пирсон.
"""

from __future__ import annotations

import math

from .transform import SleepData

# Ключевые метрики ночи: (колонка в nights, человекочитаемая метка).
SUMMARY_COLS: list[tuple[str, str]] = [
    ("total_sleep_min", "Сон за сутки, мин"),
    ("main_efficiency_pct", "Эффективность, %"),
    ("main_latency_min", "Засыпание, мин"),
    ("main_deep_pct", "Глубокий, % сна"),
    ("main_rem_pct", "REM, % сна"),
    ("sessions_count", "Сессий сна/сутки"),
    ("longest_block_min", "Длиннейшая сессия, мин"),
    ("main_hr_min", "Мин. пульс, уд/мин"),
    ("main_hrv_rmssd_avg", "HRV RMSSD, мс"),
]

# Пары для корреляций: (метка, колонка-X, колонка-Y). Исходы — объективные показатели
# (длительность сна и % глубокого), а не оценка Samsung. Контекст дня (steps, exercise_min,
# nap_min…) приклеивается к ночи той же даты сна — см. master_rows().
CORR_PAIRS: list[tuple[str, str, str]] = [
    # что связано с ДЛИТЕЛЬНОСТЬЮ сна
    ("Шаги за день → длительность сна", "steps", "total_sleep_min"),
    ("Засыпание (latency) → длительность сна", "main_latency_min", "total_sleep_min"),
    ("Дневной сон (мин) → ночной сон (мин)", "nap_min", "total_sleep_min"),
    ("Сессий сна за сутки → длиннейшая сессия", "sessions_count", "longest_block_min"),
    # что связано с ГЛУБОКИМ сном (% глубокого — объективный маркер качества)
    ("Шаги за день → глубокий %", "steps", "main_deep_pct"),
    ("Тренировка (мин) → глубокий %", "exercise_min", "main_deep_pct"),
    ("Длительность сна → глубокий %", "total_sleep_min", "main_deep_pct"),
    ("Длиннейшая сессия → глубокий %", "longest_block_min", "main_deep_pct"),
    ("HRV RMSSD → глубокий %", "main_hrv_rmssd_avg", "main_deep_pct"),
    ("Мин. пульс → глубокий %", "main_hr_min", "main_deep_pct"),
]


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize(rows: list[dict], cols: list[str]) -> dict[str, dict]:
    """По каждой колонке: n, mean, median, sd, min, max (пустые ячейки игнорируются)."""
    out: dict[str, dict] = {}
    for col in cols:
        vals = sorted(v for v in (_f(r.get(col)) for r in rows) if v is not None)
        n = len(vals)
        if n == 0:
            continue
        mean = sum(vals) / n
        median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
        out[col] = {"n": n, "mean": mean, "median": median, "sd": sd,
                    "min": vals[0], "max": vals[-1]}
    return out


def pearson(xs: list, ys: list) -> tuple[float | None, int]:
    """Коэффициент корреляции Пирсона по парам без пропусков. (r, n)."""
    pairs = [(x, y) for x, y in zip(xs, ys)
             if _f(x) is not None and _f(y) is not None]
    n = len(pairs)
    if n < 3:
        return None, n
    xs2 = [float(p[0]) for p in pairs]
    ys2 = [float(p[1]) for p in pairs]
    mx, my = sum(xs2) / n, sum(ys2) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs2))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys2))
    if sx == 0 or sy == 0:
        return None, n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs2, ys2))
    return cov / (sx * sy), n


# колонки дневного контекста, приклеиваемые к ночи
_CTX_COLS = ("steps", "distance_km", "active_min", "calories_active",
             "exercise_min", "exercise_count", "nap_min", "nap_count")


def master_rows(data: SleepData) -> list[dict]:
    """Каждая ночь + дневной контекст той же даты сна (для корреляций день→ночь)."""
    ctx = {c["date"]: c for c in data.daily_context}
    out = []
    for n in data.nights:
        row = dict(n)
        c = ctx.get(n["sleep_date"], {})
        for k in _CTX_COLS:
            row[k] = c.get(k, "")
        out.append(row)
    return out


def correlations(data: SleepData,
                 pairs: list[tuple[str, str, str]] = CORR_PAIRS) -> list[dict]:
    """Список {label, x, y, r, n}, отсортированный по убыванию |r|."""
    rows = master_rows(data)
    out = []
    for label, cx, cy in pairs:
        r, n = pearson([row.get(cx) for row in rows], [row.get(cy) for row in rows])
        if r is not None:
            out.append({"label": label, "x": cx, "y": cy, "r": round(r, 2), "n": n})
    out.sort(key=lambda d: -abs(d["r"]))
    return out
