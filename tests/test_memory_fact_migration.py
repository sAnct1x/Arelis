"""v12 archives must merge near-duplicate facts and keep leftover proposals."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from arelis.memory import MemoryStore
from arelis.memory.store import SCHEMA_VERSION


def _write_v12_fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT,
                key TEXT
            );
            INSERT INTO facts
                (text, source, status, created_at, updated_at, session_id, key)
            VALUES
                ('the user''s favorite fruit is mango', 'explicit', 'active',
                 '2026-01-01T00:00:00', '2026-01-01T00:00:00', NULL, NULL),
                ('favorite fruit is mango', 'proposed', 'active',
                 '2026-02-01T00:00:00', '2026-06-01T00:00:00', NULL, NULL),
                ('climbs on Tuesdays', 'proposed', 'pending',
                 '2026-03-01T00:00:00', '2026-03-01T00:00:00', NULL, NULL),
                ('works on Arelis', 'explicit', 'active',
                 '2026-04-01T00:00:00', '2026-04-01T00:00:00', NULL, NULL);
            PRAGMA user_version = 12;
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_v12_facts_are_deduped_and_pending_promoted(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _write_v12_fixture(path)

    probe = sqlite3.connect(path)
    try:
        assert int(probe.execute("PRAGMA user_version").fetchone()[0]) == 12
        assert probe.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 4
        pending = probe.execute(
            "SELECT COUNT(*) FROM facts WHERE status = 'pending'"
        ).fetchone()[0]
        assert pending == 1
    finally:
        probe.close()

    store = MemoryStore(path)
    try:
        assert store.schema_version == SCHEMA_VERSION
        active = store.list_facts(status="active")
        texts = {str(row["text"]) for row in active}
        assert "favorite fruit is mango" in texts
        assert "the user's favorite fruit is mango" not in texts
        assert "climbs on Tuesdays" in texts
        assert "works on Arelis" in texts
        assert len(active) == 3
        assert store.list_facts(status="pending") == []

        mango = next(row for row in active if "mango" in str(row["text"]))
        assert mango["created_at"] == "2026-01-01T00:00:00"
        assert mango["updated_at"] == "2026-06-01T00:00:00"
        rejected = store.list_facts(status="rejected")
        assert len(rejected) == 1
        assert "favorite fruit is mango" in str(rejected[0]["text"])
        assert rejected[0]["id"] != mango["id"]

        climb = next(row for row in active if "climbs" in str(row["text"]))
        assert climb["created_at"] == "2026-03-01T00:00:00"
        work = next(row for row in active if "Arelis" in str(row["text"]))
        assert work["created_at"] == "2026-04-01T00:00:00"
        assert work["status"] == "active"
    finally:
        store.close()


def _write_v12_rejected_mango_fixture(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT,
                key TEXT
            );
            INSERT INTO facts
                (text, source, status, created_at, updated_at, session_id, key)
            VALUES
                ('favorite fruit is mango', 'explicit', 'rejected',
                 '2026-01-01T00:00:00', '2026-02-01T00:00:00', NULL, NULL),
                ('the user''s favorite fruit is mango', 'proposed', 'pending',
                 '2026-03-01T00:00:00', '2026-03-01T00:00:00', NULL, NULL),
                ('works on Arelis', 'explicit', 'active',
                 '2026-04-01T00:00:00', '2026-04-01T00:00:00', NULL, NULL);
            PRAGMA user_version = 12;
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_v12_rejected_claim_is_not_revived_by_pending_wording(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _write_v12_rejected_mango_fixture(path)

    store = MemoryStore(path)
    try:
        assert store.schema_version == SCHEMA_VERSION
        active = store.list_facts(status="active")
        texts = {str(row["text"]) for row in active}
        assert texts == {"works on Arelis"}
        assert store.list_facts(status="pending") == []
        rejected = store.list_facts(status="rejected")
        mango = [row for row in rejected if "mango" in str(row["text"])]
        assert mango
        assert all(row["status"] == "rejected" for row in mango)
        assert all("mango" not in str(row["text"]) for row in active)
    finally:
        store.close()
