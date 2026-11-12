"""Relevant memories are ranked into each turn; unrelated rows stay out."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from arelis.core.prompt_sections import append_stable_operating_context
from arelis.memory.retrieval import (
    MAX_ITEMS,
    MAX_PROMPT_CHARS,
    MemoryItem,
    collect_memory_items,
    format_retrieval_block,
    memories_prompt_for_turn,
    retrieve_relevant_memories,
)
from arelis.memory.store import MemoryStore


def _loop(store: MemoryStore, tools: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        config={},
        memory=SimpleNamespace(sink=store),
        tools=tools,
        _expected_tools=set(),
    )


def _add_fact(store: MemoryStore, text: str) -> int:
    fact_id = store.add_fact(text, source="explicit", status="active")
    assert fact_id is not None
    return fact_id


@pytest.mark.asyncio
async def test_turn_gets_ranked_relevant_memories_not_the_whole_store(
    tmp_path, monkeypatch
) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    coffee = _add_fact(store, "The user's usual coffee is an Ethiopian pour-over.")
    dog = _add_fact(store, "The user's dog is named Maple.")
    _add_fact(store, "The user drives a blue Camry.")
    _add_fact(store, "The user's favorite afternoon tea is oolong.")
    _add_fact(store, "The user's favorite programming language is Python.")
    pref = store.set_preference("reply_style", "short spoken answers")
    assert pref is not None
    decision = store.add_decision("Arelis", "Ship Sentinel on Windows first.")
    assert decision is not None
    # A crowded store must not leak into the prompt just because it is recent.
    extra_ids = [
        _add_fact(store, text)
        for text in (
            "The user keeps tax PDFs in a desk drawer.",
            "The user learned clarinet in high school.",
            "The user's favorite soup is lentil.",
            "The user jogs a neighborhood loop on Sunday mornings.",
            "The user labels cables with yellow tape.",
            "The user stores winter coats in the hall closet.",
            "The user buys oat milk for cereal.",
            "The user keeps spare batteries in the junk drawer.",
        )
    ]

    coffee_query = "What coffee do I usually drink?"
    picked = retrieve_relevant_memories(store, coffee_query)
    picked_ids = [item.item_id for item in picked]
    assert f"fact:{coffee}" in picked_ids
    assert f"fact:{dog}" not in picked_ids
    assert f"decision:{decision}" not in picked_ids
    for extra in extra_ids:
        assert f"fact:{extra}" not in picked_ids

    loop = _loop(store)
    coffee_block = await memories_prompt_for_turn(loop, coffee_query)
    assert "Ethiopian pour-over" in coffee_block
    assert "Maple" not in coffee_block
    assert "blue Camry" not in coffee_block
    assert "oolong" not in coffee_block
    assert coffee_block.startswith("Relevant memories for this turn")
    assert coffee_block.count("\n- ") <= MAX_ITEMS
    assert len(coffee_block) <= MAX_PROMPT_CHARS

    # A miss must inject nothing, including when the store is full.
    miss = await memories_prompt_for_turn(loop, "What is the capital of France?")
    assert miss == ""

    # Rejected, forgotten, and still-pending rows must never be retrieved.
    pending = store.add_fact(
        "The user once trained a parrot named Cobalt.",
        source="proposed",
        status="pending",
    )
    forgotten = _add_fact(store, "The user's childhood nickname is Skip.")
    assert pending is not None
    assert store.set_fact_status(forgotten, "rejected")
    candidate_text = " ".join(item.text for item in collect_memory_items(store))
    assert "Cobalt" not in candidate_text
    assert "Skip" not in candidate_text
    parrot_hits = retrieve_relevant_memories(
        store, "What parrot called Cobalt did I train?"
    )
    assert f"fact:{pending}" not in [item.item_id for item in parrot_hits]
    assert all("Cobalt" not in item.text for item in parrot_hits)
    nick_hits = retrieve_relevant_memories(store, "What is my childhood nickname?")
    assert f"fact:{forgotten}" not in [item.item_id for item in nick_hits]
    assert all("Skip" not in item.text for item in nick_hits)

    # Many weak keyword hits still respect the count and character caps.
    hazel_texts = (
        "The user photographed a hazelwood trail marker in 2019.",
        "The user named a stuffed quokka Hazelwood.",
        "The user read a paper on hazelwood pollen counts.",
        "The user painted a hazelwood sign for the garden.",
        "The user booked a cabin near Hazelwood Falls.",
        "The user planted three hazelwood trees out back.",
        "The user keeps a hazelwood walking stick by the door.",
        "The user filed a hazelwood sketch in a blue folder.",
    )
    hazel_ids = [_add_fact(store, text) for text in hazel_texts]
    crowded = retrieve_relevant_memories(store, "What hazelwood things have I mentioned?")
    assert len(crowded) == MAX_ITEMS
    crowded_ids = {item.item_id for item in crowded}
    assert crowded_ids <= {f"fact:{item_id}" for item_id in hazel_ids}
    assert len(hazel_ids) == len(set(hazel_ids)) == 8
    crowded_block = format_retrieval_block(crowded)
    assert len(crowded_block) <= MAX_PROMPT_CHARS
    assert crowded_block.count("\n- ") <= MAX_ITEMS

    # Embeddings let a paraphrase beat an unrelated keyword-less row.
    async def stub_embed(_model: str, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    1.0
                    if any(
                        word in lowered
                        for word in ("coffee", "ethiopian", "pour-over", "drink", "morning")
                    )
                    else 0.0,
                    1.0 if any(word in lowered for word in ("dog", "maple")) else 0.0,
                    0.05,
                ]
            )
        return vectors

    class _Tools:
        def get(self, name: str):
            if name != "recall":
                return None
            return SimpleNamespace(
                _embed=stub_embed,
                _embed_available=_available,
                _embed_model="nomic-embed-text",
            )

    async def _available() -> bool:
        return True

    paraphrase = await memories_prompt_for_turn(
        _loop(store, tools=_Tools()),
        "What do I usually have to drink in the morning?",
    )
    assert "Ethiopian pour-over" in paraphrase
    assert "Maple" not in paraphrase

    # The unranked dump must no longer land in the cached prefix.
    monkeypatch.setattr(
        "arelis.core.prompt_sections.standing_profile_prompt_line",
        lambda **_: "",
    )
    monkeypatch.setattr("arelis.core.prompt_sections.contacts_prompt_line", lambda: "")
    monkeypatch.setattr(
        "arelis.core.prompt_sections.episodes_prompt_line",
        lambda *_a, **_k: "",
    )
    prefix: list[dict[str, str]] = []
    append_stable_operating_context(prefix, loop, active_room=None)
    prefix_text = "\n".join(message["content"] for message in prefix)
    assert "Ethiopian pour-over" not in prefix_text
    assert "Maple" not in prefix_text
    assert "Relevant memories for this turn" not in prefix_text

    # A preference and a decision surface when the ask points at them.
    style = await memories_prompt_for_turn(loop, "Should replies be short or long?")
    assert "short spoken answers" in style
    assert "neighborhood loop" not in style
    assert "Maple" not in style
    sentinel = await memories_prompt_for_turn(
        loop, "Did we decide where to ship Sentinel first?"
    )
    assert "Ship Sentinel on Windows first" in sentinel
    assert "Maple" not in sentinel
    assert "31 percent" not in sentinel

    overflow = format_retrieval_block(
        [
            MemoryItem(
                item_id=f"fact:{index}",
                kind="fact",
                text=("The user wrote a long spare fact about notebooks " * 8).strip(),
                updated_at="2026-11-10T00:00:00+00:00",
            )
            for index in range(12)
        ]
    )
    assert overflow
    assert len(overflow) <= MAX_PROMPT_CHARS
    assert overflow.count("\n- ") <= MAX_ITEMS

    store.close()


@pytest.mark.asyncio
async def test_hanging_embed_falls_back_to_keyword_without_stalling_the_turn(
    tmp_path,
) -> None:
    """A hung CPU embedder must not inherit the 300s chat HTTP timeout."""
    store = MemoryStore(tmp_path / "memory.db")
    _add_fact(store, "The user's usual coffee is an Ethiopian pour-over.")

    started = asyncio.Event()

    async def hanging_embed(_model: str, texts: list[str]) -> list[list[float]]:
        started.set()
        await asyncio.sleep(300)
        return [[0.0] for _ in texts]

    async def available() -> bool:
        return True

    class _Tools:
        def get(self, name: str):
            if name != "recall":
                return None
            return SimpleNamespace(
                _embed=hanging_embed,
                _embed_available=available,
                _embed_model="nomic-embed-text",
            )

    started_at = time.perf_counter()
    block = await asyncio.wait_for(
        memories_prompt_for_turn(
            _loop(store, tools=_Tools()),
            "What coffee do I usually drink?",
        ),
        timeout=10,
    )
    elapsed = time.perf_counter() - started_at
    assert started.is_set()
    assert "Ethiopian pour-over" in block
    # Well under the 300s chat HTTP timeout that a bare embed() would inherit.
    assert elapsed < 10
    store.close()


def test_compound_ask_keeps_a_second_relevant_fact_once(tmp_path) -> None:
    """Each part of a two-part ask can bring its fact; duplicates take one slot."""
    store = MemoryStore(tmp_path / "memory.db")
    saturn = _add_fact(store, "Saturn exposures are 30 seconds tonight.")
    finder_ids = {
        _add_fact(store, text)
        for text in (
            "My finder scope is a 9x50 right angle finder.",
            "Our finder scope is a 9x50 right-angle finder.",
            "Finder scope: 9x50 right angle finder.",
        )
    }
    assert len(finder_ids) == 3
    sister = _add_fact(store, "My sister's finder scope is a 9x50 right angle finder.")
    noise = [
        _add_fact(store, text)
        for text in (
            "The user has a long commute.",
            "I have two cats.",
            "The user's favorite tools are Japanese saws.",
        )
    ]

    picked = retrieve_relevant_memories(
        store,
        "Quick one, no tools please: how long are my Saturn exposures tonight, "
        "and what finder do I have?",
    )
    picked_ids = [item.item_id for item in picked]
    assert f"fact:{saturn}" in picked_ids
    assert len([i for i in picked_ids if int(i.split(":")[1]) in finder_ids]) == 1
    # Someone else's matching thing is a different fact, not a duplicate.
    assert f"fact:{sister}" in picked_ids
    for noise_id in noise:
        assert f"fact:{noise_id}" not in picked_ids
    store.close()
