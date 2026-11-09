"""Bounded on-disk store for dynamic caste definitions.

Lives under the runtime data directory, not the repo. Reads are size-capped.
Writes are same-directory temp + replace. A corrupt file is left in place
and refused; nothing here overwrites it with an empty document.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from sentinel.paths import data_dir

STORE_VERSION = 1
STORE_NAME = "dynamic_castes.json"
MAX_FILE_BYTES = 65_536


class CorruptCasteStore(ValueError):
    """The on-disk document exists but is not a valid caste list."""


class CasteStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / STORE_NAME)
        self._lock = threading.Lock()

    def load(self) -> tuple[list[dict[str, Any]], str]:
        """Return (records, status) where status is ok, missing, or corrupt.

        Corrupt never rewrites the file.
        """
        with self._lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[list[dict[str, Any]], str]:
        if not self.path.exists():
            return [], "missing"
        try:
            size = self.path.stat().st_size
            if size > MAX_FILE_BYTES:
                return [], "corrupt"
            raw = self.path.read_text(encoding="utf-8")
        except OSError:
            return [], "corrupt"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return [], "corrupt"
        if not isinstance(data, dict) or int(data.get("version") or 0) != STORE_VERSION:
            return [], "corrupt"
        rows = data.get("castes")
        if not isinstance(rows, list):
            return [], "corrupt"
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                return [], "corrupt"
            out.append(row)
        return out, "ok"

    def save(self, rows: list[dict[str, Any]]) -> None:
        payload = json.dumps(
            {"version": STORE_VERSION, "castes": rows},
            indent=2,
            ensure_ascii=False,
        )
        if len(payload.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("dynamic caste store would exceed the file size bound")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(self.path)

    def replace_all(self, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            self.save(rows)
