"""Deterministic Attention scan — measured watchers/proactivity v1.

No background poller, no silent send. Pure function over tasks/goals/agenda
(+ optional config inbox/file rules) so the morning briefing (and an attended
read-only tool) can surface what needs eyes soon. Empty result → omit the
section.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Coarse horizon phrases → end of local day / week / month windows.
_HORIZON_TODAY = re.compile(r"(?i)^(today|tonight)$")
_HORIZON_WEEK = re.compile(r"(?i)^(this\s+week|end\s+of\s+(?:the\s+)?week)$")
_HORIZON_MONTH = re.compile(
    r"(?i)^(this\s+month|end\s+of\s+(?:the\s+)?month)$"
)


@dataclass(frozen=True)
class AttentionItem:
    kind: str
    # overdue_task | due_soon_task | horizon_goal | soon_event | stale_task
    # | inbox_match | file_missing | file_stale
    text: str
    sort_key: str = ""


@dataclass(frozen=True)
class FileSnapshot:
    """mtime snapshot for a config file_rule path (collected at scan time)."""

    path: str
    exists: bool
    mtime: datetime | None = None


def collect_attention(
    *,
    now: datetime,
    tasks: list[dict[str, Any]] | None = None,
    goals: list[dict[str, Any]] | None = None,
    events: list[Any] | None = None,
    mail: list[dict[str, Any]] | None = None,
    inbox_rules: list[dict[str, Any]] | None = None,
    file_rules: list[dict[str, Any]] | None = None,
    file_snapshots: dict[str, FileSnapshot] | None = None,
    overdue_grace_days: int = 0,
    due_soon_days: int = 2,
    soon_hours: int = 24,
    stale_task_days: int = 7,
    limit: int = 12,
) -> list[AttentionItem]:
    """Build ranked attention items. Deterministic for a frozen `now`."""
    ref = now if now.tzinfo is not None else now.astimezone()
    items: list[AttentionItem] = []

    for row in tasks or []:
        if str(row.get("status") or "open") != "open":
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        tid = row.get("id")
        prefix = f"#{tid} " if tid is not None else ""
        due_raw = str(row.get("due") or "").strip()
        due_dt = _parse_dateish(due_raw, ref=ref)
        if due_dt is not None:
            due_day = due_dt.date()
            today = ref.date()
            overdue_cutoff = today - timedelta(days=max(0, overdue_grace_days))
            if due_day < overdue_cutoff:
                items.append(
                    AttentionItem(
                        kind="overdue_task",
                        text=f"Overdue task: {prefix}{title} (due {due_raw})",
                        sort_key=f"0:{due_raw}:{tid}",
                    )
                )
            elif due_day <= today + timedelta(days=max(0, due_soon_days)):
                label = "Due today" if due_day == today else "Due soon"
                items.append(
                    AttentionItem(
                        kind="due_soon_task",
                        text=f"{label} task: {prefix}{title} (due {due_raw})",
                        sort_key=f"1:{due_raw}:{tid}",
                    )
                )
        created = _parse_dateish(str(row.get("created_at") or ""), ref=ref)
        if created is not None and due_dt is None:
            age = ref.date() - created.date()
            if age.days >= stale_task_days:
                items.append(
                    AttentionItem(
                        kind="stale_task",
                        text=(
                            f"Stale open task: {prefix}{title} "
                            f"(open since {created.date().isoformat()})"
                        ),
                        sort_key=f"4:{created.date().isoformat()}:{tid}",
                    )
                )

    for row in goals or []:
        if str(row.get("status") or "") != "active":
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        horizon = str(row.get("horizon") or "").strip()
        if not horizon:
            continue
        if not _horizon_is_urgent(horizon, ref=ref):
            continue
        gid = row.get("id")
        prefix = f"#{gid} " if gid is not None else ""
        kind = str(row.get("kind") or "goal")
        items.append(
            AttentionItem(
                kind="horizon_goal",
                text=f"Horizon soon ({kind}): {prefix}{title} — {horizon}",
                sort_key=f"2:{horizon}:{gid}",
            )
        )

    soon_delta = timedelta(hours=max(1, soon_hours))
    for ev in events or []:
        starts = getattr(ev, "starts_at", None)
        summary = str(getattr(ev, "summary", "") or "").strip()
        all_day = bool(getattr(ev, "all_day", False))
        if starts is None or not summary:
            continue
        start_dt = starts
        if start_dt.tzinfo is None and ref.tzinfo is not None:
            start_dt = start_dt.replace(tzinfo=ref.tzinfo)
        elif start_dt.tzinfo is not None and ref.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=None)
        if all_day:
            # All-day: flag if the event day is today.
            if start_dt.date() == ref.date():
                items.append(
                    AttentionItem(
                        kind="soon_event",
                        text=f"Today (all-day): {summary}",
                        sort_key=f"3:{start_dt.isoformat()}:{summary}",
                    )
                )
            continue
        if ref <= start_dt <= ref + soon_delta:
            stamp = start_dt.strftime("%H:%M")
            items.append(
                AttentionItem(
                    kind="soon_event",
                    text=f"Soon ({stamp}): {summary}",
                    sort_key=f"3:{start_dt.isoformat()}:{summary}",
                )
            )

    items.extend(
        _inbox_rule_items(mail=mail or [], rules=inbox_rules or [])
    )
    items.extend(
        _file_rule_items(
            now=ref,
            rules=file_rules or [],
            snapshots=file_snapshots or {},
        )
    )

    items.sort(key=lambda item: item.sort_key)
    # Deduplicate by text while preserving order.
    seen: set[str] = set()
    unique: list[AttentionItem] = []
    for item in items:
        if item.text in seen:
            continue
        seen.add(item.text)
        unique.append(item)
        if len(unique) >= max(1, limit):
            break
    return unique


def format_attention_section(items: list[AttentionItem]) -> str:
    """Markdown body for ## Attention (no heading). Empty if nothing."""
    if not items:
        return ""
    return "\n".join(f"- {item.text}" for item in items)


