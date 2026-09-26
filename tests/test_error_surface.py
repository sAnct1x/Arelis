"""Failures belong where the user is looking, not a closed Thinking dock.

Workspace open/save and phone-notify status used to write the Thinking footer
and stop. That dock is closed unless someone asks for it. A mutant that only
calls thinking.append must fail these tests.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from arelis.core.events import Event, EventType
from arelis.notify.center import NotificationCenter, new_notice
from arelis.ui.notify_host import report_poll_state
from arelis.ui.sms_host import open_sms_chat
from arelis.ui.workspace_host import open_file, save_file
from arelis.workspace import WorkspaceRoots


def _talk_window(*, roots: WorkspaceRoots | None = None) -> SimpleNamespace:
    said: list[str] = []
    think: list[str] = []
    window = SimpleNamespace(
        chat=SimpleNamespace(add_system=said.append),
        thinking=SimpleNamespace(append=lambda text, kind="status": think.append(str(text))),
        work_dock=object(),
        act_workspace=object(),
        workspace_roots=roots,
        workspace=SimpleNamespace(
            loaded_abs=lambda: "",
            has_unsaved_changes=lambda: False,
        ),
        _reveal_dock=lambda *_a, **_k: None,
        said=said,
        think=think,
        _poll_fail_streak={},
        _poll_ok_streak={},
        _poll_state={},
        _poll_spoken={},
    )
    return window


def test_workspace_save_failure_lands_in_conversation(tmp_path: Path) -> None:
    """The visible surface, not only the closed dock footer."""
    roots = WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)
    window = _talk_window(roots=roots)

    save_file(window, str(tmp_path.parent / "outside-the-sandbox.txt"), "nope")

    assert any("could not save" in line.lower() for line in window.said), (
        "save failure must show in conversation; thinking-only is the defect"
    )
    assert any("save failed" in line for line in window.think)


def test_workspace_save_write_error_lands_in_conversation(tmp_path: Path, monkeypatch) -> None:
    roots = WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)
    window = _talk_window(roots=roots)
    (tmp_path / "notes.txt").write_text("ok", encoding="utf-8")

    def boom(self, *_a, **_k):
        raise OSError("Access is denied")

    monkeypatch.setattr(Path, "write_text", boom)
    save_file(window, "notes.txt", "edited")

    assert any("could not save" in line.lower() for line in window.said)
    assert any("save failed" in line for line in window.think)


def test_workspace_open_failure_lands_in_conversation(tmp_path: Path) -> None:
    roots = WorkspaceRoots.from_paths([str(tmp_path)], active=tmp_path.name)
    window = _talk_window(roots=roots)

    open_file(window, "ghost.txt")

    assert any(
        "could not open" in line.lower() or "not a file" in line.lower() for line in window.said
    )
    assert window.said, "open failure must not be thinking-only"


def test_notify_poll_failure_lands_in_conversation() -> None:
    window = _talk_window()
    report_poll_state(window, "sms", "Phone notifications stopped: timeout")
    assert window.said == []
    report_poll_state(window, "sms", "Phone notifications stopped: timeout")
    assert any("Phone notifications stopped" in line for line in window.said)
    assert any("Phone notifications stopped" in line for line in window.think)


def test_sms_chat_without_a_number_lands_in_conversation(qt_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui.sms_chat import SmsChatRegistry

    monkeypatch.setattr("arelis.ui.sms_chat.load_contacts", lambda: {})
    host = QWidget()
    registry = SmsChatRegistry(host)
    notice = new_notice(
        kind="sms",
        title="no-such-contact-xyz",
        body="hi",
        data={"from": "", "alias": ""},
    )
    center = NotificationCenter()
    center.add(notice)
    window = _talk_window()
    window.sms_chats = registry
    window.notify_center = center
    try:
        assert open_sms_chat(window, notice.id) is False
        assert any("No number" in line for line in window.said)
        assert any("No number" in line for line in window.think)
    finally:
        host.deleteLater()


def test_phone_notify_bind_failure_lands_in_conversation(arelis_window) -> None:
    window = arelis_window()
    said: list[str] = []
    window.chat.add_system = said.append  # type: ignore[method-assign]
    window._on_event(
        Event(
            EventType.STATUS,
            {
                "message": (
                    "Inbound notify could not bind any port from 8765 to 8774: "
                    "address already in use"
                )
            },
        )
    )
    assert any("could not bind" in line for line in said)
    assert "could not bind" in window.thinking.footer.text()


def test_phone_notify_listen_url_stays_off_the_transcript(arelis_window) -> None:
    """Setup URL must not start a conversation or hide the orbit."""
    from arelis.ui.idle_host import idle_eligible, sync_idle_mode

    window = arelis_window()
    said: list[str] = []
    window.chat.add_system = said.append  # type: ignore[method-assign]
    window._on_event(
        Event(
            EventType.STATUS,
            {"message": "Phone notifications: http://127.0.0.1:8765"},
        )
    )
    sync_idle_mode(window)
    assert said == []
    assert idle_eligible(window)
    assert window._inbound_banner.startswith("Phone notifications")
    assert "8765" in window.thinking.footer.text()
