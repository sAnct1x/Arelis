"""Calendar tile host. ArelisWindow methods stay as delegates.

Google sync, task buttons, and scheduled jobs live here. The window
still owns the floating calendar chrome and the View checkbox.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.core.events import Event, EventType
from arelis.core.failure_copy import plain_reason


def calendar_service(window):
    from arelis.calendar.service import CalendarService

    return CalendarService(window.config)

def run_calendar(window, coro, *, ok_status: str = "google · just now") -> None:
    if getattr(window, "_disposed", False) or getattr(window, "_force_quit", False):
        coro.close()
        return
    if not window.loop.is_running():
        coro.close()
        return
    fut = asyncio.run_coroutine_threadsafe(coro, window.loop)

    def done() -> None:
        try:
            fut.result()
        except Exception as exc:
            from arelis.ui.dialog import notice

            window.calendar.set_status("sync failed", failed=True)
            notice(
                window,
                "calendar",
                "Google did not take that change.",
                detail=plain_reason(exc),
                warning=True,
            )
            return
        window.calendar.reload()
        window.calendar.set_status(ok_status)

    fut.add_done_callback(lambda _f: window._ui_call.emit(done))

def kick_calendar_sync(window) -> None:
    if window._force_quit or window._disposed:
        return
    if window.calendar_window.isHidden():
        return
    window.calendar.reload()
    if getattr(window, "_calendar_sync_inflight", False):
        return
    from arelis.calendar.secrets import load_calendar_secrets

    if not load_calendar_secrets().any_authorized():
        window.calendar.set_status("authorize google")
        return
    if not window.loop.is_running():
        return
    window._calendar_sync_inflight = True
    window.calendar.set_status("syncing…")
    window._calendar_sync_watchdog.start(int(window._calendar_sync_timeout_ms))
    fut = asyncio.run_coroutine_threadsafe(
        window._calendar_service().sync(), window.loop
    )

    def done() -> None:
        try:
            if getattr(window, "_disposed", False) or getattr(window, "_force_quit", False):
                return
            try:
                summary = fut.result()
            except Exception as exc:
                window.calendar.set_status("sync failed", failed=True)
                window._report_poll_state(
                    "calendar_tile", f"Calendar sync stopped: {plain_reason(exc)}"
                )
                return
            window._report_poll_state("calendar_tile", "")
            window.calendar.reload()
            if summary.get("ok"):
                names = [
                    name
                    for name, info in (summary.get("providers") or {}).items()
                    if info.get("ok")
                ]
                window.calendar.set_status(
                    f"{', '.join(names) or 'calendar'} · just now"
                )
            else:
                err = "; ".join(summary.get("errors") or []) or "sync failed"
                window.calendar.set_status("sync failed", failed=True)
                from arelis.ui.dialog import notice

                notice(
                    window,
                    "calendar",
                    "Could not refresh the calendar.",
                    detail=err,
                    warning=True,
                )
        finally:
            window._calendar_sync_inflight = False
            timer = getattr(window, "_calendar_sync_watchdog", None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass

    fut.add_done_callback(lambda _f: window._ui_call.emit(done))

def on_calendar_sync_watchdog(window) -> None:
    if window._force_quit or window._disposed:
        window._calendar_sync_inflight = False
        return
    if not getattr(window, "_calendar_sync_inflight", False):
        return
    window._calendar_sync_inflight = False
    window.calendar.set_status("sync failed", failed=True)

def on_calendar_create(window, payload: dict[str, Any]) -> None:
    window._run_calendar(
        window._calendar_service().create(
            summary=str(payload.get("summary") or ""),
            starts_at=payload["starts_at"],
            ends_at=payload.get("ends_at"),
            all_day=bool(payload.get("all_day")),
            location=str(payload.get("location") or ""),
            description=str(payload.get("description") or ""),
            provider=str(payload.get("provider") or "") or None,
            calendar_id=str(payload.get("calendar_id") or "") or None,
        ),
        ok_status="created",
    )

def on_calendar_update(window, payload: dict[str, Any]) -> None:
    event_id = str(payload.get("event_id") or "")
    if not event_id:
        return
    window._run_calendar(
        window._calendar_service().update(
            event_id,
            summary=str(payload.get("summary") or ""),
            starts_at=payload.get("starts_at"),
            ends_at=payload.get("ends_at"),
            all_day=bool(payload.get("all_day")),
            location=str(payload.get("location") or ""),
            description=str(payload.get("description") or ""),
            provider=str(payload.get("provider") or "") or None,
            calendar_id=str(payload.get("calendar_id") or "") or None,
        ),
        ok_status="updated",
    )

def on_calendar_delete(window, event_id: str) -> None:
    from arelis.ui.dialog import confirm

    if not confirm(
        window,
        "delete event",
        "Remove this from Google Calendar?",
        confirm_text="Delete",
        destructive=True,
    ):
        return
    ev = None
    try:
        ev = window._calendar_service().get(event_id)
    except Exception:
        ev = None
    window._run_calendar(
        window._calendar_service().delete(
            event_id,
            provider=ev.provider if ev else None,
            calendar_id=ev.calendar_id if ev else None,
        ),
        ok_status="deleted",
    )

def on_calendar_task_add(window, title: str, due: str) -> None:
    if window.store is None:
        return
    try:
        window.store.add_task(title, due=due or None, source="explicit")
    except Exception as exc:
        from arelis.ui.dialog import notice

        notice(window, "tasks", "Could not add that task.", detail=str(exc), warning=True)
        return
    from arelis.core.bus import emit_nowait

    emit_nowait(Event(EventType.TASKS_CHANGED, {"action": "add"}))
    window.calendar.reload_tasks()

def on_calendar_task_status(window, task_id: int, status: str) -> None:
    if window.store is None:
        return
    window.store.set_task_status(task_id, status)
    from arelis.core.bus import emit_nowait

    emit_nowait(Event(EventType.TASKS_CHANGED, {"action": status, "id": task_id}))
    window.calendar.reload_tasks()

def on_calendar_task_remove(window, task_id: int) -> None:
    from arelis.ui.dialog import confirm

    if window.store is None:
        return
    existing = window.store.get_task(task_id)
    label = str((existing or {}).get("title") or "this task")
    if not confirm(
        window,
        "remove task",
        f"Remove {label}?",
        confirm_text="Remove",
        destructive=True,
    ):
        return
    window.store.remove_task(task_id)
    from arelis.core.bus import emit_nowait

    emit_nowait(Event(EventType.TASKS_CHANGED, {"action": "remove", "id": task_id}))
    window.calendar.reload_tasks()

def reveal_calendar_jobs(window) -> None:
    window.act_calendar.setChecked(True)
    window._toggle_calendar(True)
    window.calendar.show_jobs_tab()
    window.calendar.reload_jobs()

def on_calendar_job_save(window, payload: dict[str, Any]) -> None:
    from arelis.tools.schedule_jobs import save_job_from_payload
    from arelis.ui.dialog import notice

    result = save_job_from_payload(payload)
    if not result.ok:
        notice(
            window,
            "jobs",
            "Could not save that job.",
            detail=str(result.output),
            warning=True,
        )
        return
    job_id = str((result.data or {}).get("id") or "")
    window.calendar.reload_jobs(select_id=job_id)
    if result.data and result.data.get("registered") is False:
        notice(
            window,
            "jobs",
            "Saved, but Windows would not register it.",
            detail=str(result.output),
            warning=True,
        )

def on_calendar_job_delete(window, job_id: str) -> None:
    from arelis.jobs.store import get_job
    from arelis.tools.schedule_jobs import ScheduleTool
    from arelis.ui.dialog import confirm, notice

    job = get_job(job_id)
    label = job.name if job else job_id
    if not confirm(
        window,
        "delete job",
        f"Stop {label} and remove it from Windows?",
        confirm_text="Delete",
        destructive=True,
    ):
        return
    result = ScheduleTool()._delete(job_id)
    if not result.ok:
        notice(
            window,
            "jobs",
            "Could not delete that job.",
            detail=str(result.output),
            warning=True,
        )
        return
    window.calendar.reload_jobs()

def on_calendar_job_run(window, job_id: str) -> None:
    from arelis.tools.schedule_jobs import ScheduleTool
    from arelis.ui.dialog import notice

    result = ScheduleTool()._run_now(job_id)
    if not result.ok:
        notice(
            window,
            "jobs",
            "Could not start that job.",
            detail=str(result.output),
            warning=True,
        )
        return
    window.calendar.jobs_page.set_note("Started. The result will arrive by email.")

def on_calendar_window_closed(window) -> None:
    window.act_calendar.setChecked(False)
