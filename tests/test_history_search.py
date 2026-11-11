"""History search box must hit message bodies, not just titles.

Roadmap 6.6. The box in HistoryPanel is the same one; this file drives
filter_history_sessions so Qt is optional. The store path is
MemoryStore.search (FTS5 / LIKE) — do not invent a second index.

Mutants this file is supposed to catch:

1. body match missing (title-only filter; telescope in the assistant
   turn never surfaces the thread).
2. title match missing (body index only; a title hit with no FTS hit
   disappears).
3. empty query hides everything (whitespace / blank must keep the
   current list).
4. a match outside the loaded History window (the last 100 sessions)
   never appears, or a thread with many body hits crowds others out
   of a message-hit cap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore
from arelis.ui.panels.history import filter_history_sessions


def _archive(tmp_path: Path) -> tuple[MemoryStore, list[dict[str, str]], str, str]:
    store = MemoryStore(tmp_path / "memory.db")
    memory = SessionMemory(sink=store)

    weather = store.start_session()
    memory.add("user", "how's the weather looking")
    memory.add("assistant", "The telescope pointing model drifted again.")

    groceries = store.start_session()
    memory.add("user", "grocery list for sunday")
    memory.add("assistant", "Buy milk and eggs.")

    sessions = [
        {
            "id": str(row["id"]),
            "title": str(row.get("title") or ""),
            "started_at": str(row.get("started_at") or ""),
        }
        for row in store.list_sessions()
    ]
    return store, sessions, weather, groceries


def test_body_match_uses_store_search(tmp_path: Path) -> None:
    """Mutant: filter stays title-only and never calls MemoryStore.search."""
    store, sessions, weather, _groceries = _archive(tmp_path)
    assert store.search("telescope"), "fixture must land in messages_fts"
    rows = filter_history_sessions(sessions, "telescope", store=store)
    assert [row["id"] for row in rows] == [weather]
    store.close()


def test_title_match_still_works_without_body_hits() -> None:
    """Mutant: only body ids count, so a title hit with an empty search dies."""
    sessions = [
        {"id": "a", "title": "Math homework", "started_at": ""},
        {"id": "b", "title": "Weather", "started_at": ""},
    ]
    rows = filter_history_sessions(sessions, "homework", search=lambda _q: [])
    assert [row["id"] for row in rows] == ["a"]


def test_empty_query_keeps_the_current_list(tmp_path: Path) -> None:
    """Mutant: blank / whitespace query returns nothing."""
    store, sessions, _weather, _groceries = _archive(tmp_path)
    assert len(sessions) == 2
    for query in ("", "   ", "\t"):
        rows = filter_history_sessions(sessions, query, store=store)
        assert [row["id"] for row in rows] == [row["id"] for row in sessions]
    store.close()


def test_unrelated_query_drops_non_matches() -> None:
    sessions = [
        {"id": "a", "title": "Weather", "started_at": ""},
        {"id": "b", "title": "Math", "started_at": ""},
    ]
    rows = filter_history_sessions(sessions, "zebra", search=lambda _q: [])
    assert rows == []

def test_search_reaches_chats_outside_the_loaded_list(tmp_path: Path) -> None:
    """Mutant: filter only the 100-row list, or cap on message hits not sessions."""
    store = MemoryStore(tmp_path / "memory.db")
    memory = SessionMemory(sink=store)

    buried = store.start_session()
    memory.add("user", "old homework question")
    memory.add("assistant", "the telescope pointing model drifted")

    crowded = store.start_session()
    memory.add("user", "repeat this please")
    for index in range(250):
        memory.add("assistant", f"common word mention {index}")

    # Newer chats push buried and crowded off a 100-row History window.
    for index in range(120):
        store.start_session()
        memory.add("user", f"recent chat {index}")
        memory.add("assistant", "ok")

    loaded = [
        {
            "id": str(row["id"]),
            "title": str(row.get("title") or ""),
            "started_at": str(row.get("started_at") or ""),
        }
        for row in store.list_sessions(limit=100)
    ]
    loaded_ids = {row["id"] for row in loaded}
    assert buried not in loaded_ids
    assert crowded not in loaded_ids

    body_rows = filter_history_sessions(loaded, "telescope", store=store)
    assert buried in {row["id"] for row in body_rows}

    title_rows = filter_history_sessions(loaded, "homework", store=store)
    assert buried in {row["id"] for row in title_rows}

    common_rows = filter_history_sessions(loaded, "common", store=store)
    assert crowded in {row["id"] for row in common_rows}
    store.close()

@pytest.mark.parametrize("use_fts", [True, False], ids=["fts", "like"])
def test_search_treats_like_wildcards_as_literal(tmp_path: Path, use_fts: bool) -> None:
    """Mutant: unescaped LIKE % and _ match every title, and 100% matches 1000."""
    store = MemoryStore(tmp_path / "memory.db")
    if use_fts:
        assert store.fts_available
    else:
        store._fts = False
    memory = SessionMemory(sink=store)

    percent = store.start_session()
    memory.add("user", "growth was 100% this year")
    memory.add("assistant", "growth was 100% this year")

    thousand = store.start_session()
    memory.add("user", "growth was 1000 this year")
    memory.add("assistant", "growth was 1000 this year")

    underscored = store.start_session()
    memory.add("user", "see the file_name notes")
    memory.add("assistant", "see the file_name notes")

    store.start_session()
    memory.add("user", "ordinary chat about weather")
    memory.add("assistant", "it will be sunny")

    def ids(query: str) -> set[str]:
        return {str(row["id"]) for row in store.search_sessions(query)}

    assert ids("100%") == {percent}
    assert thousand not in ids("100%")
    assert ids("%") == {percent}
    assert ids("_") == {underscored}
    store.close()

