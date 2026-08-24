"""Failures on paths the user is watching have to reach the user.

Every bug covered here was an ``except: pass`` on something a person had asked
for and was waiting on — a saved file, a notification, a picture. The counting
assertions matter as much as the presence ones: a poller that fails every thirty
seconds and says so every thirty seconds is a second way of saying nothing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from arelis.core.events import Event, EventType
from arelis.ui.app import voice_restart_notices


def _quiet_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop _on_notify_poll from starting a real IMAP thread."""
    import arelis.ui.app as app_mod

    monkeypatch.setattr(app_mod, "peek_contact_mail_sync", lambda config=None: [])


def test_write_that_cannot_be_read_back_says_so(arelis_window, tmp_path: Path) -> None:
    """The write landed and the editor did not move. Silence reads as a clobber."""
    win = arelis_window()
    win._on_event(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": "workspace",
                "ok": True,
                "output": "wrote notes.md",
                "data": {
                    "path": "notes.md",
                    "abs_path": str(tmp_path / "never-written.md"),
                    "root_name": "arelis",
                },
            },
        )
    )
    chat = win.chat.view.toPlainText()
    assert "could not read it back" in chat
    assert "notes.md" in chat
    assert "read-back failed" in win.thinking.view.toPlainText()


def test_broken_calendar_poll_speaks_once_then_on_recovery(
    arelis_window, monkeypatch: pytest.MonkeyPatch
) -> None:
    import arelis.ui.app as app_mod

    _quiet_mail(monkeypatch)
    win = arelis_window()

    def _boom(config=None):
        raise RuntimeError("calendar cache is locked")

    monkeypatch.setattr(app_mod, "load_today_events", _boom)
    win._on_notify_poll()
    win._on_notify_poll()
    win._on_notify_poll()
    text = win.thinking.view.toPlainText()
    assert text.count("Calendar notifications stopped") == 1
    assert "cache is locked" in text

    monkeypatch.setattr(app_mod, "load_today_events", lambda config=None: [])
    win._on_notify_poll()
    assert "working again" not in win.thinking.view.toPlainText()
    win._on_notify_poll()
    assert "calendar notifications are working again" in win.thinking.view.toPlainText()


def test_mail_peek_failure_reaches_the_rail(arelis_window) -> None:
    win = arelis_window()
    err = RuntimeError("Mail notifications stopped: login refused")
    win._on_mail_headers(err)
    assert "login refused" not in win.thinking.view.toPlainText()
    win._on_mail_headers(err)
    text = win.thinking.view.toPlainText()
    assert text.count("login refused") == 1
    assert not win._mail_poll_inflight


def test_mail_peek_flap_does_not_announce_recovery(arelis_window) -> None:
    win = arelis_window()
    err = RuntimeError("Mail notifications stopped: timeout")
    win._on_mail_headers(err)
    win._on_mail_headers(err)
    win._on_mail_headers([])
    assert "working again" not in win.thinking.view.toPlainText()
    win._on_mail_headers([])
    assert "mail notifications are working again" in win.thinking.view.toPlainText()


def test_mail_peek_raises_instead_of_returning_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Nobody wrote to you" and "the password is wrong" are different answers."""
    import arelis.notify.sources as sources
    import arelis.tools.inbox as inbox_mod

    monkeypatch.setattr(
        sources, "load_account", lambda: SimpleNamespace(address="me@example.com")
    )

    class _Boom:
        def __init__(self, *a: object, **k: object) -> None:
            pass

        def _run_sync(self, *a: object, **k: object):
            raise OSError("IMAP login refused")

    monkeypatch.setattr(inbox_mod, "InboxTool", _Boom)
    with pytest.raises(sources.MailPeekError) as caught:
        sources.peek_contact_mail_sync({})
    assert "IMAP login refused" in str(caught.value)


def test_unconfigured_mail_is_still_quietly_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arelis.notify.sources as sources

    monkeypatch.setattr(sources, "load_account", lambda: None)
    assert sources.peek_contact_mail_sync({}) == []


@pytest.mark.asyncio
async def test_weather_names_the_refresh_that_failed(monkeypatch) -> None:
    """"No coordinates on file" sent people to edit a profile that was fine."""
    from arelis.tools.weather import WeatherTool

    class _Snap:
        def has_coordinates(self) -> bool:
            return False

        def place(self) -> str:
            return ""

    class _Loc:
        def snapshot(self) -> _Snap:
            return _Snap()

        def refresh(self):
            raise OSError("network location provider timed out")

    result = await WeatherTool(_Loc()).run()
    assert not result.ok
    assert "network location provider timed out" in result.output
    assert "No coordinates on file" in result.output


def test_voice_toggles_that_need_a_restart_say_so() -> None:
    assert voice_restart_notices(
        listen_wanted=True,
        listen_live=True,
        speak_wanted=True,
        speak_live=True,
    ) == []
    on_again = voice_restart_notices(
        listen_wanted=True,
        listen_live=True,
        speak_wanted=True,
        speak_live=False,
    )
    assert len(on_again) == 1
    assert "Speak on" in on_again[0]
    off_again = voice_restart_notices(
        listen_wanted=False,
        listen_live=True,
        speak_wanted=False,
        speak_live=True,
    )
    assert len(off_again) == 2
    assert "Listen off" in off_again[0]
    assert "Speak off" in off_again[1]


def test_settings_warn_when_the_live_voice_service_cannot_follow(
    arelis_window,
) -> None:
    win = arelis_window()
    win.voice = SimpleNamespace(
        stt_enabled=True,
        tts_enabled=False,
        cancel_speech=lambda: None,
    )
    win._apply_settings(
        {
            "voice": {
                "enabled": True,
                "stt": {"enabled": True},
                "tts": {"enabled": True},
            }
        }
    )
    text = win.thinking.view.toPlainText()
    assert "Restart Arelis to finish turning Speak on" in text
    assert "Listen" not in text
