"""Optional snapshot of memory.db. Off by default.

A dated copy of a 20–90 MB database every day, kept for two weeks, is how
``data/backups/`` grew past a gigabyte without anyone asking for it. The
function still exists for a deliberate ``keep=N`` call. Launch does not
write copies.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from arelis.paths import state_dir

log = logging.getLogger(__name__)

# Zero: do not write dated copies; delete any that are already there.
MEMORY_BACKUP_KEEP = 0


def _default_db() -> Path:
    return state_dir() / "memory.db"


def _default_dir() -> Path:
    return state_dir() / "backups"


def backup_memory_db(
    db_path: Path | None = None,
    *,
    dest_dir: Path | None = None,
    keep: int = MEMORY_BACKUP_KEEP,
) -> Path | None:
    """Write ``memory-YYYYMMDD.db`` if today's copy is missing. Keep ``keep`` files.

    ``keep <= 0`` writes nothing and removes leftover copies.
    """
    src = Path(db_path) if db_path is not None else _default_db()
    out_dir = Path(dest_dir) if dest_dir is not None else _default_dir()
    try:
        if int(keep) <= 0:
            prune_memory_backups(dest_dir=out_dir, keep=0)
            return None
        if not src.is_file() or src.stat().st_size <= 0:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        dest = out_dir / f"memory-{stamp}.db"
        if dest.is_file() and dest.stat().st_size > 0:
            prune_memory_backups(dest_dir=out_dir, keep=keep)
            return dest
        _sqlite_copy(src, dest)
        prune_memory_backups(dest_dir=out_dir, keep=keep)
        log.info("memory backup wrote %s", dest)
        return dest
    except Exception:
        log.exception("memory backup failed from %s", src)
        return None


def prune_memory_backups(*, dest_dir: Path | None = None, keep: int = MEMORY_BACKUP_KEEP) -> int:
    """Delete dated ``memory-*.db`` copies beyond ``keep`` (0 = all)."""
    out_dir = Path(dest_dir) if dest_dir is not None else _default_dir()
    if not out_dir.is_dir():
        return 0
    files = sorted(
        (p for p in out_dir.glob("memory-*.db") if p.is_file()),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = 0
    for stale in files[max(0, int(keep)) :]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            log.warning("could not remove old memory backup %s", stale)
    return removed


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
