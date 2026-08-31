"""Dated SQLite snapshot of memory.db."""

from __future__ import annotations

from pathlib import Path

from arelis.memory.backup import backup_memory_db
from arelis.memory.store import MemoryStore


def test_backup_writes_dated_copy_and_skips_same_day(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    dest = tmp_path / "backups"
    store = MemoryStore(db)
    store.start_session()
    assert db.is_file()

    first = backup_memory_db(db, dest_dir=dest, keep=3)
    assert first is not None
    assert first.is_file()
    assert first.stat().st_size > 0
    assert first.parent == dest

    again = backup_memory_db(db, dest_dir=dest, keep=3)
    assert again == first
    assert len(list(dest.glob("memory-*.db"))) == 1


def test_backup_missing_db_is_noop(tmp_path: Path) -> None:
    assert backup_memory_db(tmp_path / "nope.db", dest_dir=tmp_path / "b") is None


def test_backup_prunes_old_copies(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    dest = tmp_path / "backups"
    MemoryStore(db).start_session()
    dest.mkdir()
    for day in ("20260101", "20260102", "20260103"):
        (dest / f"memory-{day}.db").write_bytes(b"old")
    backup_memory_db(db, dest_dir=dest, keep=2)
    names = sorted(p.name for p in dest.glob("memory-*.db"))
    assert len(names) <= 2
    assert any(n.startswith("memory-") for n in names)


def test_backup_keep_zero_writes_nothing_and_clears(tmp_path: Path) -> None:
    db = tmp_path / "memory.db"
    dest = tmp_path / "backups"
    MemoryStore(db).start_session()
    dest.mkdir()
    (dest / "memory-20260101.db").write_bytes(b"old")
    assert backup_memory_db(db, dest_dir=dest, keep=0) is None
    assert list(dest.glob("memory-*.db")) == []
