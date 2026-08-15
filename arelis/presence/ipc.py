"""JSON-lines framing for the Core↔UI live event bridge (loopback only).

Protocol (one JSON object per line), presence design 2026-08-08:

- hello: UI → core (subscribe)
- event: core → UI (allowlisted bus events)
- confirm_reply: UI → core (allow/skip for a confirm id)
- open_ui: core → UI (bring window to front / show pending confirms)
- open_ui_request: UI → core (second-instance activate; core rebroadcasts open_ui)
- shutdown: UI/tray → core (full core quit; no silent send)
- bye: either side, optional clean close

Never bind 0.0.0.0. No silent send — confirm_reply only carries a human decision.
No named pipes — loopback TCP is enough for open_ui.
"""

from __future__ import annotations

import json
from typing import Any

from arelis.core.events import Event, EventType

PROTOCOL_VERSION = 1

# Events the core may push to an attached UI.
FORWARD_TYPES = frozenset(
    {
        EventType.SMS_RECEIVED,
        EventType.TOOL_CONFIRM,
        EventType.STATUS,
    }
)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def assert_loopback_host(host: str) -> str:
    """Return normalized host or raise ValueError if not loopback."""
    cleaned = (host or "").strip().lower()
    if cleaned not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"IPC host must be loopback (127.0.0.1 / ::1), got {host!r}"
        )
    # Prefer IPv4 literal for asyncio start_server clarity on Windows.
    if cleaned == "localhost":
        return "127.0.0.1"
    return cleaned


def encode_line(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def decode_line(raw: bytes | str) -> dict[str, Any] | None:
    text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
    text = text.strip()
    if not text:
        return None
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("IPC line must be a JSON object")
    return data


def hello_message(*, role: str = "ui") -> dict[str, Any]:
    return {"op": "hello", "role": role, "version": PROTOCOL_VERSION}


def bye_message() -> dict[str, Any]:
    return {"op": "bye"}


def event_message(event: Event) -> dict[str, Any] | None:
    """Encode a bus event for the wire, or None if not forwardable."""
    if event.type not in FORWARD_TYPES:
        return None
    payload = dict(event.payload or {})
    # Avoid re-forward loops if a client ever echoed.
    if payload.get("_from_ipc"):
        return None
    return {
        "op": "event",
        "type": event.type.value,
        "payload": payload,
        "id": event.id,
    }


def confirm_reply_message(confirm_id: str, decision: str) -> dict[str, Any]:
    return {
        "op": "confirm_reply",
        "id": str(confirm_id),
        "decision": str(decision),
    }


def open_ui_message(**kwargs: Any) -> dict[str, Any]:
    """Core → UI: foreground the glass (same intent as tray Open Arelis)."""
    msg: dict[str, Any] = {"op": "open_ui"}
    for key, value in kwargs.items():
        if value is not None:
            msg[key] = value
    return msg


def open_ui_request_message(**kwargs: Any) -> dict[str, Any]:
    """UI → core: ask core to rebroadcast open_ui (second-instance activate)."""
    msg: dict[str, Any] = {"op": "open_ui_request"}
    for key, value in kwargs.items():
        if value is not None:
            msg[key] = value
    return msg


def shutdown_message(*, reason: str = "quit") -> dict[str, Any]:
    """UI/tray → core: request a clean core shutdown."""
    return {"op": "shutdown", "reason": str(reason or "quit")}


def event_from_message(msg: dict[str, Any]) -> Event | None:
    """Rebuild a bus Event from an IPC event message."""
    if msg.get("op") != "event":
        return None
    type_name = str(msg.get("type") or "").strip()
    try:
        etype = EventType(type_name)
    except ValueError:
        return None
    if etype not in FORWARD_TYPES:
        return None
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    payload = {**payload, "_from_ipc": True}
    eid = str(msg.get("id") or "").strip() or None
    if eid:
        return Event(etype, payload, id=eid)
    return Event(etype, payload)
