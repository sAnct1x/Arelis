"""Long-chat compaction keeps exact values and marks the cut.

The model fold used to ask only for durable identity facts, so numbers,
equations and decisions could vanish from the working set. Hydrate also
sliced a long reopen in half with no summary. These tests fail if either
path drops the verbatim block, or if the transcript marker is missing
or in the wrong place.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.compaction import (
    COMPACTION_MARKER,
    COMPACTION_MARKER_NOTE,
    MAX_COMPACTION_PIN_CHARS,
    MAX_VERBATIM_ITEMS,
    extract_verbatim,
    is_compaction_marker,
    merge_compaction_pin,
)
from arelis.core.context import message_tokens
from arelis.core.memory import SessionMemory
from arelis.memory import MemoryStore
from arelis.tools.base import ToolRegistry

_VERBATIM_ASK = (
    "the mass is 5 kg and E = mc^2. We decided to use Runge-Kutta. "
    "See `integrate.py`."
)
_VERBATIM_REPLY = (
    r"weekly run distance is 10 kilometers. The period is $2\pi\sqrt{L/g}$. "
    "meeting on 2026-01-01."
)
_VALUES = (
    "5 kg",
    "E = mc^2",
    "We decided to use Runge-Kutta",
    "integrate.py",
    "10 kilometers",
    r"$2\pi\sqrt{L/g}$",
    "2026-01-01",
)


def _loop(memory: SessionMemory, router: Any, agent: dict[str, Any]) -> AgentLoop:
    return AgentLoop(
        EventBus(),
        router,
        ToolRegistry(),
        memory,
        "PERSONA",
        {"agent": agent, "llamacpp": {"default_cap": 65536}},
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )


def _seed(memory: SessionMemory, *, fillers: int = 12) -> None:
    memory.add("user", _VERBATIM_ASK)
    memory.add("assistant", _VERBATIM_REPLY)
    for index in range(fillers):
        memory.add("user", f"question {index} about the weather")
        memory.add("assistant", f"answer {index}")


def _assert_values(blob: str) -> None:
    for value in _VALUES:
        assert value in blob, value


class _OmitProvider:
    async def stream_chat(self, model, messages, **kwargs):
        del model, messages, kwargs
        yield (
            "token",
            "SUMMARY: They talked about the experiment.\nFACTS:\n- NONE",
        )


class _OmitRouter:
    def __init__(self) -> None:
        self.provider = _OmitProvider()
        self.active_model = "probe-model"
        self.default_keep_alive = "30m"

    def model_for(self, role: str | None = None) -> str:
        del role
        return self.active_model

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        raise AssertionError("compaction tests must use provider.stream_chat")


class _TimeoutProvider:
    async def stream_chat(self, model, messages, **kwargs):
        del model, messages, kwargs
        await asyncio.sleep(30)
        yield ("token", "SUMMARY: late\nFACTS:\n- NONE")


class _TimeoutRouter(_OmitRouter):
    def __init__(self) -> None:
        self.provider = _TimeoutProvider()
        self.active_model = "probe-model"
        self.default_keep_alive = "30m"


class _QuietRouter:
    def model_for(self, role: str | None = None) -> str:
        del role
        return "probe-model"

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        raise AssertionError("slash compaction must not call the model")


def _agent(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "history_max_messages": 8,
        "history_min_recent": 2,
        "summarize_max_ms": 8000,
        "summarize_skip_slash": True,
    }
    cfg.update(overrides)
    return cfg


@pytest.mark.asyncio
async def test_compaction_pin_keeps_verbatim_on_every_path(tmp_path: Path) -> None:
    """Numbers, equations and decisions survive fold, timeout, slash, and hydrate."""
    excerpt = f"user: {_VERBATIM_ASK}\nassistant: {_VERBATIM_REPLY}"
    items = extract_verbatim(excerpt)
    _assert_values("\n".join(items))
    assert "0 about" not in items
    assert extract_verbatim("user: question 0 about the weather") == []

    huge = [f"{index} kg" for index in range(80)]
    pin = merge_compaction_pin("They talked about masses for a long time. " * 20, huge)
    assert len(pin) <= MAX_COMPACTION_PIN_CHARS
    # A value that made it in is complete, never "12 k" cut out of "12 kg".
    for line in pin.splitlines():
        if line.startswith("- ") and line[2:].split()[0].rstrip("kg").isdigit():
            assert line.endswith(" kg"), line

    async def _live(router: Any, *, user_text: str, **overrides: Any) -> SessionMemory:
        store = MemoryStore(tmp_path / f"{type(router).__name__}.db")
        store.start_session()
        memory = SessionMemory(max_messages=10_000, sink=store)
        _seed(memory)
        loop = _loop(memory, router, _agent(**overrides))
        messages = await loop._messages_for_turn(
            [{"role": "system", "content": "PERSONA"}],
            1_000_000,
            4.0,
            "fast",
            user_text=user_text,
        )
        blob = f"{memory.summary}\n{json.dumps(messages)}"
        _assert_values(blob)
        archive = store.get_messages(store.session_id or "")
        assert any(_VERBATIM_ASK in str(row.get("content") or "") for row in archive)
        assert any(_VERBATIM_REPLY in str(row.get("content") or "") for row in archive)
        store.close()
        return memory

    failures: list[str] = []

    async def _path(name: str, coro) -> Any:
        try:
            return await coro
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
            return None

    omitted = await _path(
        "model-omit", _live(_OmitRouter(), user_text="what about the mass")
    )
    if omitted is not None:
        try:
            assert "They talked about the experiment." in omitted.summary
        except AssertionError as exc:
            failures.append(f"model-omit narrative: {exc}")

    timed_out = await _path(
        "timeout",
        _live(
            _TimeoutRouter(),
            user_text="what about the mass",
            summarize_max_ms=200,
        ),
    )
    if timed_out is not None:
        try:
            assert "They talked about the experiment." not in timed_out.summary
            assert "late" not in timed_out.summary
        except AssertionError as exc:
            failures.append(f"timeout narrative: {exc}")

    await _path("slash", _live(_QuietRouter(), user_text="/continue"))

    try:
        store = MemoryStore(tmp_path / "hydrate.db")
        store.start_session()
        writer = SessionMemory(max_messages=10_000, sink=store)
        _seed(writer, fillers=20)
        sid = store.session_id or ""
        archive_before = store.get_messages(sid)
        original_count = len(archive_before)
        restored = SessionMemory(max_messages=8)
        restored.hydrate(archive_before, summary=store.get_summary(sid))
        _assert_values(restored.summary)
        assert len(restored.messages) <= 8
        prompt = json.dumps(restored.as_chat())
        # Dropped turns are not still sitting in the raw working set.
        assert _VERBATIM_ASK not in prompt
        archive_after = store.get_messages(sid)
        assert any(_VERBATIM_ASK in str(row.get("content") or "") for row in archive_after)
        # Originals stay; a marker may have been added.
        assert len(archive_after) >= original_count
        store.close()
    except AssertionError as exc:
        failures.append(f"hydrate: {exc}")

    assert not failures, "; ".join(failures)


def test_compaction_marker_lands_at_the_cut(tmp_path: Path, qt_app) -> None:
    """The transcript shows the notice between folded turns and recent ones."""
    from arelis.ui.panels.chat import ChatPanel

    store = MemoryStore(tmp_path / "marker.db")
    sid = store.start_session()
    writer = SessionMemory(max_messages=10_000, sink=store)
    _seed(writer, fillers=20)
    rows = store.get_messages(sid)
    restored = SessionMemory(max_messages=8, sink=store)
    restored.hydrate(rows, summary=store.get_summary(sid))
    painted = store.get_messages(sid)

    markers = [
        index
        for index, row in enumerate(painted)
        if is_compaction_marker(
            str(row.get("role") or ""),
            str(row.get("content") or ""),
            str(row.get("note") or ""),
        )
    ]
    assert len(markers) == 1
    cut = markers[0]
    assert painted[cut]["content"] == COMPACTION_MARKER
    assert painted[cut]["note"] == COMPACTION_MARKER_NOTE
    before = "\n".join(str(row.get("content") or "") for row in painted[:cut])
    after = "\n".join(str(row.get("content") or "") for row in painted[cut + 1 :])
    assert _VERBATIM_ASK in before
    assert "5 kg" in before
    assert _VERBATIM_ASK not in after
    # Kept recent fillers sit below the marker.
    assert "question 19 about the weather" in after

    prompt = json.dumps(restored.as_chat())
    assert COMPACTION_MARKER not in prompt

    panel = ChatPanel()
    panel.load_messages(
        [
            {
                "role": str(row.get("role") or ""),
                "content": str(row.get("content") or ""),
                "note": str(row.get("note") or ""),
            }
            for row in painted
        ]
    )
    text = panel.view.toPlainText()
    assert COMPACTION_MARKER in text
    assert "5 kg" in text
    assert text.index(COMPACTION_MARKER) > text.index("5 kg")
    assert text.index(COMPACTION_MARKER) < text.index("question 19 about the weather")

    # A second hydrate of the same cut must not add another marker.
    again = SessionMemory(max_messages=8, sink=store)
    again.hydrate(store.get_messages(sid), summary=store.get_summary(sid))
    second = [
        row
        for row in store.get_messages(sid)
        if is_compaction_marker(
            str(row.get("role") or ""),
            str(row.get("content") or ""),
            str(row.get("note") or ""),
        )
    ]
    assert len(second) == 1
    store.close()


@pytest.mark.parametrize(
    ("text", "expected", "forbidden"),
    [
        ("The fence is 12-15 km long.", "12-15 km", ("-15 km",)),
        ("The sample masses 10-12 kg.", "10-12 kg", ("-12 kg",)),
        ("Expect 12–15 km of cable.", "12–15 km", ("-15 km", "15 km")),
        ("The window is 12 to 15 km.", "12 to 15 km", ("15 km",)),
        ("Budget is $12-15k.", "$12-15k", ("$12", "-15k")),
        ("Error is 12-15%.", "12-15%", ("-15%",)),
        ("Wavelength is 400-700 nm.", "400-700 nm", ("-700 nm",)),
        ("The span is 12—15 km.", "12—15 km", ("-15 km", "15 km")),
        ("T = -15 C", "-15 C", ("15 C",)),
        ("The energy is -3.2 eV", "-3.2 eV", ()),
    ],
)
def test_extract_verbatim_keeps_ranges_and_true_negatives(
    text: str, expected: str, forbidden: tuple[str, ...]
) -> None:
    """A range stays one item; a true negative keeps its sign."""
    items = extract_verbatim(text)
    assert any(expected == item or expected in item for item in items), items
    for bad in forbidden:
        assert bad not in items, items


def test_extract_verbatim_keeps_a_decision_when_quantities_fill_the_cap() -> None:
    """Thirty earlier masses must not crowd the Sentinel decision off the list."""
    masses = " ".join(f"the mass of sample {index} is {index} kg." for index in range(30))
    decision = "We decided to ship Sentinel on Windows first."
    items = extract_verbatim(masses + " " + decision)
    assert len(items) <= MAX_VERBATIM_ITEMS
    assert any("ship Sentinel on Windows first" in item for item in items), items


@pytest.mark.asyncio
async def test_speak_fold_reserves_room_for_the_pin() -> None:
    """A speak-mode fold packed near the budget must still fit the pin."""
    memory = SessionMemory(max_messages=10_000)
    clause = "with extra safeguards for the Windows installer and the lab notebook "
    memory.add("user", "Noted. We decided to ship Sentinel on Windows first.")
    memory.add("assistant", "understood")
    for index in range(16):
        memory.add(
            "user",
            f"Noted. We decided to use procedure P{index:02d} " + clause * 3 + ".",
        )
        memory.add("assistant", f"logged P{index:02d}")
    body = ("note " * 20).strip()
    for index in range(40):
        memory.add("user", f"q{index} {body}")
        memory.add("assistant", f"a{index} {body}")

    loop = _loop(
        memory,
        _QuietRouter(),
        _agent(history_max_messages=10_000, history_min_recent=2),
    )
    loop.config["_speak_replies"] = True
    ratio = 2.0
    budget = 900
    messages = await loop._messages_for_turn(
        [{"role": "system", "content": "PERSONA"}],
        budget,
        ratio,
        "fast",
        user_text="what about the mass",
    )
    total = sum(message_tokens(row, chars_per_token=ratio) for row in messages)
    pin = "\n".join(
        str(row.get("content") or "")
        for row in messages
        if "earlier in this conversation" in str(row.get("content") or "")
    )
    # The first pass keeps about half the budget; this pin is larger than
    # the leftover room, so skipping the reserve would overflow 900.
    pin_tokens = message_tokens({"role": "system", "content": pin}, chars_per_token=ratio)
    assert pin, "speak fold must inject a pin"
    assert pin_tokens > 400, pin_tokens
    assert total <= budget, f"prompt {total} exceeded budget {budget}"
    assert "Sentinel" in (memory.summary or "")
