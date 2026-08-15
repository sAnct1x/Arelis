"""One short system line: clock, place, role, and readiness snippets.

Assembled each turn and injected by the agent loop. Each field fails soft so a
missing store, secrets file, or location resolver never blanks the rest.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

_MAX_PROJECT_SNIPPET = 120


def world_state_prompt_line(
    config: dict[str, Any] | None,
    *,
    role: str,
    model: str,
    workspace: Any = None,
    store: Any = None,
) -> str:
    """Assemble one short world-state system line, or empty on total failure."""
    config = config or {}
    parts: list[str] = []

    try:
        parts.append(_clock_part())
    except Exception as exc:
        log.debug("world_state clock skipped: %s", exc)

    try:
        place = _place_part(config)
        if place:
            parts.append(place)
    except Exception as exc:
        log.debug("world_state place skipped: %s", exc)

    try:
        role_text = " ".join(str(role or "").split()) or "default"
        model_text = " ".join(str(model or "").split()) or "unknown"
        parts.append(f"role {role_text} ({model_text})")
    except Exception as exc:
        log.debug("world_state role skipped: %s", exc)

    try:
        tasks = _open_tasks_part(store)
        if tasks:
            parts.append(tasks)
    except Exception as exc:
        log.debug("world_state tasks skipped: %s", exc)

    try:
        goals = _active_goals_part(store)
        if goals:
            parts.append(goals)
    except Exception as exc:
        log.debug("world_state goals skipped: %s", exc)

    try:
        attention = _attention_count_part(store, config)
        if attention:
            parts.append(attention)
    except Exception as exc:
        log.debug("world_state attention skipped: %s", exc)

    try:
        cal = _calendar_part()
        if cal:
            parts.append(cal)
    except Exception as exc:
        log.debug("world_state calendar skipped: %s", exc)

    try:
        mail = _mail_part()
        if mail:
            parts.append(mail)
    except Exception as exc:
        log.debug("world_state mail skipped: %s", exc)

    try:
        sms = _sms_part()
        if sms:
            parts.append(sms)
    except Exception as exc:
        log.debug("world_state sms skipped: %s", exc)

    try:
        confirms = _pending_confirms_part(config)
        if confirms:
            parts.append(confirms)
    except Exception as exc:
        log.debug("world_state pending confirms skipped: %s", exc)

    if not parts:
        return ""
    return "World state: " + "; ".join(parts) + "."


def _clock_part() -> str:
    now = datetime.now().astimezone()
    stamp = now.strftime("%A, %d %B %Y, %H:%M").replace(" 0", " ")
    zone = now.strftime("%Z") or "local"
    return f"{stamp} ({zone})"


def _place_part(config: dict[str, Any]) -> str:
    loc = config.get("_location")
    if loc is None:
        return ""
    snap = loc
    snapshot = getattr(loc, "snapshot", None)
    if callable(snapshot):
        snap = snapshot()
    known = getattr(snap, "known", None)
    if callable(known) and not known():
        return ""
    place_fn = getattr(snap, "place", None)
    if not callable(place_fn):
        return ""
    place = " ".join(str(place_fn() or "").split())
    if not place:
        return ""
    return f"place {place}"


def _open_tasks_part(store: Any) -> str:
    if store is None:
        return ""
    list_tasks = getattr(store, "list_tasks", None)
    if not callable(list_tasks):
        return ""
    rows = list_tasks(status="open", limit=500)
    count = len(rows or [])
    return f"open tasks {count}"


def _active_goals_part(store: Any) -> str:
    if store is None:
        return ""
    list_goals = getattr(store, "list_goals", None)
    if not callable(list_goals):
        return ""
    rows = list_goals(status="active", limit=500)
    count = len(rows or [])
    return f"active goals {count}"


def _attention_count_part(store: Any, config: dict[str, Any]) -> str:
    """Count-only attention (tasks/goals/file rules; no IMAP/agenda)."""
    if store is None:
        return ""
    briefing_cfg = ((config.get("tools") or {}).get("briefing") or {})
    attention_cfg = briefing_cfg.get("attention") or {}
    if not bool(attention_cfg.get("enabled", True)):
        return ""
    from datetime import datetime

    from arelis.briefing.attention import collect_attention, snapshot_file_rules
    from arelis.config import PROJECT_ROOT

    list_tasks = getattr(store, "list_tasks", None)
    list_goals = getattr(store, "list_goals", None)
    tasks = list_tasks(status="open", limit=200) if callable(list_tasks) else []
    goals = list_goals(status="active", limit=200) if callable(list_goals) else []
    now = datetime.now().astimezone()
    file_rules = list(attention_cfg.get("file_rules") or [])
    snaps = snapshot_file_rules(file_rules, project_root=PROJECT_ROOT, now=now)
    items = collect_attention(
        now=now,
        tasks=tasks,
        goals=goals,
        events=[],
        mail=[],
        inbox_rules=[],
        file_rules=file_rules,
        file_snapshots=snaps,
        overdue_grace_days=int(attention_cfg.get("overdue_grace_days") or 0),
        due_soon_days=int(attention_cfg.get("due_soon_days") or 2),
        soon_hours=int(attention_cfg.get("soon_hours") or 24),
        stale_task_days=int(attention_cfg.get("stale_task_days") or 7),
        limit=int(attention_cfg.get("limit") or 12),
    )
    if not items:
        return ""
    return f"attention {len(items)}"


def _calendar_part() -> str:
    from arelis.calendar.secrets import load_calendar_secrets

    secrets = load_calendar_secrets()
    google = secrets.google
    if google is not None and google.authorized:
        return "calendar Google authorized"
    return "calendar Google not authorized"


def _mail_part() -> str:
    from arelis.mail import load_account

    account = load_account()
    if account is not None:
        return "mail configured"
    return "mail not configured"


def _sms_part() -> str:
    from arelis.sms_android import load_sms_account

    account = load_sms_account()
    if account is not None:
        return "SMS companion configured"
    return "SMS companion not configured"


def _pending_confirms_part(config: dict[str, Any]) -> str:
    from arelis.presence.pending_confirms import (
        PendingConfirmStore,
        pending_confirms_path,
    )

    items = PendingConfirmStore(pending_confirms_path(config)).list()
    count = len(items or [])
    if count <= 0:
        return ""
    return f"pending confirms {count}"


def _project_part(workspace: Any) -> str:
    if workspace is None:
        return ""
    prompt_line = getattr(workspace, "prompt_line", None)
    if not callable(prompt_line):
        return ""
    line = prompt_line()
    if not line:
        return ""
    text = " ".join(str(line).split())
    if not text:
        return ""
    # First sentence is enough; the path-qualify instruction is noise here.
    snippet = text.split(".")[0].strip()
    if not snippet:
        snippet = text
    if len(snippet) > _MAX_PROJECT_SNIPPET:
        snippet = snippet[: _MAX_PROJECT_SNIPPET - 1].rstrip() + "…"
    return snippet
