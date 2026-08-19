"""Calm first paint, fonts, and listen-pulse affordances."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.ui.icons import conversation_icon, microphone_icon
from arelis.ui.theme import load_fonts


def test_reset_layout_is_conversation_only(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window.think_dock.show()
        window.work_dock.show()
        window.history_dock.show()
        window.contacts_inbox.show()
        window._reset_layout()
        # isVisible() stays false while the window itself is hidden; isHidden()
        # is the dock's own show/hide latch.
        assert window.think_dock.isHidden()
        assert window.work_dock.isHidden()
        assert window.history_dock.isHidden()
        assert window.contacts_inbox.isHidden()
        assert window.notify_inbox.isHidden()
        assert not window.act_thinking.isChecked()
        assert not window.act_contacts.isChecked()
    finally:
        window.hide()
        window.loop.close()


def test_away_rest_collapses_then_click_restores(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        window.history_dock.show()
        window.think_dock.show()
        window._away_rest = True
        window._enter_away_rest()
        assert window._away_resting
        assert window.history_dock.isHidden()
        assert window.think_dock.isHidden()
        window._note_engagement()
        assert not window._away_resting
        assert not window.history_dock.isHidden()
        assert not window.think_dock.isHidden()
        window._enter_away_rest()
        window._on_event(Event(EventType.THINKING, {"text": "boot noise"}))
        assert window.think_dock.isHidden()
    finally:
        window.hide()
        window.loop.close()


def test_thinking_trace_reveals_the_dock(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {
                "default_width": 800,
                "default_height": 600,
                "thinking_open": False,
                "workspace_open": False,
            },
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        assert window.think_dock.isHidden()
        window._on_event(Event(EventType.THINKING, {"text": "considering Vega"}))
        assert not window.think_dock.isHidden()
        assert window.act_thinking.isChecked()
    finally:
        window.hide()
        window.loop.close()


def test_load_fonts_prefers_bundled_plex_when_present(qt_app) -> None:
    font_dir = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "fonts"
    zen = font_dir / "ZenKakuGothicNew-Regular.ttf"
    bundled = [
        font_dir / "IBMPlexSans-Regular.ttf",
        font_dir / "IBMPlexSans-SemiBold.ttf",
        font_dir / "IBMPlexMono-Regular.ttf",
    ]
    families = load_fonts()
    assert "body" in families
    assert "mono" in families
    if zen.is_file():
        return
    if not all(path.is_file() for path in bundled):
        return
    assert "Plex" in families["body"]
    assert "Plex" in families["mono"]


def test_live_icons_accept_a_pulse(qt_app) -> None:
    assert not microphone_icon(22, live=True, pulse=0.6).isNull()
    assert not conversation_icon(22, live=True, pulse=1.2).isNull()


def test_role_combo_is_not_editable(qt_app) -> None:
    """Editable+readOnly LineEdit ate Windows popup clicks (U1 / S01-S10)."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage(default_role="fast")
    try:
        assert not stage.role.isEditable()
        assert stage.role.currentText() == "fast"
        stage.role.setCurrentText("research")
        assert stage.role.currentText() == "research"
    finally:
        stage.deleteLater()


def test_role_status_syncs_composer_combo(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        assert window.conversation.role.currentText() == "fast"
        window._on_event(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        "Role set to `research`. New messages use it unless you pick another chip."
                    )
                },
            )
        )
        assert window.conversation.role.currentText() == "research"
        assert window._current_role == "research"
    finally:
        window.hide()
        window.loop.close()


def test_floating_instrument_raises_fill_alpha(qt_app) -> None:
    from PySide6.QtWidgets import QLabel

    from arelis.ui.panels.instrument import (
        _DOCKED_FILL_ALPHA,
        _FLOATING_FILL_ALPHA,
        InstrumentPanel,
    )

    panel = InstrumentPanel("history", QLabel("body"))
    assert panel._fill_alpha == _DOCKED_FILL_ALPHA
    panel._on_floating_changed(True)
    assert panel._fill_alpha == _FLOATING_FILL_ALPHA
    panel._on_floating_changed(False)
    assert panel._fill_alpha == _DOCKED_FILL_ALPHA
    panel.deleteLater()


