"""Record a take as jsonl. If it is not in a take, it did not happen."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from arelis.paths import outputs_dir
from arelis.spatial.types import HandsFrame

MAX_TAKE_FRAMES = 2000
MAX_TAKE_SECONDS = 60.0
KEEP_LAST_TAKES = 12
KEEP_MARKER = "keep"
STILL_KEEP = 16


def takes_root() -> Path:
    return outputs_dir() / "physics" / "takes"


def prune_takes(root: Path | None = None, keep_last: int = KEEP_LAST_TAKES) -> list[Path]:
    """Delete oldest unpinned take folders. Pinned = a `keep` file in the folder."""
    base = root if root is not None else takes_root()
    if not base.is_dir():
        return []
    folders = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    removed: list[Path] = []
    kept = 0
    for folder in folders:
        if (folder / KEEP_MARKER).exists():
            continue
        if kept < keep_last:
            kept += 1
            continue
        shutil.rmtree(folder, ignore_errors=True)
        removed.append(folder)
    return removed


def prune_stills(
    directory: Path,
    *,
    prefix: str = "camera_",
    suffix: str = ".jpg",
    keep: int = STILL_KEEP,
) -> list[Path]:
    """Keep the newest stills; delete the rest. Never touches other files."""
    if not directory.is_dir():
        return []
    files = sorted(
        [
            p
            for p in directory.iterdir()
            if p.is_file() and p.name.startswith(prefix) and p.name.endswith(suffix)
        ],
        key=lambda p: p.name,
        reverse=True,
    )
    removed: list[Path] = []
    for path in files[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


@dataclass
class TakeWriter:
    path: Path
    meta: dict[str, Any]
    _fh: TextIO | None = field(default=None, repr=False)
    frames: int = 0
    capped: bool = False
    _t0: float | None = field(default=None, repr=False)

    @classmethod
    def start(cls, meta: dict[str, Any], *, root: Path | None = None) -> TakeWriter:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = root if root is not None else takes_root()
        folder = base / stamp
        folder.mkdir(parents=True, exist_ok=True)
        meta_path = folder / "meta.json"
        body = dict(meta)
        body["started_at"] = stamp
        meta_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
        log_path = folder / "frames.jsonl"
        fh = log_path.open("a", encoding="utf-8")
        prune_takes(base)
        return cls(path=folder, meta=body, _fh=fh)

    def write(self, frame: HandsFrame, extra: dict[str, Any] | None = None) -> bool:
        """Append one row. False if the take hit a cap (caller should close)."""
        if self._fh is None or self.capped:
            return False
        if self._t0 is None:
            self._t0 = float(frame.t_capture)
        elapsed = float(frame.t_capture) - self._t0
        if self.frames >= MAX_TAKE_FRAMES or elapsed >= MAX_TAKE_SECONDS:
            self.capped = True
            return False
        row = frame.to_log()
        if extra:
            row.update(extra)
        self._fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.frames += 1
        return True

    def close(self) -> Path:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        summary = self.path / "summary.json"
        summary.write_text(
            json.dumps(
                {
                    "frames": self.frames,
                    "dir": str(self.path),
                    "capped": self.capped,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return self.path
