"""Параметры обработки. Меняются в CLI-флагах или в сайдбаре Streamlit,
чтобы «итеративно крутить» процедуру, не трогая код."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Всё, что влияет на агрегацию. frozen=True -> можно кэшировать в Streamlit."""

    # Граница «суток сна»: ночь относится к дате вечера засыпания.
    # 12 = полдень (сон с вечера до утра попадает в дату вечера).
    sleep_day_boundary_hour: int = 12

    # Разрывы записи: интервал без сессий сна длиннее этого считается «дырой».
    gap_min_hours: float = 18.0

    # Внутри дыры непрерывный период без пульса >= этого = «часы были сняты».
    watch_off_window_hours: float = 2.0

    # Если в дыре суммарно столько часов часы сняты — трактуем как незаписанный сон,
    # а не как реальное бодрствование.
    watch_off_for_sleep_hours: float = 3.0

    # Качество дня по числу часов с пульсом: <= not_worn -> watch_not_worn;
    # < partial -> partial_wear; иначе ok.
    not_worn_max_hours: int = 4
    partial_max_hours: int = 16
