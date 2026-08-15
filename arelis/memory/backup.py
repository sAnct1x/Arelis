"""Dated copies of memory.db so a corrupt file is not total amnesia.

Uses SQLite's backup API so a live WAL is snapshotted consistently. Failures
are logged and swallowed — a backup miss must not block launch.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from arelis.paths import state_dir

log = logging.getLogger(__name__)

_DEFAULT_DB = state_dir() / "memory.db"
_DEFAULT_DIR = state_dir() / "backups"


def backup_memory_db(
    db_path: Path | None = None,
    *,
    dest_dir: Path | None = None,
    keep: int = 14,
) -> Path | None:
    """Write ``memory-YYYYMMDD.db`` if today's copy is missing. Keep ``keep`` files."""
    src = Path(db_path) if db_path is not None else _DEFAULT_DB
    out_dir = Path(dest_dir) if dest_dir is not None else _DEFAULT_DIR
    try:
        if not src.is_file() or src.stat().st_size <= 0:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        dest = out_dir / f"memory-{stamp}.db"
        if dest.is_file() and dest.stat().st_size > 0:
            _prune(out_dir, keep=keep)
            return dest
        _sqlite_copy(src, dest)
        _prune(out_dir, keep=keep)
        log.info("memory backup wrote %s", dest)
        return dest
    except Exception:
        log.exception("memory backup failed from %s", src)
        return None


def _sqlite_copy(src: Path, dest: Path) -> None:
    source = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _prune(out_dir: Path, *, keep: int) -> None:
    files = sorted(
        (p for p in out_dir.glob("memory-*.db") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    for stale in files[max(0, int(keep)) :]:
        try:
            stale.unlink()
        except OSError:
            log.warning("could not remove old memory backup %s", stale)
