"""History dock: load past sessions over the bus, never mid-turn."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.memory import MemoryStore
from arelis.tools.base import ToolRegistry


def _config() -> dict:
    return {
        "agent": {},
        "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
        "workspace": {"roots": ["."]},
    }


class _StubRouter:
    default_role = "fast"
    active_model = None
    models = {"fast": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        if False:
            yield ("token", "")
        return

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_session_load_hydrates_memory_from_the_archive(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    sid = store.start_session()
    seed = SessionMemory(sink=store)
    seed.add("user", "Remember the interferometer baseline.")
    seed.add("assistant", "Baseline noted.")

    bus = EventBus()
    loaded: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.SESSION_LOADED:
            loaded.append(event)

    bus.subscribe(EventType.SESSION_LOADED, capture)
    memory = SessionMemory(sink=store)
    Orchestrator(bus, _StubRouter(), ToolRegistry(), _config(), memory)  # type: ignore[arg-type]

    task = asyncio.create_task(bus.run())
    await bus.publish(Event(EventType.SESSION_LOAD, {"session_id": sid}))
    await bus.drain()
    bus.stop()
    task.cancel()

    assert loaded and loaded[0].payload["ok"] is True
    assert memory.as_ollama()[0]["content"] == "Remember the interferometer baseline."
    assert "Baseline noted." in memory.as_ollama()[1]["content"]
    store.close()


@pytest.mark.asyncio
async def test_chat_notice_is_archived_without_starting_a_turn(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    bus = EventBus()
    memory = SessionMemory(sink=store)
    Orchestrator(bus, _StubRouter(), ToolRegistry(), _config(), memory)  # type: ignore[arg-type]
    task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(
                EventType.CHAT_NOTICE,
                {"text": "Text from Robin Hale: Bro that man is SSG"},
            )
        )
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
    rows = store.get_messages(store.session_id or "")
    assert len(rows) == 1
    assert rows[0]["role"] == "notice"
    assert "Bro that man is SSG" in rows[0]["content"]
    assert memory.as_ollama() == []
    store.close()


@pytest.mark.asyncio
async def test_session_load_is_refused_while_a_turn_is_running(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    sid = store.start_session()
    bus = EventBus()
    loaded: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.SESSION_LOADED:
            loaded.append(event)

    bus.subscribe(EventType.SESSION_LOADED, capture)
    memory = SessionMemory(sink=store)
    orch = Orchestrator(bus, _StubRouter(), ToolRegistry(), _config(), memory)  # type: ignore[arg-type]

    async def _hang() -> None:
        await asyncio.Event().wait()

    orch._turn_task = asyncio.create_task(_hang())
    task = asyncio.create_task(bus.run())
    await bus.publish(Event(EventType.SESSION_LOAD, {"session_id": sid}))
    await bus.drain()
    bus.stop()
    task.cancel()
    orch._turn_task.cancel()

    assert loaded and loaded[0].payload["ok"] is False
    assert "turn" in str(loaded[0].payload.get("error") or "").lower()
    store.close()


def test_chat_clear_and_load_messages_reset_stream_state(qt_app) -> None:
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.begin_assistant()
    panel.append_delta("draft")
    panel.clear()
    assert not panel._stream_open
    assert panel._anchor is None
    assert panel._stream_text == []
    assert panel._last_assistant_body is None
    assert not panel._has_messages
    assert not panel.empty.isHidden()
    assert panel.view.isHidden()

    panel.load_messages(
        [
            {"role": "user", "content": "hello from march"},
            {"role": "notice", "content": "Text from Robin: it's a test"},
            {"role": "assistant", "content": "hello back"},
        ]
    )
    text = panel.view.toPlainText()
    assert "hello from march" in text
    assert "Text from Robin: it's a test" in text
    assert "hello back" in text
    assert panel._has_messages


def test_switching_sessions_mid_turn_is_refused_in_the_window(qt_app, tmp_path: Path) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    window = ArelisWindow(
        {"ui": {}, "router": {"default_role": "fast"}, "voice": {"enabled": False}},
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
        store=store,
    )
    try:
        window._turn_busy = True
        window._on_history_selected("abc123")
        assert "Finish or stop the current turn" in window.chat.view.toPlainText()
        # Debounce: second click must not double the amber toast (L3 / S10).
        before = window.chat.view.toPlainText().count("Finish or stop")
        window._on_history_selected("abc123")
        after = window.chat.view.toPlainText().count("Finish or stop")
        assert after == before
    finally:
        window.hide()
        window.loop.close()
        store.close()


def test_history_disables_switch_while_busy(qt_app) -> None:
    from arelis.ui.panels.history import HistoryPanel

    panel = HistoryPanel()
    assert panel.list.isEnabled()
    panel.set_switch_enabled(False)
    assert not panel.list.isEnabled()
    assert not panel.new_btn.isEnabled()
    panel.set_switch_enabled(True)
    assert panel.list.isEnabled()
    panel.deleteLater()
