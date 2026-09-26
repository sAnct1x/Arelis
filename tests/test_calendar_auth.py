"""In-app calendar sign-in. No terminal command for a dead token."""

from __future__ import annotations

from arelis.calendar.auth import (
    AuthResult,
    authorize_calendar,
    is_reauth_error,
    run_auth_calendar,
)


def test_token_refresh_is_a_reauth() -> None:
    assert is_reauth_error(
        "google: Google token refresh failed (400). Sign in on the calendar tile."
    )
    assert is_reauth_error("Google Calendar not authorized. Sign in on the calendar tile.")
    assert not is_reauth_error("sync timed out")


def test_authorize_without_secrets_does_not_open_a_browser(tmp_path, monkeypatch) -> None:
    blank = tmp_path / "secrets.yaml"
    blank.write_text("calendar: {}\n", encoding="utf-8")
    monkeypatch.setattr("arelis.calendar.auth.load_calendar_secrets", lambda: __import__(
        "arelis.calendar.secrets", fromlist=["CalendarSecrets"]
    ).CalendarSecrets(google=None, outlook=None))
    result = authorize_calendar("google")
    assert isinstance(result, AuthResult)
    assert result.ok is False
    assert result.provider == "google"
    assert "not set up" in result.error


def test_unknown_provider() -> None:
    result = authorize_calendar("yahoo")
    assert result.ok is False
    assert run_auth_calendar("yahoo") == 2


def test_sign_in_button_is_on_the_tile(qt_app) -> None:
    from arelis.ui.panels.calendar import CalendarPanel

    panel = CalendarPanel()
    try:
        assert panel.sign_in_btn.text() == "sign in"
        panel.set_sign_in_busy(True)
        assert panel.sign_in_btn.text() == "signing in…"
        assert not panel.sign_in_btn.isEnabled()
        panel.set_sign_in_busy(False)
        assert panel.sign_in_btn.text() == "sign in"
        assert panel.sign_in_btn.isEnabled()
    finally:
        panel.deleteLater()
