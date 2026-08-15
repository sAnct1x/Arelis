"""Assemble a fixed-template briefing from mail, weather, and local memory.

The point of a template is that a 7am email is useful even when the model would
have wandered. Scheduled jobs call this directly; the chat tool returns the
same text on demand.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from arelis.briefing.attention import (
    collect_attention,
    format_attention_section,
    snapshot_file_rules,
)
from arelis.briefing.calendar import (
    CalendarEvent,
    format_agenda_section,
    load_agenda,
    resolve_calendar_path,
)
from arelis.briefing.weather import describe_weather_code, fetch_current_weather
from arelis.config import PROJECT_ROOT, load_config
from arelis.jobs.store import Job
from arelis.location import LocationResolver, build_location
from arelis.mail import load_account
from arelis.memory import MemoryStore

log = logging.getLogger(__name__)

# Stored as the job prompt so the runner can recognise a briefing without a
# new schema field. Hand-edited jobs.yaml can use the same sentinel.
BRIEFING_PROMPT = "__arelis_briefing__"


def is_briefing_job(job: Job) -> bool:
    return (job.prompt or "").strip() == BRIEFING_PROMPT


async def build_briefing(
    config: dict[str, Any] | None = None,
    *,
    store: MemoryStore | None = None,
    inbox: Any | None = None,
    location: LocationResolver | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Return markdown for today's briefing."""
    config = config or load_config()
    briefing_cfg = ((config.get("tools") or {}).get("briefing") or {})
    mail_limit = int(briefing_cfg.get("mail_limit", 10))
    fact_limit = int(briefing_cfg.get("fact_limit", 8))
    task_limit = int(briefing_cfg.get("task_limit", 12))
    goal_limit = int(briefing_cfg.get("goal_limit", 8))
    session_limit = int(briefing_cfg.get("session_limit", 5))
    attention_cfg = briefing_cfg.get("attention") or {}
    attention_enabled = bool(attention_cfg.get("enabled", True))

    now = datetime.now().astimezone()
    stamp = now.strftime("%A, %d %B %Y").replace(" 0", " ")
    sections: list[str] = [f"# Briefing — {stamp}", ""]

    owns_store = store is None
    if store is None:
        store = MemoryStore()
    try:
        loc = location or config.get("_location") or build_location(config)
        weather_block = await _weather_section(loc, http_client=http_client)
        if weather_block:
            sections.extend(["## Weather", weather_block, ""])

        mail_block, mail_messages = await _mail_section(
            config, inbox=inbox, limit=mail_limit
        )
        sections.extend(["## Unread mail", mail_block, ""])

        agenda_events = load_briefing_events(config, now=now)
        if attention_enabled:
            attention = _attention_section(
                store,
                events=agenda_events,
                now=now,
                cfg=attention_cfg,
                mail=mail_messages,
            )
            if attention:
                sections.extend(["## Attention", attention, ""])

        loops = _open_loops_section(store, limit=fact_limit)
        if loops:
            sections.extend(["## Open loops", loops, ""])

        tasks = _tasks_section(store, limit=task_limit)
        if tasks:
            sections.extend(["## Tasks", tasks, ""])

        goals = _goals_section(store, limit=goal_limit)
        if goals:
            sections.extend(["## Goals", goals, ""])

        recent = _recent_sessions_section(store, limit=session_limit)
        if recent:
            sections.extend(["## Recent conversations", recent, ""])

        if agenda_events:
            agenda = format_agenda_section(agenda_events, now=now)
        else:
            agenda = _calendar_missing_message(config)
        sections.extend(["## Agenda", agenda, ""])
        sections.append("_Ask in chat for anything else._")
        return "\n".join(sections).rstrip() + "\n"
    finally:
        if owns_store:
            store.close()


def _attention_section(
    store: MemoryStore,
    *,
    events: list[CalendarEvent],
    now: datetime,
    cfg: dict[str, Any],
    mail: list[dict[str, Any]] | None = None,
) -> str:
    list_tasks = getattr(store, "list_tasks", None)
    list_goals = getattr(store, "list_goals", None)
    tasks = list_tasks(status="open", limit=200) if callable(list_tasks) else []
    goals = list_goals(status="active", limit=200) if callable(list_goals) else []
    inbox_rules = list(cfg.get("inbox_rules") or [])
    file_rules = list(cfg.get("file_rules") or [])
    snaps = snapshot_file_rules(file_rules, project_root=PROJECT_ROOT, now=now)
    items = collect_attention(
        now=now,
        tasks=tasks,
        goals=goals,
        events=events,
        mail=mail or [],
        inbox_rules=inbox_rules,
        file_rules=file_rules,
        file_snapshots=snaps,
        overdue_grace_days=int(cfg.get("overdue_grace_days") or 0),
        due_soon_days=int(cfg.get("due_soon_days") or 2),
        soon_hours=int(cfg.get("soon_hours") or 24),
        stale_task_days=int(cfg.get("stale_task_days") or 7),
        limit=int(cfg.get("limit") or 12),
    )
    return format_attention_section(items)


