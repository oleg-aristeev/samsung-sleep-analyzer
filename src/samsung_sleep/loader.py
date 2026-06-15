"""Единый доступ к экспорту Samsung Health — хоть .zip, хоть распакованная папка.

Внутри экспорта:
    <корень>/com.samsung.*.<id>.csv           - таблицы (первая строка - метаданные)
    <корень>/jsons/<таблица>/<символ>/<uuid>.*.json - поминутные данные (epoch ms)
Корень может быть как самой папкой, так и вложенной (zip обычно нестит всё в одну).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile
from typing import Any, BinaryIO

# по этому файлу опознаём корень экспорта (а не sleep_stage и т.п.)
_ROOT_MARKER = re.compile(r"com\.samsung\.shealth\.sleep\.\d+\.csv$")


class Export:
    """Читает таблицы и JSON-бины из экспорта независимо от того, zip это или папка.

    Использование:
        with Export("export.zip") as ex:
            rows = ex.load_table("com.samsung.shealth.sleep")
    """

    def __init__(self, source: str | os.PathLike | BinaryIO):
        self._zip: zipfile.ZipFile | None = None
        self._dir: str | None = None
        self._index: dict[str, str] = {}  # относительный posix-путь -> бэкенд-ключ
        self.name = "export"

        if hasattr(source, "read"):  # файловый объект -> только zip (например, загрузка в Streamlit)
            self._open_zip(source)
        elif isinstance(source, (str, os.PathLike)):
            path = os.fspath(source)
            if os.path.isdir(path):
                self._open_dir(path)
            elif zipfile.is_zipfile(path):
                self._open_zip(path)
                self.name = os.path.splitext(os.path.basename(path))[0]
            else:
                raise ValueError(f"Не папка и не zip-архив: {path}")
        else:
            raise TypeError(f"Не поддерживаемый источник: {type(source)!r}")

        if not any(_ROOT_MARKER.search(rel) for rel in self._index):
            raise ValueError(
                "Это не похоже на экспорт Samsung Health: "
                "не найден com.samsung.shealth.sleep.*.csv"
            )

    # ---------------------------------------------------------- инициализация

    def _open_dir(self, path: str) -> None:
        root = _find_root(
            (os.path.join(dp, fn), fn)
            for dp, _dirs, files in os.walk(path)
            for fn in files
        )
        self._dir = root or path
        self.name = os.path.basename(os.path.normpath(self._dir))
        for dp, _dirs, files in os.walk(self._dir):
            for fn in files:
                full = os.path.join(dp, fn)
                rel = os.path.relpath(full, self._dir).replace(os.sep, "/")
                self._index[rel] = full

    def _open_zip(self, src) -> None:
        self._zip = zipfile.ZipFile(src)
        members = [m for m in self._zip.namelist() if not m.endswith("/")]
        prefix = _zip_prefix(members)
        for m in members:
            if prefix and not m.startswith(prefix):
                continue
            self._index[m[len(prefix):]] = m

    # ----------------------------------------------------------------- доступ

    def has(self, table: str) -> bool:
        return self.find_table(table) is not None

    def find_table(self, table: str) -> str | None:
        """Имя файла таблицы: точное совпадение `<table>.<id>.csv` в корне."""
        pat = re.compile(re.escape(table) + r"\.\d+\.csv")
        for rel in self._index:
            if "/" not in rel and pat.fullmatch(rel):
                return rel
        return None

    def load_table(self, table: str) -> list[dict]:
        """Строки таблицы как list[dict]. Первая строка файла (метаданные) пропускается."""
        rel = self.find_table(table)
        if not rel:
            return []
        with self._open_text(rel) as f:
            f.readline()  # строка метаданных: <имя_таблицы>,<версия>,<счётчик>
            return list(csv.DictReader(f))

    def load_json(self, table: str, filename: str) -> Any:
        """JSON-бин по имени из колонки binning_data/data/custom."""
        if not filename:
            return None
        rel = f"jsons/{table}/{filename[0]}/{filename}"
        if rel not in self._index:
            suffix = "/" + filename
            prefix = f"jsons/{table}/"
            rel = next((k for k in self._index
                        if k.startswith(prefix) and k.endswith(suffix)), None)
        if not rel:
            return None
        with self._open_bytes(rel) as f:
            return json.load(f)

    # --------------------------------------------------------- низкоуровневое

    def _open_text(self, rel: str):
        if self._zip is not None:
            return io.TextIOWrapper(self._zip.open(self._index[rel]),
                                    encoding="utf-8-sig", newline="")
        return open(self._index[rel], encoding="utf-8-sig", newline="")

    def _open_bytes(self, rel: str):
        if self._zip is not None:
            return self._zip.open(self._index[rel])
        return open(self._index[rel], "rb")

    # ------------------------------------------------------ менеджер контекста

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def __enter__(self) -> "Export":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _find_root(pairs) -> str | None:
    """pairs: (полный_путь, имя_файла) -> директория, где лежит маркерный CSV."""
    for full, fn in pairs:
        if _ROOT_MARKER.search(fn):
            return os.path.dirname(full)
    return None


def _zip_prefix(members: list[str]) -> str:
    """Общий префикс-папка перед таблицами внутри архива ('' если их нет)."""
    for m in members:
        base = m.rsplit("/", 1)[-1]
        if _ROOT_MARKER.search(base):
            return m[: len(m) - len(base)]
    return ""
