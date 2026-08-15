"""Semantic recall: vector index in the background, RRF merge at search time."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from arelis.core.memory import SessionMemory
from arelis.memory.indexer import MemoryIndexer
from arelis.memory.rrf import merge_ranked_hits
from arelis.memory.store import MemoryStore, SearchHit
from arelis.tools.recall import RecallTool


def _hit(message_id: int, content: str = "x") -> SearchHit:
    return SearchHit(
        message_id=message_id,
        session_id="s",
        role="user",
        content=content,
        created_at="2026-01-01T00:00:00+00:00",
        title="t",
    )


def test_reciprocal_rank_fusion_prefers_agreement() -> None:
    fts = [_hit(1, "a"), _hit(2, "b"), _hit(3, "c")]
    vec = [_hit(2, "b"), _hit(4, "d"), _hit(1, "a")]
    merged = merge_ranked_hits(fts, vec, limit=3)
    assert next(h.message_id for h in merged) == 2


def test_vector_search_finds_a_near_neighbour(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "We aligned the interferometer mirrors.")
    memory.add("user", "I bought groceries.")
    rows = store.get_messages(store.session_id or "")
    store.upsert_embedding(int(rows[0]["id"]), "nomic-embed-text", [1.0, 0.0, 0.0])
    store.upsert_embedding(int(rows[1]["id"]), "nomic-embed-text", [0.0, 1.0, 0.0])

    hits = store.vector_search([0.9, 0.1, 0.0], model="nomic-embed-text", limit=1)
    assert hits and "interferometer" in hits[0].content
    store.close()


@pytest.mark.asyncio
async def test_indexer_embeds_unindexed_messages(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    SessionMemory(sink=store).add("user", "telescope pointing model")

    class _Prov:
        async def embed(self, model, texts):
            return [[1.0, 0.0] for _ in texts]

        async def list_models(self):
            return ["nomic-embed-text:latest"]

    indexer = MemoryIndexer(store, _Prov(), model="nomic-embed-text")  # type: ignore[arg-type]
    assert await indexer.run_batch() == 1
    assert store.unembedded_messages(limit=10) == []
    store.close()


@pytest.mark.asyncio
async def test_recall_merges_keyword_and_vector_hits(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "The interferometer baseline drifted.")
    memory.add("user", "Unrelated groceries note.")
    rows = store.get_messages(store.session_id or "")
    store.upsert_embedding(int(rows[0]["id"]), "nomic-embed-text", [1.0, 0.0])
    store.upsert_embedding(int(rows[1]["id"]), "nomic-embed-text", [0.0, 1.0])

    async def embed(model, texts):
        return [[1.0, 0.0] for _ in texts]

    async def available():
        return True

    tool = RecallTool(
        store,
        embed=embed,
        embed_model="nomic-embed-text",
        embed_available=available,
    )
    # Query has no keyword overlap with "interferometer", but the vector does.
    result = await tool.run(action="search", query="the telescope thing")
    assert result.ok
    assert result.data["mode"] in {"hybrid", "semantic"}
    assert "interferometer" in result.output.lower()
    store.close()


@pytest.mark.asyncio
async def test_recall_says_keyword_only_once_when_embed_model_is_missing(
    tmp_path: Path,
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    SessionMemory(sink=store).add("user", "I climb on Thursdays.")

    async def embed(model, texts):
        raise AssertionError("embed must not run when unavailable")

    async def available():
        return False

    tool = RecallTool(
        store, embed=embed, embed_available=available, embed_model="nomic-embed-text"
    )
    first = await tool.run(action="search", query="climb")
    second = await tool.run(action="search", query="climb")
    assert "ollama pull nomic-embed-text" in first.output
    assert "ollama pull nomic-embed-text" not in second.output
    store.close()


def test_cosine_helpers_reject_empty_query(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    assert store.vector_search(np.zeros(3), model="nomic-embed-text") == []
    store.close()
