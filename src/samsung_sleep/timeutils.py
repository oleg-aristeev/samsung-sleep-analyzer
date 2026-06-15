"""Время и числа. Главное правило: в CSV экспорта всё в UTC, локальный пояс
лежит отдельной колонкой time_offset и его нужно ПРИБАВЛЯТЬ."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_OFFSET_RE = re.compile(r"UTC([+-])(\d{2})(\d{2})")


def parse_dt(s: str | None) -> datetime | None:
    """Разбирает '2026-04-17 15:00:00.000' (UTC, naive)."""
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")


def parse_offset(s: str | None) -> timedelta:
    """'UTC+0300' -> timedelta(hours=3). Неизвестное -> 0."""
    m = _OFFSET_RE.match(s or "")
    if not m:
        return timedelta(0)
    sign = 1 if m.group(1) == "+" else -1
    return sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))


def epoch_ms(dt_utc: datetime) -> int:
    """naive-UTC datetime -> миллисекунды Unix epoch (как в JSON-бинах)."""
    return int(dt_utc.replace(tzinfo=timezone.utc).timestamp() * 1000)


def from_epoch_ms(ms: int) -> datetime:
    """Обратно: epoch ms -> naive-UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def fmt_minute(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def parse_minute(s: str) -> datetime:
    """Обратно к fmt_minute: 'YYYY-MM-DD HH:MM' -> datetime."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


def rnd(x: float | None, n: int = 1):
    """Округление с превращением None в '' (для пустых ячеек CSV)."""
    return round(x, n) if x is not None else ""


def mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None
