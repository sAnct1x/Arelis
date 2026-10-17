"""Strict path resolution for Sentinel.

All runtime data, logs, quarantine vaults, and harvested outputs stay inside
the Arelis_Sentinel root. Sentinel never writes to external directories.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
_RUNTIME_ROOT: Path | None = None


def set_runtime_root(path: Path | None) -> None:
    """Override the runtime root directory (used by pytest to isolate test artifacts)."""
    global _RUNTIME_ROOT
    _RUNTIME_ROOT = path


def _active_root() -> Path:
    return _RUNTIME_ROOT if _RUNTIME_ROOT is not None else REPO_ROOT


def ensure(path: Path) -> Path:
    """Create directory (or parent directory for a file path) if missing."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def repo_root() -> Path:
    return REPO_ROOT


def data_dir() -> Path:
    return ensure(_active_root() / "data")


def logs_dir() -> Path:
    return ensure(_active_root() / "logs")


def outputs_dir() -> Path:
    return ensure(_active_root() / "outputs")


def harvest_dir() -> Path:
    return ensure(outputs_dir() / "harvest")


def quarantine_dir() -> Path:
    return ensure(data_dir() / "quarantine")


def ledger_path() -> Path:
    ensure(data_dir())
    return data_dir() / "sentinel_ledger.jsonl"


def token_path() -> Path:
    ensure(data_dir())
    return data_dir() / "session_token"


def banned_peers_path() -> Path:
    ensure(data_dir())
    return data_dir() / "banned_peers.json"


def immunized_hashes_path() -> Path:
    ensure(data_dir())
    return data_dir() / "immunized_hashes.json"


def overseer_static_dir() -> Path:
    return PACKAGE_ROOT / "ui" / "overseer"

