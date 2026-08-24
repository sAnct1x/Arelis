"""Pair the Android companion to this Arelis over the LAN.

The phone scans a QR (or pastes the same text). That ticket carries ingest
URLs, the ingest token, this instance id, and a short-lived pair secret.
The phone then POSTs /inbound/pair with its radio listen URL and a device
key. Phone DHCP is a second POST with the same device key — no new QR.
PC DHCP is a LAN beacon plus stored-URL failover; the phone adopts the new
ingest address without scanning again.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from arelis.identity import instance_id
from arelis.paths import state_dir

log = logging.getLogger(__name__)

SECRETS_PATH = state_dir() / "secrets.yaml"
PAIR_PATH = state_dir() / "sms_pair.json"
PAIR_TTL_S = 15 * 60
COMPANION_USER = "arelis"


@dataclass(frozen=True)
class PairTicket:
    instance: str
    urls: tuple[str, ...]
    token: str
    pair: str
    relay: str = ""

    def as_text(self) -> str:
        """Compact form the phone parser accepts (and the QR encodes)."""
        parts = [self.instance, self.token, self.pair, *self.urls]
        if self.relay:
            parts.append(self.relay)
        return "A1|" + "|".join(parts)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "v": 1,
            "kind": "arelis-pair",
            "instance": self.instance,
            "urls": list(self.urls),
            "token": self.token,
            "pair": self.pair,
        }
        if self.relay:
            data["relay"] = self.relay
        return data


def issue_pair_secret(*, ttl_s: int = PAIR_TTL_S, path: Path | None = None) -> str:
    """Mint a short-lived secret and persist it next to other mutable state."""
    path = path or PAIR_PATH
    secret = secrets.token_urlsafe(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pair": secret,
        "instance": instance_id(),
        "issued_at": time.time(),
        "ttl_s": int(ttl_s),
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return secret


def load_pair_record(path: Path | None = None) -> dict[str, Any] | None:
    path = path or PAIR_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return None
    return raw if isinstance(raw, dict) else None


def pair_secret_ok(candidate: str, *, path: Path | None = None, now: float | None = None) -> bool:
    raw = load_pair_record(path)
    if not raw:
        return False
    secret = str(raw.get("pair") or "").strip()
    if not secret or not candidate or secret != candidate.strip():
        return False
    if str(raw.get("instance") or "") != instance_id():
        return False
    issued = float(raw.get("issued_at") or 0)
    ttl = float(raw.get("ttl_s") or PAIR_TTL_S)
    stamp = time.time() if now is None else now
    return issued > 0 and (stamp - issued) <= ttl


def pairing_urls(port: int) -> tuple[str, ...]:
    from arelis.sms_ingest import list_lan_ipv4

    ips = list_lan_ipv4()
    if not ips:
        return (f"http://<this-pc-lan-ip>:{port}",)
    return tuple(f"http://{ip}:{port}" for ip in ips[:3])


def make_ticket(
    token: str,
    port: int,
    *,
    urls: tuple[str, ...] | None = None,
    rotate: bool = True,
) -> PairTicket:
    secret = ""
    if not rotate:
        rec = load_pair_record()
        stored = str((rec or {}).get("pair") or "")
        if stored and pair_secret_ok(stored):
            secret = stored
    if not secret:
        secret = issue_pair_secret()
    from arelis.relay.config import load_relay_settings

    relay = load_relay_settings().url
    return PairTicket(
        instance=instance_id(),
        urls=urls or pairing_urls(port),
        token=token.strip(),
        pair=secret,
        relay=relay,
    )


def parse_listen_url(url: str) -> str | None:
    """Accept a LAN http URL with a port. Reject loopback-as-only if it's public-looking."""
    text = (url or "").strip().rstrip("/")
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.hostname or ""
    if not host or parsed.port is None:
        return None
    return f"{parsed.scheme}://{host}:{parsed.port}"


def load_companion(path: Path | None = None) -> dict[str, str] | None:
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return None
    section = raw.get("sms") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return None
    companion = section.get("companion")
    if not isinstance(companion, dict):
        return None
    base = str(companion.get("base_url") or "").strip()
    key = str(companion.get("device_key") or "").strip()
    if not key:
        return None
    return {
        "base_url": base,
        "device_key": key,
        "instance": str(companion.get("instance") or "").strip(),
    }


def save_companion(
    *,
    listen_url: str,
    device_key: str,
    path: Path | None = None,
) -> None:
    """Write sms.companion without clobbering mail or SMSGate fields."""
    path = path or SECRETS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    sms = raw.get("sms")
    if not isinstance(sms, dict):
        sms = {}
        raw["sms"] = sms
    sms["companion"] = {
        "base_url": listen_url,
        "device_key": device_key,
        "instance": instance_id(),
    }
    path.write_text(
        yaml.safe_dump(raw, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def apply_pair(
    payload: dict[str, Any],
    *,
    secrets_path: Path | None = None,
    pair_path: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    """Validate a /inbound/pair body. Returns HTTP code and JSON object."""
    instance = str(payload.get("instance") or "").strip()
    if instance != instance_id():
        return 409, {"ok": False, "error": "wrong instance"}
    listen_raw = str(payload.get("listen_url") or "").strip()
    listen = parse_listen_url(listen_raw) if listen_raw else None
    if listen_raw and listen is None:
        return 400, {"ok": False, "error": "listen_url is not a LAN http URL with a port"}
    device_key = str(payload.get("device_key") or "").strip()
    pair = str(payload.get("pair") or "").strip()
    talk_only = bool(payload.get("talk")) or not listen_raw
    if not device_key:
        return 400, {"ok": False, "error": "device_key required"}
    if not talk_only and not listen:
        return 400, {"ok": False, "error": "listen_url and device_key required"}
    existing = load_companion(secrets_path)
    if existing and existing["device_key"] == device_key:
        if listen:
            save_companion(listen_url=listen, device_key=device_key, path=secrets_path)
        return 200, {
            "ok": True,
            "updated": True,
            "listen_url": listen or existing.get("base_url") or "",
            "talk": True,
        }
    if not pair_secret_ok(pair, path=pair_path):
        return 403, {"ok": False, "error": "pairing expired or missing"}
    save_companion(listen_url=listen or "", device_key=device_key, path=secrets_path)
    return 200, {
        "ok": True,
        "updated": False,
        "listen_url": listen or "",
        "talk": True,
    }
