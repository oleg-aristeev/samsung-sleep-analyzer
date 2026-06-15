"""CLI: экспорт Samsung Health (.zip или папка) -> CSV + (опционально) HTML-дашборд.

    samsung-sleep export.zip -o output
    samsung-sleep export.zip -o output --html
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .charts import write_html
from .config import Config
from .export import write_all
from .loader import Export
from .transform import build_all


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="samsung-sleep",
        description="Экспорт Samsung Health -> аккуратные CSV о сне + дашборд + контекст для LLM",
    )
    p.add_argument("source", help="путь к .zip архиву экспорта или распакованной папке")
    p.add_argument("-o", "--out", default="output", help="куда сложить результат (по умолч. ./output)")
    p.add_argument("--html", action="store_true", help="также собрать sleep_dashboard.html")
    p.add_argument("--rolling-days", type=int, default=7, help="окно скользящего среднего для графика сна")
    p.add_argument("--sleep-day-boundary", type=int, default=Config.sleep_day_boundary_hour,
                   metavar="HOUR", help="час-граница 'суток сна' (по умолч. 12)")
    p.add_argument("--gap-min-hours", type=float, default=Config.gap_min_hours,
                   help="порог разрыва записи в часах (по умолч. 18)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = p.parse_args(argv)

    if not os.path.exists(a.source):
        print(f"Нет такого пути: {a.source}", file=sys.stderr)
        return 2

    config = Config(sleep_day_boundary_hour=a.sleep_day_boundary,
                    gap_min_hours=a.gap_min_hours)
    try:
        with Export(a.source) as ex:
            data = build_all(ex, config)
    except (ValueError, TypeError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1

    counts = write_all(data, a.out)
    print(f"Готово -> {a.out}/")
    for fname, n in counts.items():
        print(f"  {fname:<22} {n if fname.endswith('.csv') else ''}")
    if a.html:
        html_path = os.path.join(a.out, "sleep_dashboard.html")
        write_html(data, html_path, rolling_days=a.rolling_days)
        print(f"  sleep_dashboard.html   (открыть в браузере)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
