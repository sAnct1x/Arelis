"""Dead Google refresh tokens must be forgotten, not retried."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from arelis.calendar.google_client import GoogleCalendarClient
from arelis.calendar.secrets import GoogleCalendarCreds, load_calendar_secrets


def _write_google_secrets(path: Path) -> None:
    path.write_text(
        "calendar:\n"
        "  google:\n"
        "    client_id: dummy-client-id\n"
        "    client_secret: dummy-client-secret\n"
        "    refresh_token: dummy_refresh_token\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_invalid_grant_clears_refresh_token_and_does_not_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = tmp_path / "secrets.yaml"
    _write_google_secrets(secrets)
    monkeypatch.setattr("arelis.calendar.secrets.SECRETS_PATH", secrets)

    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(str(request.url))
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )

    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)

    client = GoogleCalendarClient(
        GoogleCalendarCreds(
            client_id="dummy-client-id",
            client_secret="dummy-client-secret",
            refresh_token="dummy_refresh_token",
        )
    )

    with pytest.raises(RuntimeError, match="token refresh failed"):
        await client.access_token()

    assert posts == ["https://oauth2.googleapis.com/token"]
    loaded = load_calendar_secrets(secrets)
    assert loaded.google is not None
    assert loaded.google.refresh_token == ""
    assert loaded.google.authorized is False
    stored = yaml.safe_load(secrets.read_text(encoding="utf-8"))
    google = stored["calendar"]["google"]
    assert "refresh_token" not in google

    with pytest.raises(RuntimeError, match="not authorized"):
        await client.access_token()
    assert posts == ["https://oauth2.googleapis.com/token"]
