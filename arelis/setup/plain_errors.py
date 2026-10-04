"""Plain first-run failure sentences. No Qt. No raw library text on the glass."""

from __future__ import annotations

import errno

import httpx

SUFFIX = "Your files are fine. Try again."

DOWNLOAD_ENGINE = "download_engine"
INSTALL_ENGINE = "install_engine"
START_ENGINE = "start_engine"
PULL_MODEL = "pull_model"
PULL_RECALL = "pull_recall"
UNEXPECTED = "unexpected"
STAGES = (
    DOWNLOAD_ENGINE,
    INSTALL_ENGINE,
    START_ENGINE,
    PULL_MODEL,
    PULL_RECALL,
    UNEXPECTED,
)

PLAIN: dict[str, str] = {
    "network": (
        "Arelis could not download the setup files. Check that this PC is online. "
        + SUFFIX
    ),
    "disk": (
        "This PC ran out of free disk space during the download. Free some space. "
        + SUFFIX
    ),
    "installer": (
        "The engine installer did not finish. If its window is open, finish it there. "
        + SUFFIX
    ),
    "engine_start": (
        "The local engine would not start. Give it a moment. " + SUFFIX
    ),
    "pull": (
        "The model download was refused or stopped. It may be unavailable right now. "
        + SUFFIX
    ),
    "unknown": "Setup hit a problem it did not expect. " + SUFFIX,
}

_DISK_PHRASES = ("no space left", "not enough space", "disk full")


def _kind(stage: str, problem: BaseException | str) -> str:
    text = str(problem).lower()
    if isinstance(problem, OSError) and (
        problem.errno == errno.ENOSPC or getattr(problem, "winerror", None) == 112
    ):
        return "disk"
    if any(phrase in text for phrase in _DISK_PHRASES):
        return "disk"
    if isinstance(problem, httpx.TransportError):
        return "network"
    if isinstance(problem, httpx.HTTPStatusError) and stage == DOWNLOAD_ENGINE:
        return "network"
    if stage == INSTALL_ENGINE:
        return "installer"
    if stage == START_ENGINE:
        return "engine_start"
    if stage in (PULL_MODEL, PULL_RECALL):
        return "pull"
    return "unknown"


def plain_failure(stage: str, problem: BaseException | str) -> str:
    """One glass sentence. Never the raw library or installer string."""
    return PLAIN[_kind(stage, problem)]
