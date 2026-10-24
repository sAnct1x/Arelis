"""Loopback-only IPC protocol, port candidates, and session token authentication."""

from __future__ import annotations

import hmac
import secrets
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from sentinel.paths import token_path

PROTOCOL_VERSION = 1
PORT_SEARCH_SPAN = 6
TOKEN_HEADER = "X-Sentinel-Token"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def assert_loopback_host(host: str) -> str:
    """Enforce loopback-only binding (never 0.0.0.0)."""
    cleaned = (host or "").strip().lower()
    if cleaned not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"Sentinel Bridge must bind loopback (127.0.0.1 / ::1), got {host!r}"
        )
    return "127.0.0.1" if cleaned == "localhost" else cleaned


def port_candidates(preferred: int, span: int = PORT_SEARCH_SPAN) -> list[int]:
    """Preferred port first, then next few ports above it (matches arelis/presence/ports.py)."""
    first = int(preferred)
    if first == 0:
        return [0]
    if first < 1 or first > 65535:
        return []
    return [p for p in range(first, first + max(1, int(span))) if p <= 65535]


def ensure_session_token(path: Path | None = None) -> str:
    """Read or mint the 256-bit local session token for Arelis <-> Sentinel authentication."""
    p = path or token_path()
    if p.is_file():
        existing = p.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    tok = secrets.token_hex(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok, encoding="utf-8")
    return tok


def verify_session_token(candidate: str | None, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate.strip(), expected.strip())


def token_from_headers(headers: Mapping[str, str]) -> str:
    """Read the session token from X-Sentinel-Token, or from Bearer."""
    by_lower = {str(key).lower(): value for key, value in headers.items()}
    raw = (by_lower.get("x-sentinel-token") or "").strip()
    if raw:
        return raw
    authorization = (by_lower.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def command_headers(token: str) -> dict[str, str]:
    """HTTP headers every command-bridge client sends."""
    return {TOKEN_HEADER: token}


def hello_message(*, token: str | None = None) -> dict[str, Any]:
    """First WebSocket frame. Same shape as Arelis IPC hello."""
    msg: dict[str, Any] = {"op": "hello", "version": PROTOCOL_VERSION}
    if token:
        msg["token"] = token
    return msg


def overseer_public_url(host: str, port: int) -> str:
    """Static HUD path. No token. Safe to log or print."""
    return f"http://{host}:{int(port)}/overseer"


def overseer_open_url(host: str, port: int, token: str) -> str:
    """HUD URL with the session token in the fragment.

    Fragments are not sent to the server and are not written to access logs.
    Callers that open the page (QWebEngine, webbrowser) keep the fragment.
    """
    return f"http://{host}:{int(port)}/overseer#token={token}"


def format_command_response(ok: bool, data: dict[str, Any] | None = None, error: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"ok": bool(ok), "version": PROTOCOL_VERSION}
    if error:
        out["error"] = error
    if data:
        out.update(data)
    return out
