"""Browser OAuth for Google Calendar and Outlook.

The calendar tile owns re-auth. Testing-mode Google refresh tokens die
after about a week; that must open a browser, not a terminal command.
``--auth-calendar`` stays for headless / first setup of client ids.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from arelis.calendar.secrets import (
    load_calendar_secrets,
    save_refresh_token,
)

log = logging.getLogger(__name__)

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
OUTLOOK_SCOPES = ["Calendars.ReadWrite", "offline_access", "User.Read"]

SIGN_IN_HINT = "Sign in on the calendar tile."


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    provider: str
    error: str = ""


def is_reauth_error(text: str) -> bool:
    """True when a cloud call died because the refresh token is gone."""
    raw = (text or "").casefold()
    if "token refresh failed" in raw:
        return True
    if "not authorized" in raw and (
        "google" in raw or "outlook" in raw or "calendar" in raw
    ):
        return True
    return False


def authorize_calendar(provider: str) -> AuthResult:
    """Blocking browser consent. Safe to run on a worker thread."""
    name = (provider or "").strip().lower()
    if name == "google":
        return authorize_google()
    if name in {"outlook", "microsoft", "graph"}:
        return authorize_outlook()
    return AuthResult(ok=False, provider=name, error=f"Unknown provider {provider!r}.")


def authorize_google() -> AuthResult:
    secrets = load_calendar_secrets()
    if secrets.google is None or not secrets.google.configured:
        return AuthResult(
            ok=False,
            provider="google",
            error="Google Calendar is not set up in secrets yet.",
        )
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return AuthResult(
            ok=False,
            provider="google",
            error="google-auth-oauthlib is not installed.",
        )

    client_config = {
        "installed": {
            "client_id": secrets.google.client_id,
            "client_secret": secrets.google.client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    try:
        flow = InstalledAppFlow.from_client_config(
            client_config, scopes=GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0, prompt="consent")
    except Exception as exc:
        log.warning("Google calendar sign-in failed: %s", exc)
        return AuthResult(ok=False, provider="google", error=str(exc))
    refresh = getattr(creds, "refresh_token", None) or ""
    if not refresh:
        return AuthResult(
            ok=False,
            provider="google",
            error=(
                "Google did not return a refresh token. "
                "Revoke Arelis at https://myaccount.google.com/permissions and sign in again."
            ),
        )
    save_refresh_token("google", refresh)
    return AuthResult(ok=True, provider="google")


def authorize_outlook() -> AuthResult:
    secrets = load_calendar_secrets()
    if secrets.outlook is None or not secrets.outlook.configured:
        return AuthResult(
            ok=False,
            provider="outlook",
            error="Outlook is not set up in secrets yet.",
        )
    try:
        import msal
    except ImportError:
        return AuthResult(
            ok=False,
            provider="outlook",
            error="msal is not installed.",
        )

    app = msal.PublicClientApplication(
        secrets.outlook.client_id,
        authority=(
            f"https://login.microsoftonline.com/{secrets.outlook.tenant or 'consumers'}"
        ),
    )
    try:
        result = app.acquire_token_interactive(scopes=OUTLOOK_SCOPES)
    except Exception as exc:
        log.warning("Outlook calendar sign-in failed: %s", exc)
        return AuthResult(ok=False, provider="outlook", error=str(exc))
    if not isinstance(result, dict) or "refresh_token" not in result:
        err = (result or {}).get("error_description") or (result or {}).get("error")
        return AuthResult(
            ok=False,
            provider="outlook",
            error=str(err or "Outlook sign-in failed."),
        )
    save_refresh_token("outlook", str(result["refresh_token"]))
    return AuthResult(ok=True, provider="outlook")


def run_auth_calendar(provider: str, config: dict[str, Any] | None = None) -> int:
    """CLI wrapper. The tile is the everyday path."""
    del config
    result = authorize_calendar(provider)
    if result.ok:
        label = "Google Calendar" if result.provider == "google" else "Outlook"
        print(f"{label} authorized. refresh_token saved to data/secrets.yaml")
        return 0
    print(result.error)
    return 1 if result.provider in {"google", "outlook"} else 2
