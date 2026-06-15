"""Запись результата на диск: CSV-таблицы + llm_context.md (словарь данных для LLM)."""

from __future__ import annotations

import csv
import os

from .stats import SUMMARY_COLS, correlations, summarize
from .transform import SleepData


def write_csv(path: str, rows: list[dict]) -> None:
    if not rows:
        open(path, "w").close()
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def write_all(data: SleepData, out_dir: str) -> dict[str, int]:
    """Пишет все таблицы и llm_context.md. Возвращает {имя_файла: число_строк}."""
    os.makedirs(out_dir, exist_ok=True)
    counts: dict[str, int] = {}
    for name, rows in data.tables().items():
        write_csv(os.path.join(out_dir, f"{name}.csv"), rows)
        counts[f"{name}.csv"] = len(rows)
    with open(os.path.join(out_dir, "llm_context.md"), "w", encoding="utf-8") as f:
        f.write(build_llm_context(data))
    counts["llm_context.md"] = 1
    return counts


def _direction(r: float) -> str:
    s = "сильная" if abs(r) >= 0.5 else "умеренная" if abs(r) >= 0.3 else "слабая"
    return f"{s} {'прямая' if r > 0 else 'обратная'}"


def _stats_md(data: SleepData) -> str:
    """Сводные статистики по ночам + наблюдаемые корреляции день→ночь."""
    summ = summarize(data.nights, [c for c, _ in SUMMARY_COLS])
    labels = dict(SUMMARY_COLS)
    lines = ["## Статистика по этим данным (по суткам сна)",
             "",
             "| Метрика | n | среднее | медиана | разброс (sd) | мин | макс |",
             "|---|---|---|---|---|---|---|"]
    for col, _ in SUMMARY_COLS:
        s = summ.get(col)
        if not s:
            continue
        lines.append(f"| {labels[col]} | {s['n']} | {s['mean']:.1f} | {s['median']:.1f} "
                     f"| {s['sd']:.1f} | {s['min']:.1f} | {s['max']:.1f} |")
    cors = correlations(data)
    if cors:
        lines += ["", "Наблюдаемые корреляции (Пирсон; |r|≥0.3 заметно, это не доказательство "
                  "причинности и не учитывает сдвиг данных):"]
        for c in cors:
            lines.append(f"- {c['label']}: r = {c['r']:+.2f} ({_direction(c['r'])}, n={c['n']})")
    return "\n".join(lines)


def build_llm_context(data: SleepData) -> str:
    """Текстовый словарь данных + правила интерпретации — прикладывается к запросу в LLM."""
    p = data.profile
    lo, hi = data.date_range
    gaps_md = ""
    if data.data_gaps:
        gaps_md = "\n\nИзвестные разрывы записи в этих данных:\n" + "\n".join(
            f"- {g['no_sleep_record_from']} -> {g['no_sleep_record_to']}"
            f" ({g['gap_hours']} ч): {g['interpretation']}"
            for g in data.data_gaps)
    return f"""# Контекст для интерпретации данных сна (Samsung Health, носимое устройство)

Профиль: пол {p.get('gender', '?')}, дата рождения {p.get('birth_date', '?')},
рост {p.get('height', '?')} см, вес {p.get('weight', '?')} кг.
Период данных: {lo or '?'} - {hi or '?'}.
Все времена в таблицах - ЛОКАЛЬНЫЕ (пояс указан в колонке time_offset).

## sleep_sessions.csv - одна строка = одна сессия сна
- record_kind: session - обычная сессия; combined_night - ночь, склеенная Samsung из
  нескольких кусков; part_of_combined - кусок такой ночи (НЕ суммировать с целой ночью!).
- sleep_date: "сутки сна" с границей в {data.config.sleep_day_boundary_hour}:00
  (ночь относится к дате вечера засыпания).
- in_bed_min - время в постели; sleep_min - фактический сон (без бодрствования).
- sleep_score - оценка Samsung 0-100; efficiency_pct - эффективность сна;
  latency_min - время засыпания; sleep_cycles - число циклов.
- awake/light/deep/rem_min - минуты по стадиям; *_pct_of_sleep - % от фактического сна
  (нормы: deep 13-23%, rem 20-25%).
- awakening_count / longest_awake_min - число и длина awake-сегментов ВНУТРИ сессии. Это
  микропробуждения, размеченные трекером (Samsung держит их в рамках одной сессии) - НЕ
  путать с реальной разрывностью. Для разрывности смотри число сессий и longest_block_min
  в nights.csv.
- hr_min/avg/max - пульс за сессию (минимальный ночной пульс - маркер восстановления);
  hrv_rmssd_avg - HRV RMSSD, мс (сравнивать с личным средним, не с абсолютной нормой);
  resp_rate_avg - дыхание, вдох/мин; spo2_min/avg - сатурация, % (min<90 - красный флаг);
  skin_temp_* - температура кожи запястья, C (важна динамика к личному базлайну).

## nights.csv - одна строка = сутки сна (без дублей combined)
total_* - суммы по всем сессиям суток (включая дневной сон);
main_* - показатели самой длинной (основной) сессии суток.
Разрывность сна (берётся из самих сессий Samsung, не выдумывается из стадий):
sessions_count - сколько отдельных сессий сна было в эти сутки (это и есть «сессии», что
показывают часы; обычно 1-3; каждая отдельная сессия = ты просыпался и снова засыпал);
longest_block_min - длительность самой длинной непрерывной сессии сна за сутки
(чем меньше относительно total_sleep_min, тем сильнее сон раздроблён).

## sleep_stages.csv - гипнограмма
Каждый сегмент стадии (awake/light/deep/rem) с локальным временем; session_id
ссылается на sleep_sessions.session_id (для combined-ночей - на их части).

## daily_context.csv - дневная активность по календарным дням
Шаги, дистанция, активные минуты, активные калории, тренировки (число, минуты, типы),
дневной сон (nap_count/nap_min). Используется для поиска связей "день -> ночь".

## daily_sleep.csv - сон по КАЛЕНДАРНЫМ дням (сессии разрезаны по полуночи)
recorded_sleep_min - записанный сон за календарные сутки; watch_worn_hours - сколько
часов в сутках часы были на руке (по наличию пульса); data_quality: ok / partial_wear /
watch_not_worn. Для вопросов "сколько я спал в день X" использовать ЭТОТ файл.

## data_gaps.csv - разрывы записи сна (> {data.config.gap_min_hours:g} ч)
Каждая строка - период без записей сна с указанием, сколько часов внутри него часы
были сняты с руки (watch_off_hours, watch_off_windows) и готовой интерпретацией.

{_stats_md(data)}

## КРИТИЧЕСКИЕ ПРАВИЛА ИНТЕРПРЕТАЦИИ (нарушение = неверные выводы)
1. ОТСУТСТВИЕ записи сна НЕ означает бодрствование. Часы снимают на зарядку - сон в
   это время не записывается. Перед любым выводом о "долгом бодрствовании" или
   "марафонах без сна" сверься с data_gaps.csv и daily_sleep.data_quality.
2. Дни с data_quality = watch_not_worn / partial_wear исключай из средних по сну
   (recorded_sleep_min там занижен из-за отсутствия данных, а не недосыпа).
3. Засыпание в 4-12 утра здесь НОРМА (сдвинутый ритм), такие сессии полноценно
   оценены трекером - не считай их дневным сном.{gaps_md}
"""
