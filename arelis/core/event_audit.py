"""Durable audit trail for high-value bus events → logs/events.log.

ASSISTANT_DELTA and audio clips are intentionally omitted (too noisy). Turn
latency stays in turns.log; this file answers “what happened on the bus?”
for confirms, SMS, errors, and tool boundaries.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.paths import logs_dir

log = logging.getLogger("arelis.event.audit")

_HANDLER_TAG = "arelis-event-audit"
_attached = False

# High-signal types only. Deltas/audio would drown the file.
_AUDITED: frozenset[EventType] = frozenset(
    {
        EventType.USER_MESSAGE,
        EventType.ASSISTANT_DONE,
        EventType.ASSISTANT_RETRACT,
        EventType.ERROR,
        EventType.TOOL_START,
        EventType.TOOL_RESULT,
        EventType.TOOL_CONFIRM,
        EventType.TOOL_CONFIRM_REPLY,
        EventType.TURN_CANCEL,
        EventType.TURN_PAUSE,
        EventType.TURN_RESUME,
        EventType.MODEL_SWITCH,
        EventType.SMS_RECEIVED,
        EventType.SESSION_LOAD,
        EventType.SESSION_LOADED,
        EventType.VOICE_TRANSCRIPT,
        EventType.STATUS,
        EventType.MOBILE_SYNC,
    }
)

# STATUS lines are chatty; keep only a short allowlist of prefixes.
_STATUS_PREFIXES: tuple[str, ...] = (
    "Role ",
    "SMS",
    "Inbound",
    "Confirm",
    "pending",
    "Arelis",
    "Arelis Chrome",
    "your turn",
    "Voice",
    "Mail",
    "Job",
    "Ollama",
    "Model",
    "Warm",
    "Lesson",
    "Indexer",
    "Comfy",
    "Core IPC",
    "Live bridge",
    "Detached",
    "open_ui",
)


def event_telemetry_enabled(config: dict[str, Any] | None) -> bool:
    agent = (config or {}).get("agent") or {}
    return bool(agent.get("event_telemetry", True))


def ensure_event_log(log_dir: Path | None = None) -> None:
    """Attach rotating events.log once per process."""
    global _attached
    if _attached:
        return
    directory = log_dir or logs_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(
            directory / "events.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._arelis_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    for existing in log.handlers:
        if getattr(existing, "_arelis_tag", "") == _HANDLER_TAG:
            _attached = True
            return
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    _attached = True


def attach_event_audit(bus: EventBus, config: dict[str, Any] | None = None) -> bool:
    """Subscribe a bus wildcard that writes audited events. Returns True if on."""
    if not event_telemetry_enabled(config):
        return False
    ensure_event_log()

    async def _audit(event: Event) -> None:
        if event.type not in _AUDITED:
            return
        if event.type == EventType.STATUS and not _status_interesting(event.payload):
            return
        log.info(_format_event(event))

    bus.subscribe(None, _audit)
    return True


def log_side_effect(
    event: str,
    *,
    tool: str = "",
    ok: bool | None = None,
    confirm_id: str = "",
    detail: str = "",
    turn_id: str = "-",
    session_id: str = "-",
) -> None:
    """Record a side-effect outside the agent loop (restored confirms, etc.)."""
    ensure_event_log()
    fields: dict[str, Any] = {}
    if tool:
        fields["tool"] = tool
    if ok is not None:
        fields["ok"] = ok
    if confirm_id:
        fields["confirm"] = confirm_id
    if detail:
        fields["detail"] = _clip(detail, 160)
    if session_id and session_id != "-":
        fields["session"] = session_id
    body = " ".join(f"{k}={_render(v)}" for k, v in fields.items())
    stamp = _stamp()
    log.info(f"side {stamp} {event:<12} id={turn_id} {body}".rstrip())


def _status_interesting(payload: dict[str, Any] | None) -> bool:
    message = str((payload or {}).get("message") or "").strip()
    if not message:
        return False
    return any(message.startswith(p) for p in _STATUS_PREFIXES)


def _format_event(event: Event) -> str:
    payload = event.payload or {}
    fields: dict[str, Any] = {"eid": (event.id or uuid4().hex)[:8]}
    if event.type == EventType.USER_MESSAGE:
        text = str(payload.get("text") or "")
        fields["chars"] = len(text)
        fields["source"] = payload.get("source") or "chat"
        fields["preview"] = _clip(text, 80)
    elif event.type == EventType.ASSISTANT_DONE:
        text = str(payload.get("text") or "")
        fields["chars"] = len(text)
        fields["preview"] = _clip(text, 240)
    elif event.type == EventType.TOOL_START:
        fields["tool"] = payload.get("tool") or "?"
        fields["summary"] = _clip(str(payload.get("summary") or ""), 100)
    elif event.type == EventType.TOOL_RESULT:
        fields["tool"] = payload.get("tool") or "?"
        fields["ok"] = bool(payload.get("ok"))
        fields["preview"] = _clip(str(payload.get("output") or ""), 400)
    elif event.type in {EventType.TOOL_CONFIRM, EventType.TOOL_CONFIRM_REPLY}:
        fields["confirm"] = payload.get("id") or "?"
        fields["tool"] = payload.get("tool") or "?"
        if event.type == EventType.TOOL_CONFIRM_REPLY:
            fields["decision"] = payload.get("decision") or "?"
        else:
            fields["summary"] = _clip(str(payload.get("summary") or ""), 100)
    elif event.type == EventType.ERROR:
        fields["scope"] = payload.get("scope") or "turn"
        fields["message"] = _clip(str(payload.get("message") or ""), 160)
    elif event.type == EventType.MODEL_SWITCH:
        fields["from"] = payload.get("from") or "?"
        fields["to"] = payload.get("to") or "?"
        fields["role"] = payload.get("role") or "?"
    elif event.type == EventType.SMS_RECEIVED:
        who = (
            payload.get("contact_name")
            or payload.get("contact_alias")
            or payload.get("from")
            or "?"
        )
        fields["from"] = who
        fields["preview"] = _clip(str(payload.get("body") or ""), 80)
    elif event.type in {EventType.SESSION_LOAD, EventType.SESSION_LOADED}:
        fields["session"] = payload.get("session_id") or "?"
        if "ok" in payload:
            fields["ok"] = payload.get("ok")
    elif event.type == EventType.VOICE_TRANSCRIPT:
        fields["chars"] = len(str(payload.get("text") or ""))
        fields["preview"] = _clip(str(payload.get("text") or ""), 80)
    elif event.type == EventType.STATUS:
        fields["message"] = _clip(str(payload.get("message") or ""), 160)
    elif event.type == EventType.TURN_CANCEL:
        fields["reason"] = payload.get("reason") or "cancel"
    elif event.type == EventType.TURN_PAUSE:
        fields["reason"] = payload.get("reason") or "pause"
    elif event.type == EventType.TURN_RESUME:
        fields["reason"] = payload.get("reason") or "resume"
    stamp = _stamp()
    body = " ".join(f"{k}={_render(v)}" for k, v in fields.items())
    return f"bus  {stamp} {event.type.value:<22} {body}".rstrip()


def _stamp() -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    return f"{stamp}.{millis:03d}"


def _clip(text: str, limit: int) -> str:
    cleaned = text.replace("\n", " ").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)
