"""Send application logs somewhere a desktop session can find them.

Without this, log.exception in the orchestrator and the bus vanishes into a
pythonw process with no console. Scheduled jobs already write to logs/jobs.log;
this is the matching sink for the interactive app and the CLI.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from arelis.config import PROJECT_ROOT

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
        directory = log_dir if log_dir is not None else PROJECT_ROOT / "logs"
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

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    _configured = True