def load_briefing_events(
    config: dict[str, Any], *, now: datetime | None = None
) -> list[CalendarEvent]:
    """Prefer synced cache; fall back to local ICS. Empty if neither."""
    now = now or datetime.now().astimezone()
    try:
        from arelis.calendar.store import CalendarStore

        cal_store = CalendarStore()
        try:
            today = now.date()
            cached = cal_store.list_range(today, today + timedelta(days=1))
        finally:
            cal_store.close()
        if cached:
            return [
                CalendarEvent(
                    starts_at=ev.starts_at,
                    summary=f"[{ev.provider}] {ev.summary}",
                    all_day=ev.all_day,
                )
                for ev in cached
            ]
    except Exception as exc:
        log.warning("Calendar cache read for briefing failed: %s", exc)

    path = resolve_calendar_path(config)
    if path.is_file():
        return load_agenda(path, now=now, days=2)
    return []


def _calendar_missing_message(config: dict[str, Any]) -> str:
    briefing_cfg = ((config.get("tools") or {}).get("briefing") or {})
    raw_path = str(briefing_cfg.get("calendar_path") or "data/calendar.ics").strip()
    return (
        "No calendar data. Authorize Google/Outlook "
        "(`arelis --auth-calendar …`) or copy `data/calendar.example.ics` to "
        f"`{raw_path}`."
    )


async def _weather_section(
    location: LocationResolver,
    *,
    http_client: httpx.AsyncClient | None,
) -> str:
    snap = location.snapshot()
    place = snap.place() or "your area"
    if not snap.has_coordinates():
        if snap.known():
            return f"{place} — no coordinates on file, so weather was skipped."
        return ""
    try:
        wx = await fetch_current_weather(
            float(snap.latitude),
            float(snap.longitude),
            client=http_client,
        )
    except Exception as exc:
        log.info("Briefing weather skipped: %s", exc)
        return f"{place} — weather lookup failed ({exc})."
    condition = describe_weather_code(wx.get("weather_code"))
    temp = wx.get("temperature_2m")
    feels = wx.get("apparent_temperature")
    parts = [f"**{place}**"]
    if temp is not None:
        line = f"{temp:.0f}°F"
        if feels is not None and abs(float(feels) - float(temp)) >= 2:
            line += f" (feels like {float(feels):.0f}°F)"
        if condition:
            line += f", {condition}"
        parts.append(line)
    elif condition:
        parts.append(condition)
    hi = wx.get("temperature_2m_max")
    lo = wx.get("temperature_2m_min")
    pop = wx.get("precipitation_probability_max")
    day_bits: list[str] = []
    if hi is not None and lo is not None:
        day_bits.append(f"today {float(lo):.0f}-{float(hi):.0f}°F")
    if pop is not None:
        day_bits.append(f"{int(pop)}% chance of precip")
    if day_bits:
        parts.append(", ".join(day_bits))
    return " · ".join(parts)


async def _mail_section(
    config: dict[str, Any],
    *,
    inbox: Any | None,
    limit: int,
) -> tuple[str, list[dict[str, Any]]]:
    tool = inbox
    if tool is None:
        account = load_account()
        if account is None:
            return "Email is not configured (`data/secrets.yaml`).", []
        # Imported here so arelis.briefing can load without pulling in tools/.
        from arelis.tools.inbox import InboxTool

        email_cfg = (config.get("tools") or {}).get("email") or {}
        tool = InboxTool(
            account,
            host=email_cfg.get("imap_host", "imap.gmail.com"),
            port=int(email_cfg.get("imap_port", 993)),
            timeout_s=float(email_cfg.get("timeout_s", 30)),
            max_messages=limit,
        )
    result = await tool.run(action="list", unread_only=True, limit=limit)
    if not result.ok:
        return f"Could not read the inbox: {result.output}", []
    data = result.data or {}
    messages = list(data.get("messages") or [])
    total = data.get("total")
    unread = data.get("unread")
    if not messages:
        if total is not None or unread is not None:
            return (
                f"No unread messages. Mailbox: {total} total, {unread} unread.",
                [],
            )
        return "No unread messages.", []
    lines: list[str] = []
    matched = data.get("matched", len(messages))
    head = f"Showing {len(messages)} of {matched} unread"
    if total is not None:
        head += f" (mailbox {total} total, {unread} unread)"
    lines.append(head + ".")
    for item in messages:
        subject = str(item.get("subject") or "(no subject)")
        sender = str(item.get("from") or "(unknown)")
        date = str(item.get("date") or "")
        lines.append(f"- **{subject}** — {sender}" + (f" · {date}" if date else ""))
    return "\n".join(lines), messages


