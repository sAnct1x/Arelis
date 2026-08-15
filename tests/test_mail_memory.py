"""Opt-in mail peek index for recall — never marks messages read."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.mail import MailAccount
from arelis.memory.mail_index import MailIndexer, MailPeek
from arelis.memory.store import MemoryStore
from arelis.tools.recall import RecallTool


def test_mail_indexer_upserts_and_prunes_outside_the_window(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    peeks = [
        MailPeek("1", "mom@example.com", "Trip plans", "2026-08-01", True, "Beach house"),
        MailPeek("2", "bank@example.com", "Statement", "2026-08-02", False, "Balance ok"),
    ]

    def fetch() -> list[MailPeek]:
        return list(peeks)

    indexer = MailIndexer(
        store,
        MailAccount("me@example.com", "pw"),
        fetch=fetch,
        min_interval_s=60,
    )
    assert indexer.sync_batch(force=True) == 2
    assert store.search_mail("Beach")
    assert store.search_mail("Statement")

    peeks[:] = [
        MailPeek("2", "bank@example.com", "Statement", "2026-08-02", False, "Balance ok"),
        MailPeek("3", "work@example.com", "Standup", "2026-08-03", True, "Bring slides"),
    ]
    assert indexer.sync_batch(force=True) == 2
    assert store.search_mail("Beach") == []
    assert store.search_mail("slides")
    store.close()


def test_mail_indexer_respects_min_interval(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    calls = {"n": 0}

    def fetch() -> list[MailPeek]:
        calls["n"] += 1
        return [
            MailPeek("9", "a@b.c", "Hi", "2026-08-07", True, "hello there"),
        ]

    indexer = MailIndexer(
        store,
        MailAccount("me@example.com", "pw"),
        fetch=fetch,
        min_interval_s=3600,
    )
    assert indexer.sync_batch(force=True) == 1
    assert indexer.sync_batch() == 0
    assert calls["n"] == 1
    store.close()


@pytest.mark.asyncio
async def test_recall_source_mail(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.upsert_mail_message(
        uid="42",
        sender="mom@example.com",
        subject="Trip plans",
        date_text="2026-07-01",
        unread=False,
        body="We booked the cabin near the lake.",
    )
    tool = RecallTool(store)
    result = await tool.run(action="search", query="cabin", source="mail")
    assert result.ok
    assert "cabin" in result.output.lower()
    assert "mail=" in result.output
    miss = await tool.run(action="search", query="cabin", source="chat")
    assert miss.ok
    assert "No past messages matched" in miss.output
    store.close()
