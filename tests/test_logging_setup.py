"""The interactive app needs a durable log; without it, turn failures vanish."""

from __future__ import annotations

import logging
from pathlib import Path

import arelis.logging_setup as logging_setup


def test_a_turn_failure_lands_in_the_rotating_log(tmp_path: Path, monkeypatch) -> None:
    """log.exception from the orchestrator has to reach a file, not pythonw's void."""
    monkeypatch.setattr(logging_setup, "_configured", False)
    # No console noise in pytest; the file is the contract under test.
    monkeypatch.setattr(logging_setup.sys.stderr, "isatty", lambda: False)

    logging_setup.configure_logging(tmp_path)
    logging.getLogger("arelis.core.orchestrator").exception("Turn failed")

    text = (tmp_path / "arelis.log").read_text(encoding="utf-8")
    assert "Turn failed" in text
    assert "arelis.core.orchestrator" in text


def test_configure_logging_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    """A second call must not stack another handler and double every line."""
    monkeypatch.setattr(logging_setup, "_configured", False)
    monkeypatch.setattr(logging_setup.sys.stderr, "isatty", lambda: False)

    logging_setup.configure_logging(tmp_path)
    before = len(logging.getLogger().handlers)
    logging_setup.configure_logging(tmp_path)
    assert len(logging.getLogger().handlers) == before
