"""Load calendar OAuth credentials from data/secrets.yaml."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

log = logging.getLogger(__name__)

SECRETS_PATH = state_dir() / "secrets.yaml"


@dataclass(frozen=True)
class GoogleCalendarCreds:
    client_id: str
    client_secret: str
    refresh_token: str = ""
    calendar_id: str = "primary"

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def authorized(self) -> bool:
        return self.configured and bool(self.refresh_token)


@dataclass(frozen=True)
class OutlookCalendarCreds:
    client_id: str
    client_secret: str = ""
    refresh_token: str = ""
    tenant: str = "consumers"
    calendar_id: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.client_id)

    @property
    def authorized(self) -> bool:
        return self.configured and bool(self.refresh_token)


@dataclass(frozen=True)
class CalendarSecrets:
    google: GoogleCalendarCreds | None
    outlook: OutlookCalendarCreds | None

    def any_authorized(self) -> bool:
        return bool(
            (self.google and self.google.authorized)
            or (self.outlook and self.outlook.authorized)
        )


def calendar_connected(path: Path | None = None) -> bool:
    """True when a live source exists: OAuth or an ICS URL.

    The agenda tool stays unregistered otherwise, so chat can say it cannot
    instead of calling a tool that fails every time.
    """
    if load_calendar_secrets(path).any_authorized():
        return True
    return bool(load_ics_url(path))


def load_calendar_secrets(path: Path | None = None) -> CalendarSecrets:
    path = path or SECRETS_PATH
    data = _calendar_section(path)
    return CalendarSecrets(
        google=_google(data.get("google")),
        outlook=_outlook(data.get("outlook")),
    )


def load_ics_url(path: Path | None = None) -> str:
    """Private ICS feed URL for local file sync (option S). Empty if unset."""
    data = _calendar_section(path or SECRETS_PATH)
    return str(data.get("ics_url") or "").strip()


def _calendar_section(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return {}
    section = raw.get("calendar") if isinstance(raw, dict) else None
    return section if isinstance(section, dict) else {}


def _google(raw: Any) -> GoogleCalendarCreds | None:
    if not isinstance(raw, dict):
        return None
    client_id = str(raw.get("client_id") or "").strip()
    client_secret = str(raw.get("client_secret") or "").strip()
    if not client_id and not client_secret:
        return None
    return GoogleCalendarCreds(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=str(raw.get("refresh_token") or "").strip(),
        calendar_id=str(raw.get("calendar_id") or "primary").strip() or "primary",
    )


def _outlook(raw: Any) -> OutlookCalendarCreds | None:
    if not isinstance(raw, dict):
        return None
    client_id = str(raw.get("client_id") or "").strip()
    if not client_id:
        return None
    return OutlookCalendarCreds(
        client_id=client_id,
        client_secret=str(raw.get("client_secret") or "").strip(),
        refresh_token=str(raw.get("refresh_token") or "").strip(),
        tenant=str(raw.get("tenant") or "consumers").strip() or "consumers",
        calendar_id=str(raw.get("calendar_id") or "").strip(),
    )


def save_refresh_token(
    provider: str,
    refresh_token: str,
    *,
    path: Path | None = None,
) -> None:
    """Persist a refresh token into secrets.yaml without clobbering other keys."""
    path = path or SECRETS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    cal = raw.setdefault("calendar", {})
    if not isinstance(cal, dict):
        cal = {}
        raw["calendar"] = cal
    block = cal.setdefault(provider, {})
    if not isinstance(block, dict):
        block = {}
        cal[provider] = block
    block["refresh_token"] = refresh_token
    path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
