"""Send application logs somewhere a desktop session can find them.

Without this, log.exception in the orchestrator and the bus vanishes into a
pythonw process with no console. Scheduled jobs already write to logs/jobs.log;
this is the matching sink for the interactive app and the CLI.
"""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

from arelis.paths import logs_dir

# Once per process. main() is the only caller in production; tests reset this
# when they need to point the file at a temporary directory.
_configured = False


def configure_logging(log_dir: Path | None = None) -> None:
    """Attach a rotating file handler to the root logger.

    Console only when stderr is a real tty: pythonw accepts writes on a non-tty
    stderr that go nowhere, and is cp1252, so a curly quote in a log line would
    fail mid-write. The file is UTF-8 and is the record that survives a
    force-quit.

    Scheduled runs call their own configure_logging in jobs/runner.py afterward,
    with force=True, so they keep writing to logs/jobs.log rather than here.
    """
    global _configured
    if _configured:
        return

    handlers: list[logging.Handler] = []
    try:
        directory = log_dir if log_dir is not None else logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                directory / "arelis.log",
                maxBytes=2 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except OSError:
        # A read-only install should still start; it just has nowhere durable
        # to leave a traceback.
        pass
    try:
        if sys.stderr is not None and sys.stderr.isatty():
            handlers.append(logging.StreamHandler(sys.stderr))
    except (AttributeError, ValueError, OSError):
        pass

    if not handlers:
        return

    from arelis.location.privacy import LocationLogFilter

    for handler in handlers:
        handler.addFilter(LocationLogFilter())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    _configured = True


def flush_logs() -> None:
    """Push handler buffers to disk so the last lines survive quit."""
    seen: set[int] = set()
    manager = logging.Logger.manager
    loggers: list[logging.Logger] = [logging.getLogger()]
    for name in list(getattr(manager, "loggerDict", {})):
        logger = manager.loggerDict[name]
        if isinstance(logger, logging.Logger):
            loggers.append(logger)
    for logger in loggers:
        for handler in logger.handlers:
            key = id(handler)
            if key in seen:
                continue
            seen.add(key)
            try:
                handler.flush()
            except Exception:
                pass


def install_unhandled_hook() -> None:
    """Send uncaught exceptions to the log file.

    pythonw has no console. sys.excepthook writes to stderr, which goes
    nowhere, so a crash at launch looks like the process just vanished.
    """

    def _hook(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        log = logging.getLogger("arelis")
        if tb is None:
            tb = getattr(exc, "__traceback__", None)
        if tb is not None:
            log.critical("unhandled exception", exc_info=(exc_type, exc, tb))
        else:
            # Qt/Shiboken can raise from C with no traceback object. The
            # Python frames still on the stack are the only record of the line.
            frames = "".join(traceback.format_stack()[:-1]).rstrip("\n")
            detail = "".join(traceback.format_exception_only(exc)).rstrip("\n")
            log.critical(
                "unhandled exception\nTraceback (most recent call last):\n%s\n%s",
                frames,
                detail,
            )
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
