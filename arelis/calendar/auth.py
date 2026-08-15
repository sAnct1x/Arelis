"""One-shot browser OAuth for Google Calendar and Outlook."""

from __future__ import annotations

import logging
from typing import Any

from arelis.calendar.secrets import (
    load_calendar_secrets,
    save_refresh_token,
)

log = logging.getLogger(__name__)

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
OUTLOOK_SCOPES = ["Calendars.ReadWrite", "offline_access", "User.Read"]


def run_auth_calendar(provider: str, config: dict[str, Any] | None = None) -> int:
    """Interactive auth. Returns process exit code."""
    del config  # reserved for future redirect overrides
    name = (provider or "").strip().lower()
    if name == "google":
        return _auth_google()
    if name in {"outlook", "microsoft", "graph"}:
        return _auth_outlook()
    print(f"Unknown provider {provider!r}. Use google or outlook.")
    return 2


def _auth_google() -> int:
    secrets = load_calendar_secrets()
    if secrets.google is None or not secrets.google.configured:
        print(
            "Missing calendar.google.client_id / client_secret in data/secrets.yaml.\n"
            "See docs/calendar-oauth.md"
        )
        return 1
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Install google-auth-oauthlib: pip install google-auth-oauthlib")
        return 1

    client_config = {
        "installed": {
            "client_id": secrets.google.client_id,
            "client_secret": secrets.google.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, scopes=GOOGLE_SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    refresh = getattr(creds, "refresh_token", None) or ""
    if not refresh:
        print(
            "Google did not return a refresh_token. Revoke the app at "
            "https://myaccount.google.com/permissions and try again with prompt=consent."
        )
        return 1
    save_refresh_token("google", refresh)
    print("Google Calendar authorized. refresh_token saved to data/secrets.yaml")
    return 0


def _auth_outlook() -> int:
    secrets = load_calendar_secrets()
    if secrets.outlook is None or not secrets.outlook.configured:
        print(
            "Missing calendar.outlook.client_id in data/secrets.yaml.\n"
            "See docs/calendar-oauth.md"
        )
        return 1
    try:
        import msal
    except ImportError:
        print("Install msal: pip install msal")
        return 1

    app = msal.PublicClientApplication(
        secrets.outlook.client_id,
        authority=(
            f"https://login.microsoftonline.com/{secrets.outlook.tenant or 'consumers'}"
        ),
    )
    result = app.acquire_token_interactive(scopes=OUTLOOK_SCOPES)
    if not isinstance(result, dict) or "refresh_token" not in result:
        err = (result or {}).get("error_description") or (result or {}).get("error")
        print(f"Outlook auth failed: {err}")
        return 1
    save_refresh_token("outlook", str(result["refresh_token"]))
    print("Outlook authorized. refresh_token saved to data/secrets.yaml")
    return 0