def _open_loops_section(store: MemoryStore, *, limit: int) -> str:
    facts = store.list_facts(status="active", limit=limit)
    if not facts:
        return ""
    return "\n".join(f"- {row['text']}" for row in facts if row.get("text"))


def _tasks_section(store: MemoryStore, *, limit: int) -> str:
    """Open local to-dos from memory.db (beside open-loop facts)."""
    list_tasks = getattr(store, "list_tasks", None)
    if not callable(list_tasks):
        return ""
    rows = list_tasks(status="open", limit=limit)
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        due = str(row.get("due") or "").strip()
        tid = row.get("id")
        prefix = f"#{tid} " if tid is not None else ""
        suffix = f" (due {due})" if due else ""
        gid = row.get("goal_id")
        link = f" → goal #{gid}" if gid is not None and str(gid).strip() != "" else ""
        lines.append(f"- {prefix}{title}{suffix}{link}")
    if not lines:
        return ""
    stale = _stale_task_lines(rows, older_than_days=7)
    if stale:
        lines.append("")
        lines.append("### Stale tasks")
        lines.extend(stale)
    return "\n".join(lines)


def _goals_section(store: MemoryStore, *, limit: int) -> str:
    """Active (+ paused) goals/commitments from memory.db."""
    list_goals = getattr(store, "list_goals", None)
    if not callable(list_goals):
        return ""
    # Pull a bit extra so paused items can share the cap with active.
    rows = list_goals(status=None, limit=max(limit * 2, limit))
    if not rows:
        return ""
    active = [r for r in rows if str(r.get("status") or "") == "active"]
    paused = [r for r in rows if str(r.get("status") or "") == "paused"]
    chosen = (active + paused)[:limit]
    if not chosen:
        return ""
    lines: list[str] = []
    for row in chosen:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        gid = row.get("id")
        kind = str(row.get("kind") or "goal")
        status = str(row.get("status") or "active")
        horizon = str(row.get("horizon") or "").strip()
        prefix = f"#{gid} " if gid is not None else ""
        tag = f"[{status}/{kind}]"
        suffix = f" — {horizon}" if horizon else ""
        lines.append(f"- {prefix}{tag} {title}{suffix}")
    return "\n".join(lines)


def _parse_task_created_at(raw: str) -> datetime | None:
    """Best-effort parse of task created_at (ISO or date-only)."""
    text = (raw or "").strip()
    if not text:
        return None
    # SQLite / store uses UTC ISO; tolerate trailing Z and space separator.
    cleaned = text.replace("Z", "+00:00")
    if " " in cleaned and "T" not in cleaned[:12]:
        cleaned = cleaned.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _stale_task_lines(
    rows: list[dict[str, Any]],
    *,
    older_than_days: int = 7,
    now: datetime | None = None,
) -> list[str]:
    """Open tasks with created_at older than N days → bullet lines."""
    ref = now or datetime.now().astimezone()
    if ref.tzinfo is None:
        cutoff = ref - timedelta(days=older_than_days)
    else:
        cutoff = ref - timedelta(days=older_than_days)
    lines: list[str] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        created = _parse_task_created_at(str(row.get("created_at") or ""))
        if created is None:
            continue
        # Compare naive/aware safely.
        if created.tzinfo is None and cutoff.tzinfo is not None:
            created_cmp = created.replace(tzinfo=cutoff.tzinfo)
        elif created.tzinfo is not None and cutoff.tzinfo is None:
            created_cmp = created.replace(tzinfo=None)
        else:
            created_cmp = created
        if created_cmp > cutoff:
            continue
        tid = row.get("id")
        prefix = f"#{tid} " if tid is not None else ""
        age = str(row.get("created_at") or "")[:10]
        suffix = f" (open since {age})" if age else ""
        lines.append(f"- {prefix}{title}{suffix}")
    return lines


def _recent_sessions_section(store: MemoryStore, *, limit: int) -> str:
    sessions = store.list_sessions(limit=limit * 2)
    lines: list[str] = []
    for row in sessions:
        title = str(row.get("title") or "").strip()
        if not title or title.lower() in {"new chat", "new conversation"}:
            continue
        started = str(row.get("started_at") or "")[:10]
        prefix = f"{started}: " if started else ""
        lines.append(f"- {prefix}{title}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _calendar_section(config: dict[str, Any], *, now: datetime) -> str:
    """Prefer synced Google/Outlook cache; fall back to local ICS."""
    events = load_briefing_events(config, now=now)
    if events:
        return format_agenda_section(events, now=now)
    return _calendar_missing_message(config)
