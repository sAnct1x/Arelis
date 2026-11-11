"""Near-duplicate facts update one dated row instead of inserting another."""

from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    "texts",
    [
        ("the mass is 5 kg", "the mass is 6 kg"),
        (
            "weekly run distance is 10 kilometers",
            "weekly run distance is 24 kilometers",
        ),
        ("meeting on 2026-01-01", "meeting on 2026-01-02"),
        ("allergic to peanuts", "not allergic to peanuts"),
        ("I work on Tuesdays", "I do not work on Tuesdays"),
        ("likes cats", "likes cats and dogs", "likes dogs"),
    ],
)
def test_distinct_facts_stay_separate(tmp_path: Path, texts: tuple[str, ...]) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        ids: list[int] = []
        for text in texts:
            fact_id = store.add_fact(text, source="explicit", status="active")
            assert fact_id is not None
            ids.append(fact_id)
        rows = _active(store)
        assert len(rows) == len(texts)
        assert len(set(ids)) == len(texts)
        assert {str(row["text"]) for row in rows} == set(texts)
        by_id = {int(row["id"]): str(row["text"]) for row in rows}
        for fact_id, text in zip(ids, texts, strict=True):
            assert by_id[fact_id] == text
    finally:
        store.close()


def test_on_pending_fact_does_not_revive_forgotten_claim(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        fact_id = store.add_fact(
            "favorite fruit is mango",
            source="explicit",
            status="active",
        )
        assert fact_id is not None
        assert store.forget_fact("favorite fruit is mango") == 1
        store.on_pending_fact("the user's favorite fruit is mango")
        assert [row for row in _active(store) if "mango" in str(row["text"])] == []
        row = next(item for item in store.list_facts() if int(item["id"]) == fact_id)
        assert row["status"] == "rejected"
    finally:
        store.close()


def test_explicit_remember_reactivates_forgotten_claim(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        fact_id = store.add_fact(
            "favorite fruit is mango",
            source="explicit",
            status="active",
        )
        assert fact_id is not None
        _backdate(store, fact_id, "2026-01-01T00:00:00")
        assert store.forget_fact("favorite fruit is mango") == 1
        remembered = store.add_fact(
            "the user's favorite fruit is mango",
            source="explicit",
            status="active",
        )
        assert remembered == fact_id
        rows = _active(store)
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == fact_id
        assert row["text"] == "the user's favorite fruit is mango"
        assert row["created_at"] == "2026-01-01T00:00:00"
        assert str(row["updated_at"]) > "2026-01-01T00:00:00"
        assert row["status"] == "active"
    finally:
        store.close()
