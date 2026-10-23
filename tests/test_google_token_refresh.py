"""Dead Google refresh tokens must be forgotten, not retried."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

from arelis.calendar.auth import AuthResult
from arelis.calendar.google_client import GoogleCalendarClient
from arelis.calendar.secrets import GoogleCalendarCreds, load_calendar_secrets
from arelis.ui.calendar_host import (
    bind_calendar,
    kick_calendar_auth,
    kick_calendar_sync,
    run_calendar,
)
from arelis.ui.host_bind import bind_window_hosts
from arelis.ui.idle_host import wake_from_away_rest
from arelis.ui.window_docks import toggle_calendar

REFRESH_FAIL = (
    "Google token refresh failed (400). Sign in on the calendar tile."
)


def _write_google_secrets(path: Path, *, token: str = "dummy_refresh_token") -> None:
    block = (
        "calendar:\n"
        "  google:\n"
        "    client_id: dummy-client-id\n"
        "    client_secret: dummy-client-secret\n"
    )
    if token:
        block += f"    refresh_token: {token}\n"
    path.write_text(block, encoding="utf-8")


def _creds() -> GoogleCalendarCreds:
    return GoogleCalendarCreds(
        client_id="dummy-client-id",
        client_secret="dummy-client-secret",
        refresh_token="dummy_refresh_token",
    )


def _close_coro(coro: object) -> None:
    close = getattr(coro, "close", None)
    if close is not None:
        close()


class _ImmediateFut:
    def __init__(
        self, *, result: object = None, error: BaseException | None = None
    ) -> None:
        self._result = result
        self._error = error

    def result(self) -> object:
        if self._error is not None:
            raise self._error
        return self._result

    def add_done_callback(self, cb: Any) -> None:
        cb(self)


def _fake_window() -> SimpleNamespace:
    panel = SimpleNamespace(
        reload=lambda: None,
        set_status=lambda *_a, **_k: None,
        set_sign_in_busy=lambda busy: None,
    )
    return SimpleNamespace(
        _force_quit=False,
        _disposed=False,
        _calendar_auth_offered=False,
        _calendar_sync_inflight=False,
        _calendar_auth_inflight=False,
        _calendar_sync_timeout_ms=1000,
        _calendar_sync_watchdog=SimpleNamespace(
            start=lambda _ms: None, stop=lambda: None
        ),
        config={},
        loop=SimpleNamespace(is_running=lambda: True),
        _ui_call=SimpleNamespace(emit=lambda fn: fn()),
        calendar=panel,
        calendar_window=SimpleNamespace(isHidden=lambda: False),
    )


@pytest.mark.asyncio
async def test_invalid_grant_clears_refresh_token_and_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = tmp_path / "secrets.yaml"
    _write_google_secrets(secrets)
    monkeypatch.setattr("arelis.calendar.secrets.SECRETS_PATH", secrets)
    monkeypatch.setattr("arelis.ui.notify_host.report_poll_state", lambda *_a, **_k: None)
    monkeypatch.setattr("arelis.ui.dialog.notice", lambda *_a, **_k: None)

    posts: list[str] = []
    replies: list[httpx.Response] = [
        httpx.Response(500, json={"error": "server_error"}),
        httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(str(request.url))
        if not replies:
            raise AssertionError("Google token endpoint was posted again")
        return replies.pop(0)

    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    keep = GoogleCalendarClient(_creds())
    with pytest.raises(RuntimeError, match="token refresh failed"):
        await keep.access_token()
    assert posts == ["https://oauth2.googleapis.com/token"]
    after_500 = load_calendar_secrets(secrets)
    assert after_500.google is not None
    assert after_500.google.refresh_token == "dummy_refresh_token"
    assert after_500.google.authorized is True

    dead = GoogleCalendarClient(_creds())
    with pytest.raises(RuntimeError, match="token refresh failed"):
        await dead.access_token()
    assert posts == [
        "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/token",
    ]
    loaded = load_calendar_secrets(secrets)
    assert loaded.google is not None
    assert loaded.google.refresh_token == ""
    assert loaded.google.authorized is False
    stored = yaml.safe_load(secrets.read_text(encoding="utf-8"))
    google = stored["calendar"]["google"]
    assert "refresh_token" not in google

    with pytest.raises(RuntimeError, match="not authorized"):
        await dead.access_token()
    assert posts == [
        "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/token",
    ]

    bind_src = inspect.getsource(bind_calendar)
    assert "timeout.connect(lambda: kick_calendar_sync(window))" in bind_src
    assert "kick_calendar_sync(window, user=True)" in bind_src
    host_src = inspect.getsource(bind_window_hosts)
    assert "timeout.connect(lambda: kick_calendar_sync(window))" in host_src
    assert "kick_calendar_sync(window, user=True)" in host_src
    idle_src = inspect.getsource(wake_from_away_rest)
    assert "kick_calendar_sync(window)" in idle_src
    assert "kick_calendar_sync(window, user=True)" not in idle_src
    dock_src = inspect.getsource(toggle_calendar)
    assert "kick_calendar_sync(window)" in dock_src
    assert "kick_calendar_sync(window, user=True)" not in dock_src

    auth_calls: list[str] = []
    monkeypatch.setattr(
        "arelis.ui.calendar_host.kick_calendar_auth",
        lambda window, provider="": auth_calls.append(provider or "google"),
    )
    pending: list[_ImmediateFut] = []

    def fake_threadsafe(coro: object, loop: object) -> _ImmediateFut:
        _close_coro(coro)
        return pending.pop(0)

    monkeypatch.setattr(
        "arelis.ui.calendar_host.asyncio.run_coroutine_threadsafe",
        fake_threadsafe,
    )

    window = _fake_window()
    _write_google_secrets(secrets)

    pending.append(_ImmediateFut(error=RuntimeError(REFRESH_FAIL)))
    kick_calendar_sync(window)
    assert auth_calls == []
    pending.append(_ImmediateFut(error=RuntimeError(REFRESH_FAIL)))
    kick_calendar_sync(window, user=True)
    assert auth_calls == ["google"]

    auth_calls.clear()
    pending.append(
        _ImmediateFut(result={"ok": False, "errors": [REFRESH_FAIL]})
    )
    kick_calendar_sync(window)
    assert auth_calls == []
    pending.append(
        _ImmediateFut(result={"ok": False, "errors": [REFRESH_FAIL]})
    )
    kick_calendar_sync(window, user=True)
    assert auth_calls == ["google"]

    _write_google_secrets(secrets, token="")
    auth_calls.clear()
    window._calendar_auth_offered = False
    kick_calendar_sync(window)
    assert auth_calls == []
    kick_calendar_sync(window, user=True)
    assert auth_calls == ["google"]
    assert window._calendar_auth_offered is True

    monkeypatch.setattr(
        "arelis.ui.calendar_host.kick_calendar_auth", kick_calendar_auth
    )
    window._calendar_auth_offered = True
    window._calendar_auth_inflight = False
    pending.append(
        _ImmediateFut(
            result=AuthResult(ok=False, provider="google", error="closed")
        )
    )
    kick_calendar_auth(window)
    assert window._calendar_auth_offered is True

    auth_calls.clear()
    monkeypatch.setattr(
        "arelis.ui.calendar_host.kick_calendar_auth",
        lambda w, provider="": auth_calls.append(provider or "google"),
    )
    kick_calendar_sync(window)
    assert auth_calls == []

    async def _unused() -> None:
        return None

    pending.append(_ImmediateFut(error=RuntimeError(REFRESH_FAIL)))
    run_calendar(window, _unused())
    assert auth_calls == ["google"]
