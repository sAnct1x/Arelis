"""Mail/SMS/calendar stay dark until connected — chat says so, no dummy tool."""

from __future__ import annotations

from arelis.calendar.secrets import calendar_connected
from arelis.core.agent_loop import disconnected_integration_reply


def test_disconnected_reply_for_sms_when_not_paired() -> None:
    text = disconnected_integration_reply(
        expected={"send_sms"},
        available={"calculator"},
        want_sms=True,
    )
    assert text is not None
    assert "Settings → Notify" in text
    assert "scan the QR" in text


def test_disconnected_reply_for_mail_when_no_account() -> None:
    text = disconnected_integration_reply(
        expected={"send_email"},
        available={"calculator"},
        want_mail=True,
    )
    assert text is not None
    assert "Settings → Mail" in text


def test_disconnected_reply_for_calendar_when_not_authorized() -> None:
    text = disconnected_integration_reply(
        expected={"agenda"},
        available={"calculator"},
        want_calendar=True,
    )
    assert text is not None
    assert "Settings" in text
    assert "calendar" in text.lower()


def test_disconnected_reply_stays_quiet_when_the_tool_exists() -> None:
    assert (
        disconnected_integration_reply(
            expected={"send_sms"},
            available={"send_sms"},
            want_sms=True,
        )
        is None
    )
    assert (
        disconnected_integration_reply(
            expected={"send_email"},
            available={"send_email", "inbox"},
            want_mail=True,
        )
        is None
    )
    assert (
        disconnected_integration_reply(
            expected={"agenda"},
            available={"agenda"},
            want_calendar=True,
        )
        is None
    )


def test_disconnected_reply_does_not_steal_a_mixed_turn() -> None:
    assert (
        disconnected_integration_reply(
            expected={"send_sms", "web_search"},
            available={"web_search"},
            want_sms=True,
        )
        is None
    )


def test_calendar_connected_needs_oauth_or_ics(tmp_path) -> None:
    blank = tmp_path / "blank.yaml"
    blank.write_text("calendar:\n  google:\n    client_id: x\n", encoding="utf-8")
    assert calendar_connected(blank) is False

    ics = tmp_path / "ics.yaml"
    ics.write_text(
        "calendar:\n  ics_url: https://cal.example/private.ics\n",
        encoding="utf-8",
    )
    assert calendar_connected(ics) is True

    oauth = tmp_path / "oauth.yaml"
    oauth.write_text(
        "calendar:\n  google:\n    client_id: id\n    client_secret: secret\n"
        "    refresh_token: rt\n",
        encoding="utf-8",
    )
    assert calendar_connected(oauth) is True
