"""Dead Google refresh tokens must be forgotten, not retried."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import yaml

from arelis.calendar.google_client import GoogleCalendarClient
from arelis.calendar.secrets import GoogleCalendarCreds, load_calendar_secrets
from arelis.ui.calendar_host import kick_calendar_sync


def _write_google_secrets(path: Path) -> None:
    path.write_text(
        "calendar:\n"
        "  google:\n"
        "    client_id: dummy-client-id\n"
        "    client_secret: dummy-client-secret\n"
        "    refresh_token: dummy_refresh_token\n",
        encoding="utf-8",
    )


def _creds() -> GoogleCalendarCreds:
    return GoogleCalendarCreds(
        client_id="dummy-client-id",
        client_secret="dummy-client-secret",
        refresh_token="dummy_refresh_token",
    )


def _fake_window() -> SimpleNamespace:
    panel = SimpleNamespace(
        reload=lambda: None,
        set_status=lambda *_a, **_k: None,
    )
    return SimpleNamespace(
        _force_quit=False,
        _disposed=False,
        _calendar_auth_offered=False,
        _calendar_sync_inflight=False,
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

    auth_calls: list[str] = []
    monkeypatch.setattr(
        "arelis.ui.calendar_host.kick_calendar_auth",
        lambda window, provider="": auth_calls.append(provider or "google"),
    )
    window = _fake_window()
    kick_calendar_sync(window)
    assert auth_calls == []
    kick_calendar_sync(window, user=True)
    assert auth_calls == ["google"]
