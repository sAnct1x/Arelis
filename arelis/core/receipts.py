"""Structured action receipts + append-only action ledger.

Exactness already refuses send claims without a warrant; receipts make the
audit trail human-readable in Thinking / the turn tool trace. The ledger file
is operational truth across turns (gitignored under data/).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT

log = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = PROJECT_ROOT / "data" / "action_ledger.jsonl"

# Mutating / side-effect tools that should emit a receipt when they succeed.
_RECEIPT_TOOLS = frozenset(
    {
        "send_email",
        "send_sms",
        "agenda",
        "tasks",
        "goals",
        "workspace",
        "memory",
        "browser",
        "image",
        "vision",
        "look",
        "research_report",
        "contacts",
    }
)

_AGENDA_MUTATE = frozenset({"create", "update", "delete"})
_TASKS_MUTATE = frozenset(
    {"add", "done", "reopen", "remove", "attach", "detach"}
)
_GOALS_MUTATE = frozenset(
    {"add", "update", "pause", "resume", "done", "drop", "remove"}
)
_WORKSPACE_MUTATE = frozenset({"write", "edit"})
_MEMORY_MUTATE = frozenset({"remember", "forget", "prefer", "decide", "episode"})
_CONTACTS_MUTATE = frozenset({"add", "update", "remove"})
_BROWSER_MUTATE = frozenset(
    {"open", "navigate", "click", "type", "relaunch", "screenshot"}
)


def action_receipt(
    name: str,
    *,
    ok: bool,
    args: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a receipt dict for a successful mutate, else None."""
    tool = (name or "").strip()
    if tool not in _RECEIPT_TOOLS or not ok:
        return None
    args = args or {}
    data = data or {}
    action = str(args.get("action") or "").strip().lower()

    if tool == "agenda" and action not in _AGENDA_MUTATE:
        return None
    if tool == "tasks" and action not in _TASKS_MUTATE:
        return None
    if tool == "goals" and action not in _GOALS_MUTATE:
        return None
    if tool == "workspace" and action not in _WORKSPACE_MUTATE:
        return None
    if tool == "memory" and action not in _MEMORY_MUTATE:
        return None
    if tool == "contacts" and action not in _CONTACTS_MUTATE:
        return None
    if tool == "browser" and action not in _BROWSER_MUTATE:
        return None

    ids: list[str] = []
    for key in ("id", "event_id", "message_id", "thread_id", "path", "full_ref"):
        val = data.get(key)
        if val is None:
            val = args.get(key)
        if val is not None and str(val).strip() != "":
            ids.append(f"{key}={val}")

    if tool.startswith("send_"):
        receipt_action = tool
    elif tool in {"image", "vision", "look", "research_report"}:
        receipt_action = tool
    elif tool == "browser":
        receipt_action = f"browser.{action or '?'}"
    else:
        receipt_action = f"{tool}.{action or '?'}"

    receipt: dict[str, Any] = {
        "action": receipt_action,
        "ok": True,
        "ids": ids,
        "tool": tool,
    }
    if tool == "send_email":
        receipt["to"] = str(args.get("to") or data.get("to") or "").strip()
        receipt["subject"] = str(args.get("subject") or "").strip()[:120]
    elif tool == "send_sms":
        receipt["to"] = str(args.get("to") or data.get("to") or "").strip()
    elif tool == "agenda":
        receipt["summary"] = str(args.get("summary") or data.get("summary") or "")[:120]
    elif tool == "tasks":
        receipt["title"] = str(args.get("title") or data.get("title") or "")[:120]
        gid = data.get("goal_id")
        if gid is None:
            gid = args.get("goal_id")
        if gid is not None and str(gid).strip() != "":
            receipt["goal_id"] = int(gid)
    elif tool == "goals":
        receipt["title"] = str(args.get("title") or data.get("title") or "")[:120]
        receipt["kind"] = str(data.get("kind") or args.get("kind") or "")[:40]
        receipt["status"] = str(data.get("status") or "")[:40]
    elif tool == "workspace":
        receipt["path"] = str(
            data.get("path") or args.get("path") or ""
        ).strip()[:200]
    elif tool == "memory":
        receipt["kind"] = str(data.get("kind") or action or "").strip()[:40]
    elif tool == "browser":
        receipt["url"] = str(data.get("url") or args.get("url") or "").strip()[:200]
        receipt["mode"] = str(data.get("mode") or "").strip()[:40]
    elif tool == "image":
        receipt["path"] = str(data.get("path") or "").strip()[:200]
    elif tool == "vision":
        receipt["path"] = str(
            data.get("path") or args.get("path") or ""
        ).strip()[:200]
        receipt["answer_len"] = data.get("answer_len")
        receipt["answer_hash"] = str(data.get("answer_hash") or "")[:16]
    elif tool == "look":
        receipt["path"] = str(
            data.get("path") or args.get("path") or ""
        ).strip()[:200]
        receipt["speech_act"] = str(data.get("speech_act") or "")[:40]
        receipt["channel"] = str(data.get("channel") or "")[:40]
        receipt["frame_sha256"] = str(data.get("frame_sha256") or "")[:16]
        receipt["deferral"] = str(data.get("deferral") or "")[:40]
        receipt["allow_count"] = data.get("allow_count", 1)
    elif tool == "research_report":
        receipt["path"] = str(data.get("path") or "").strip()[:200]
        receipt["ok_count"] = data.get("ok_count")
    elif tool == "contacts":
        receipt["who"] = str(args.get("who") or args.get("id") or "").strip()[:80]
    return receipt


def format_action_receipt(receipt: dict[str, Any]) -> str:
    """One-line Thinking / trace rendering."""
    action = receipt.get("action") or "?"
    ids = receipt.get("ids") or []
    id_part = f"  ids={','.join(ids)}" if ids else ""
    extra = ""
    for key in ("to", "subject", "summary", "title", "path", "url", "kind", "who"):
        val = str(receipt.get(key) or "").strip()
        if val:
            extra += f"  {key}={val}"
    return f"receipt  action={action}  ok={receipt.get('ok')}{id_part}{extra}"


def append_action_ledger(
    receipt: dict[str, Any],
    *,
    path: Path | None = None,
    session_id: str | None = None,
) -> None:
    """Append one receipt line to the action ledger (best-effort)."""
    out = path or DEFAULT_LEDGER_PATH
    row = {
        "ts": datetime.now(UTC).isoformat(),
        "session_id": session_id or "",
        **receipt,
    }
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        log.debug("action ledger write failed", exc_info=True)
