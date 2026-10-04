"""Plain first-run failure sentences. No Qt. No raw library text on the glass."""

from __future__ import annotations

import errno

import httpx

SUFFIX = "Nothing was lost."

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
        "Arelis could not download the setup files. Check that this PC is online, "
        "then try again. " + SUFFIX
    ),
    "disk": (
        "This PC ran out of free disk space during the download. Free some space, "
        "then try again. " + SUFFIX
    ),
    "installer": (
        "The engine installer did not finish. If its window is open, finish it "
        "there, then try again. " + SUFFIX
    ),
    "engine_start": (
        "The local engine would not start. Wait a few seconds and try again. "
        "If it keeps happening, restart your PC. " + SUFFIX
    ),
    "engine_missing": (
        "The local engine was not found after the install. Try again to install "
        "it again. If it keeps happening, restart your PC. " + SUFFIX
    ),
    "pull": (
        "The model download stopped. Check your internet connection and that "
        "the disk has enough free space, then try again. " + SUFFIX
    ),
    "unknown": "Setup hit a problem it did not expect. Try again. " + SUFFIX,
}

_DISK_PHRASES = ("no space left", "not enough space", "disk full")
_PULL_NETWORK_PHRASES = (
    "no such host",
    "dial tcp",
    "i/o timeout",
    "tls handshake timeout",
    "temporary failure in name resolution",
    "network is unreachable",
)
_ENGINE_MISSING = "Ollama is not installed on this PC yet."
_PULL_STAGES = (PULL_MODEL, PULL_RECALL)


def _kind(stage: str, problem: BaseException | str) -> str:
    text = str(problem).lower()
    if isinstance(problem, OSError) and (
        problem.errno == errno.ENOSPC or getattr(problem, "winerror", None) == 112
    ):
        return "disk"
    if any(phrase in text for phrase in _DISK_PHRASES):
        return "disk"
    if isinstance(problem, httpx.TransportError):
        if stage in _PULL_STAGES:
            return "engine_start"
        return "network"
    if isinstance(problem, httpx.HTTPStatusError) and stage == DOWNLOAD_ENGINE:
        return "network"
    if stage == INSTALL_ENGINE:
        return "installer"
    if stage == START_ENGINE:
        if str(problem) == _ENGINE_MISSING:
            return "engine_missing"
        return "engine_start"
    if stage in _PULL_STAGES:
        if any(phrase in text for phrase in _PULL_NETWORK_PHRASES):
            return "network"
        return "pull"
    return "unknown"


def plain_failure(stage: str, problem: BaseException | str) -> str:
    """One glass sentence. Never the raw library or installer string."""
    return PLAIN[_kind(stage, problem)]
