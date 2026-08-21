"""Mailbox settings. Empty URL means LAN-only; that is the shipped default."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

SECRETS_PATH = state_dir() / "secrets.yaml"
URL_ENV = "ARELIS_RELAY_URL"
TOKEN_ENV = "ARELIS_RELAY_TOKEN"


@dataclass(frozen=True)
class RelaySettings:
    url: str
    token: str


def load_relay_settings(path: Path | None = None) -> RelaySettings:
    url = (os.environ.get(URL_ENV) or "").strip().rstrip("/")
    token = (os.environ.get(TOKEN_ENV) or "").strip()
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    except (OSError, yaml.YAMLError):
        raw = {}
    section: Any = raw.get("sms") if isinstance(raw, dict) else None
    if isinstance(section, dict):
        if not url:
            url = str(section.get("relay_url") or "").strip().rstrip("/")
        if not token:
            token = str(section.get("relay_token") or "").strip()
    return RelaySettings(url=url, token=token)
