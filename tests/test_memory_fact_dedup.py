"""Near-duplicate facts update one dated row instead of inserting another."""

from __future__ import annotations

from pathlib import Path

from arelis.memory import MemoryStore


def _backdate(store: MemoryStore, fact_id: int, stamp: str) -> None:
    store._conn.execute(
        "UPDATE facts SET created_at = ?, updated_at = ? WHERE id = ?",
        (stamp, stamp, fact_id),
    )
    store._conn.commit()


def _active(store: MemoryStore) -> list[dict[str, object]]:
    return store.list_facts(status="active")


def test_near_duplicate_fact_updates_existing_row(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        first = store.add_fact(
            "the user's favorite fruit is mango",
            source="explicit",
            status="active",
        )
        assert first is not None
        _backdate(store, first, "2026-01-01T00:00:00")

        second = store.add_fact(
            "favorite fruit is mango",
            source="explicit",
            status="active",
        )
        assert second == first
        rows = _active(store)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == first
        assert row["text"] == "favorite fruit is mango"
        assert row["created_at"] == "2026-01-01T00:00:00"
        assert str(row["updated_at"]) > "2026-01-01T00:00:00"

        keyed = store.add_fact(
            "climbs on Tuesdays",
            source="explicit",
            status="active",
            key="hobby",
        )
        assert keyed is not None
        _backdate(store, keyed, "2026-02-01T00:00:00")
        again = store.add_fact(
            "climbs on Thursdays",
            source="explicit",
            status="active",
            key="hobby",
        )
        assert again == keyed
        hobby = next(item for item in _active(store) if item["id"] == keyed)
        assert hobby["text"] == "climbs on Thursdays"
        assert hobby["created_at"] == "2026-02-01T00:00:00"
        assert str(hobby["updated_at"]) > "2026-02-01T00:00:00"

        other = store.add_fact(
            "works on Arelis",
            source="explicit",
            status="active",
        )
        assert other not in {first, keyed}
        assert len(_active(store)) == 3

        store.on_pending_fact("lives in New York")
        texts = [str(item["text"]) for item in _active(store)]
        assert "lives in New York" in texts
        assert store.list_facts(status="pending") == []
        store.on_pending_fact("favorite fruit is mango")
        mango = [item for item in _active(store) if "mango" in str(item["text"])]
        assert len(mango) == 1
        assert mango[0]["id"] == first
    finally:
        store.close()
