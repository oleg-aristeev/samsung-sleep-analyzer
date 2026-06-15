"""samsung_sleep — превращает экспорт Samsung Health в аккуратные CSV,
интерактивный дашборд и контекст для LLM.

Быстрый путь:
    from samsung_sleep import Export, build_all, write_all
    with Export("export.zip") as ex:
        data = build_all(ex)
    write_all(data, "output")
"""

from __future__ import annotations

from .charts import all_figures, write_html
from .config import Config
from .export import build_llm_context, write_all, write_csv
from .loader import Export
from .stats import correlations, summarize
from .transform import SleepData, build_all

__version__ = "0.1.0"

__all__ = [
    "Export", "Config", "SleepData", "build_all",
    "write_all", "write_csv", "build_llm_context",
    "all_figures", "write_html", "correlations", "summarize", "__version__",
]