def test_inbound_sms_held_until_turn_floor_frees(qt_app, tmp_path: Path) -> None:
    from arelis.core.events import Event, EventType
    from arelis.memory import MemoryStore
    from arelis.ui.app import ArelisWindow, BusBridge

    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
        store=store,
    )
    try:
        window._set_busy(True)
        window._on_event(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "a",
                    "from": "+1555",
                    "body": "Bro that man is SSG",
                    "contact_name": "Robin Hale",
                },
            )
        )
        window._on_event(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "b",
                    "from": "+1555",
                    "body": "But his title is very very important",
                    "contact_name": "Robin Hale",
                },
            )
        )
        chat = window.chat.view.toPlainText()
        think = window.thinking.view.toPlainText()
        assert "Bro that man is SSG" not in chat
        assert "Bro that man is SSG" not in think
        head = window.notify_center.head()
        assert head is not None
        assert head.kind == "sms"
        assert head.count == 2
        assert "Robin" in head.title
        assert window.notify_center.unread_count() == 1
        window._set_busy(False)
        chat = window.chat.view.toPlainText()
        think = window.thinking.view.toPlainText()
        assert "2 texts from Robin Hale" not in chat
        assert "Bro that man is SSG" not in chat
        assert "2 texts from Robin Hale" not in think
        rows = store.get_messages(store.session_id or "")
        assert not any(r["role"] == "notice" for r in rows)
    finally:
        window.hide()
        window.loop.close()
        store.close()


def test_esc_does_not_kill_a_turn_that_has_painted_nothing(qt_app) -> None:
    """A tool round holds the answer back, so the thread is blank until the
    tools finish. The orbit says "esc to clear", and clearing a blank thread is
    how three spoken SMS turns were cancelled before their Allow card existed.
    The stop control is the thing that cancels, and it still does."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stops: list[int] = []
        declined: list[int] = []
        stage.stop_requested.connect(lambda: stops.append(1))
        stage.stop_declined.connect(lambda: declined.append(1))

        stage.set_busy(True)
        assert not stage.turn_visible()
        stage._escape()
        assert stops == [], "Esc must not cancel an invisible turn"
        assert declined == [1], "and must say why instead of doing nothing"

        # The stop control has no ladder.
        stage._stop()
        assert stops == [1]

        # Once tokens or a tool line are on screen, Esc means stop again.
        stage.set_turn_visible(True)
        stage._escape()
        assert stops == [1, 1]

        # A new turn starts invisible again.
        stage.set_busy(True)
        assert not stage.turn_visible()
    finally:
        stage.deleteLater()


def test_a_confirm_card_is_something_to_stop(qt_app) -> None:
    """Esc on an open card is deny (wire: skip), not cancel, and not silent."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        declined: list[int] = []
        decided: list[str] = []
        stage.stop_declined.connect(lambda: declined.append(1))
        stage.confirm_decided.connect(
            lambda _id, decision, _batch: decided.append(decision)
        )
        stage.set_busy(True)
        stage.ask_confirm("c1", "send_sms", "text wife: I love you.")
        stage._escape()
        assert decided == ["skip"]
        assert declined == []
    finally:
        stage.deleteLater()


def test_esc_skips_confirm_while_busy(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    decided: list[str] = []
    stage.confirm_decided.connect(lambda _id, decision, _batch: decided.append(decision))
    stage.set_busy(True)
    stage.ask_confirm("c1", "workspace", "write file")
    assert stage.confirm_open()
    assert stage.input.placeholderText().startswith("Enter = allow")
    stage._escape()
    assert decided == ["skip"]
    assert not stage.confirm_open()
    stage.deleteLater()
