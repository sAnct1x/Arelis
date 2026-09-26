"""Tear down live-board leftovers. A token is a test, not a life."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from arelis.calendar.models import CachedEvent
from arelis.calendar.store import CalendarStore
from arelis.memory import MemoryStore
from arelis.paths import outputs_dir

_TOKEN_MARKS = ("f50-", "brd-", "lb-")
_BOARD_PHRASES = (
    "arelis stay",
    "arelis live-board",
    "live-board keep",
    "coverage pass",
    "coverage board",
)


def _is_board_junk(text: str, token: str = "") -> bool:
    blob = (text or "").casefold()
    if token and token.casefold() in blob:
        return True
    if any(mark in blob for mark in _TOKEN_MARKS):
        return True
    return any(phrase in blob for phrase in _BOARD_PHRASES)


def cleanup_board_token(
    token: str = "",
    *,
    calendar: CalendarStore | None = None,
    memory: MemoryStore | None = None,
    files_root: Path | None = None,
) -> dict[str, int]:
    """Delete calendar / tasks / goals / files this board token created."""
    counts = {"events": 0, "tasks": 0, "goals": 0, "facts": 0, "files": 0}
    counts["events"] = _drop_events(token, calendar)
    mem = memory or MemoryStore()
    counts["tasks"], counts["goals"], counts["facts"] = _drop_memory(token, mem)
    counts["files"] = _drop_files(token, files_root)
    return counts


def _file_roots(files_root: Path | None) -> list[Path]:
    if files_root is not None:
        return [files_root]
    root = outputs_dir()
    return [root / "live_fifty", root / "documents"]


def _drop_events(token: str, store: CalendarStore | None) -> int:
    today = date.today()
    start, end = today - timedelta(days=14), today + timedelta(days=60)
    if store is not None:
        return _drop_cached_events(token, store, start, end)
    from arelis.calendar.service import CalendarService

    svc = CalendarService()
    events = [
        ev
        for ev in svc.list_range(start, end)
        if _is_board_junk(f"{ev.summary or ''} {ev.description or ''}", token)
    ]
    if not events:
        return 0
    return _run_async(_delete_remote(svc, events))


def _drop_cached_events(
    token: str, store: CalendarStore, start: date, end: date
) -> int:
    n = 0
    for ev in store.list_range(start, end):
        title = f"{ev.summary or ''} {ev.description or ''}"
        if not _is_board_junk(title, token):
            continue
        store.delete_id(ev.id)
        n += 1
    return n


def _run_async(coro: Any) -> int:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return int(asyncio.run(coro))
    raise RuntimeError("board cleanup cannot run inside an event loop")


async def _delete_remote(svc: Any, events: list[CachedEvent]) -> int:
    n = 0
    for ev in events:
        try:
            await svc.delete(
                ev.id, provider=ev.provider, calendar_id=ev.calendar_id
            )
            n += 1
        except Exception:
            store, owns = svc._open_store()
            try:
                store.delete_id(ev.id)
            finally:
                if owns:
                    store.close()
    return n


def _drop_memory(token: str, store: MemoryStore) -> tuple[int, int, int]:
    tasks = 0
    for row in store.list_tasks(status=None, limit=500):
        if not _is_board_junk(str(row.get("title") or ""), token):
            continue
        if store.remove_task(int(row["id"])):
            tasks += 1
    goals = 0
    for row in store.list_goals(status=None, limit=200):
        if str(row.get("status") or "") == "dropped":
            continue
        if not _is_board_junk(str(row.get("title") or ""), token):
            continue
        if store.set_goal_status(int(row["id"]), "dropped"):
            goals += 1
    facts = 0
    if token:
        facts += int(store.forget_fact(token) or 0)
    facts += int(store.forget_fact("persimmon") or 0)
    return tasks, goals, facts


def _drop_files(token: str, files_root: Path | None) -> int:
    n = 0
    marks = [token.lower(), *_TOKEN_MARKS] if token else list(_TOKEN_MARKS)
    for root in _file_roots(files_root):
        if not root.is_dir():
            continue
        for path in root.iterdir():
            name = path.name.lower()
            if path.suffix.lower() not in {".md", ".csv", ".py", ".pdf"}:
                continue
            if name in {"report.md"}:
                continue
            if not any(m and m in name for m in marks):
                continue
            try:
                path.unlink()
                n += 1
            except OSError:
                pass
    return n


def format_cleanup(counts: dict[str, Any]) -> str:
    bits = [f"{k}={v}" for k, v in counts.items() if v]
    return "cleaned " + (", ".join(bits) if bits else "nothing")
