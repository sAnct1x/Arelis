"""Run one saved job with nobody watching, and mail the answer.

The security posture here is the whole point. A turn that runs at 7am has no
one to read a confirm card. The CLI also denies confirms when stdin is not a
terminal (unless `--allow-write`); this runner goes further: everything that
would ask is answered skip, send_email/browser/archive are never registered,
and the mail is sent by this module after the turn is over, to an address that
was fixed when the job was created.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from typing import Any

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.jobs.store import Job, get_job, record_run
from arelis.mail import Mailer, load_account
from arelis.paths import logs_dir
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

# Generous. A research turn that searches and scrapes several pages on a cold
# model can genuinely take minutes, and a digest arriving late beats one that
# was killed halfway through.
TURN_TIMEOUT_S = 900.0


class _Collector:
    """Watches the bus for one turn and refuses everything that asks."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.done = asyncio.Event()
        self.answer = ""
        self.error = ""
        self.refused: list[str] = []
        bus.subscribe(None, self.on_event)

    async def on_event(self, event: Event) -> None:
        payload = event.payload
        if event.type == EventType.TOOL_CONFIRM:
            summary = str(payload.get("summary") or "")
            self.refused.append(summary)
            await self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {"id": payload.get("id"), "decision": "skip", "allow_turn": False},
                )
            )
        elif event.type == EventType.ASSISTANT_DONE:
            self.answer = str(payload.get("text") or "")
            self.done.set()
        elif event.type == EventType.ERROR:
            self.error = str(payload.get("message") or "unknown error")
            self.done.set()


async def run_job_async(job: Job, config: dict[str, Any] | None = None) -> int:
    config = config or load_config()
    workspace = WorkspaceRoots.from_config(config)
    config["_workspace"] = workspace

    account = load_account()
    if account is None:
        log.error("Job %s cannot run: email is not configured", job.id)
        record_run(job.id, "no email configured")
        return 2

    email_cfg = (config.get("tools") or {}).get("email") or {}
    mailer = Mailer(
        account,
        host=email_cfg.get("smtp_host", "smtp.gmail.com"),
        port=int(email_cfg.get("smtp_port", 587)),
        from_name=email_cfg.get("from_name", "Arelis"),
        timeout_s=float(email_cfg.get("timeout_s", 30)),
    )
    to = account.recipient(job.recipient)
    stamp = datetime.now().strftime("%a %d %b")

    from arelis.briefing.builder import build_briefing, is_briefing_job

    # Briefings are a fixed template. Running them through the model would add
    # latency and inventing; the builder already has mail, weather, and facts.
    if is_briefing_job(job):
        status = "ok"
        try:
            body = await build_briefing(config)
            subject = f"{job.name} — {stamp}"
        except Exception as exc:
            log.exception("Briefing job %s failed while building", job.id)
            status = f"failed: {exc}"[:120]
            subject = f"{job.name} failed — {stamp}"
            body = (
                f"The scheduled briefing **{job.name}** did not finish.\n\n{exc}"
            )
        return await _mail_and_finish(job, mailer, to, subject, body, status)

    from arelis.core.seat import build_seat

    # allow_send=False (and attended=False with it) is the load-bearing line.
    # Fresh memory, no sink: the job neither sees chat nor leaves anything in it.
    seat = build_seat(config, profile="job")
    bus = seat.bus
    router = seat.router
    collector = _Collector(bus)

    bus_task = asyncio.create_task(bus.run())
    status = "ok"
    try:
        await bus.publish(
            Event(EventType.USER_MESSAGE, {"text": job.prompt, "role": job.role})
        )
        try:
            await asyncio.wait_for(collector.done.wait(), timeout=TURN_TIMEOUT_S)
        except TimeoutError:
            collector.error = f"The turn ran longer than {int(TURN_TIMEOUT_S)}s and was stopped."
    finally:
        bus.stop()
        bus_task.cancel()
        await router.close()

    if collector.error:
        status = f"failed: {collector.error[:120]}"
        subject = f"{job.name} failed — {stamp}"
        body = (
            f"The scheduled job **{job.name}** did not finish.\n\n"
            f"{collector.error}\n\n"
            f"Prompt: {job.prompt}"
        )
    else:
        subject = f"{job.name} — {stamp}"
        body = collector.answer or "The turn produced no answer."
        if collector.refused:
            # Say so rather than silently dropping it. A job that keeps trying
            # to write a file is a job whose prompt needs changing.
            skipped = "\n".join(f"- {s}" for s in collector.refused)
            body += (
                "\n\n---\n\nScheduled runs cannot write files, generate images, "
                f"or send mail themselves, so these were skipped:\n\n{skipped}"
            )

    return await _mail_and_finish(job, mailer, to, subject, body, status)


async def _mail_and_finish(
    job: Job,
    mailer: Mailer,
    to: str,
    subject: str,
    body: str,
    status: str,
) -> int:
    try:
        await mailer.send_async(to=to, subject=subject, body=body)
        log.info("Job %s mailed %d chars to %s", job.id, len(body), to)
    except Exception as exc:
        # Nothing above this can reach the user, so the log is the only record.
        log.exception("Job %s could not be mailed", job.id)
        record_run(job.id, f"send failed: {exc}")
        return 1

    record_run(job.id, status)
    if job.one_off:
        _retire(job)
    return 0 if status == "ok" else 1


def _retire(job: Job) -> None:
    """Clear a one-off away once it has fired.

    Task Scheduler drops its own task via DeleteExpiredTaskAfter, but only the
    store knows the job existed, and a list full of spent reminders is the
    thing that makes someone stop reading the list.
    """
    from arelis.jobs import schedule as win
    from arelis.jobs.store import delete_job

    try:
        win.unregister(job.id)
    except win.ScheduleError as exc:
        log.warning("Job %s ran but its task could not be removed: %s", job.id, exc)
    delete_job(job.id)
    log.info("Job %s was a one-off and has been retired", job.id)


def configure_logging() -> None:
    """Scheduled runs have nowhere to print, so they log to a file.

    Task Scheduler starts pythonw with no console attached. Its stderr accepts
    writes but they go nowhere, and it is cp1252, so a log line quoting an email
    subject with a curly quote in it would fail mid-write. logs/jobs.log is
    therefore the only record of why a run at 7am did not produce an email.

    The console handler is added only for a real terminal, which is the case
    when you run --run-job by hand and want to watch it.
    """
    handlers: list[logging.Handler] = []
    try:
        from logging.handlers import RotatingFileHandler

        log_dir = logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_dir / "jobs.log",
                maxBytes=2 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
        )
    except OSError:
        pass
    try:
        if sys.stderr is not None and sys.stderr.isatty():
            handlers.append(logging.StreamHandler(sys.stderr))
    except (AttributeError, ValueError, OSError):
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def run_job(job_id: str, config: dict[str, Any] | None = None) -> int:
    """Entry point for `arelis --run-job ID`."""
    configure_logging()
    job = get_job(job_id)
    if job is None:
        log.error("No job with id %r. See data/jobs.yaml.", job_id)
        return 2
    if not job.enabled:
        log.info("Job %s is disabled; nothing to do", job.id)
        return 0
    log.info("Job %s starting: %s", job.id, job.name)
    code = asyncio.run(run_job_async(job, config))
    log.info("Job %s finished with exit code %d", job.id, code)
    return code