def snapshot_file_rules(
    rules: list[dict[str, Any]] | None,
    *,
    project_root: Path | str,
    now: datetime | None = None,
) -> dict[str, FileSnapshot]:
    """Stat each file_rule path under project_root (scan-time snapshot)."""
    root = Path(project_root).resolve()
    ref = now or datetime.now().astimezone()
    out: dict[str, FileSnapshot] = {}
    for rule in rules or []:
        raw = str(rule.get("path") or "").strip()
        if not raw:
            continue
        try:
            path = _resolve_under_root(raw, root=root)
        except ValueError:
            out[raw] = FileSnapshot(path=raw, exists=False, mtime=None)
            continue
        if not path.is_file():
            out[raw] = FileSnapshot(path=raw, exists=False, mtime=None)
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=ref.tzinfo)
        except OSError:
            out[raw] = FileSnapshot(path=raw, exists=True, mtime=None)
            continue
        out[raw] = FileSnapshot(path=raw, exists=True, mtime=mtime)
    return out


def _resolve_under_root(raw: str, *, root: Path) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {raw}") from exc
    return resolved


def _inbox_rule_items(
    *,
    mail: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for rule in rules:
        rid = str(rule.get("id") or "inbox").strip() or "inbox"
        sender_sub = str(rule.get("sender_contains") or "").strip().lower()
        subject_sub = str(rule.get("subject_contains") or "").strip().lower()
        if not sender_sub and not subject_sub:
            continue
        matches: list[dict[str, Any]] = []
        for msg in mail:
            frm = str(msg.get("from") or "").lower()
            subj = str(msg.get("subject") or "").lower()
            if sender_sub and sender_sub not in frm:
                continue
            if subject_sub and subject_sub not in subj:
                continue
            matches.append(msg)
        if not matches:
            continue
        first = matches[0]
        subject = str(first.get("subject") or "(no subject)").strip()
        sender = str(first.get("from") or "(unknown)").strip()
        extra = f" (+{len(matches) - 1} more)" if len(matches) > 1 else ""
        items.append(
            AttentionItem(
                kind="inbox_match",
                text=f"Inbox match ({rid}): {subject} — {sender}{extra}",
                sort_key=f"0.5:{rid}:{subject}",
            )
        )
    return items


def _file_rule_items(
    *,
    now: datetime,
    rules: list[dict[str, Any]],
    snapshots: dict[str, FileSnapshot],
) -> list[AttentionItem]:
    items: list[AttentionItem] = []
    for rule in rules:
        rid = str(rule.get("id") or "").strip()
        raw = str(rule.get("path") or "").strip()
        if not raw:
            continue
        label = rid or raw
        snap = snapshots.get(raw)
        want_missing = bool(rule.get("missing"))
        older_raw = rule.get("older_than_days")
        older_days: int | None = None
        if older_raw is not None and str(older_raw).strip() != "":
            try:
                older_days = int(older_raw)
            except (TypeError, ValueError):
                older_days = None
        if want_missing and (snap is None or not snap.exists):
            items.append(
                AttentionItem(
                    kind="file_missing",
                    text=f"Missing file ({label}): {raw}",
                    sort_key=f"0.6:{label}:{raw}",
                )
            )
            continue
        if (
            older_days is not None
            and older_days >= 0
            and snap is not None
            and snap.exists
            and snap.mtime is not None
        ):
            age = now - snap.mtime
            if age.days >= older_days:
                items.append(
                    AttentionItem(
                        kind="file_stale",
                        text=(
                            f"Stale file ({label}): {raw} "
                            f"(mtime {snap.mtime.date().isoformat()}, "
                            f">={older_days}d)"
                        ),
                        sort_key=f"0.7:{snap.mtime.isoformat()}:{label}",
                    )
                )
    return items


def _parse_dateish(raw: str, *, ref: datetime) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    # Date-only first (common for task.due).
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            d = datetime.strptime(text, "%Y-%m-%d").date()
            return datetime(d.year, d.month, d.day, tzinfo=ref.tzinfo)
        except ValueError:
            return None
    cleaned = text.replace("Z", "+00:00")
    if " " in cleaned and "T" not in cleaned[:12]:
        cleaned = cleaned.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if dt.tzinfo is None and ref.tzinfo is not None:
        return dt.replace(tzinfo=ref.tzinfo)
    return dt


def _horizon_is_urgent(horizon: str, *, ref: datetime) -> bool:
    text = horizon.strip()
    if not text:
        return False
    if _HORIZON_TODAY.search(text):
        return True
    if _HORIZON_WEEK.search(text):
        return True
    # "this month" is softer — only flag in the last 7 days of the month.
    if _HORIZON_MONTH.search(text):
        # Last week of month.
        next_month = (ref.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day = next_month - timedelta(days=1)
        return (last_day - ref.date()).days <= 7
    due = _parse_dateish(text, ref=ref)
    if due is None:
        return False
    return due.date() <= ref.date() + timedelta(days=7)
