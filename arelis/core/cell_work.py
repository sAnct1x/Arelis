"""Per-turn folder for python-cell writes. Not the user's documents drop tray.

There was no existing per-turn work dir: C19's ``work/mini.csv`` is a drop-tray
basename the #327 resolver already maps onto ``outputs/documents``. The cell
runs with cwd ``outputs/work/<turn id>/``. plot/analyze look here first, then
fall back to that documents resolver.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from arelis.paths import ensure, outputs_dir
from arelis.workspace import is_unsafe_windows_path

_TURN_ID_MAX = 32


@dataclass
class _TurnState:
    turn_id: str


_STATES: dict[str, _TurnState] = {}


def _data_key() -> str:
    try:
        return str(outputs_dir().resolve())
    except OSError:
        return ""


def _safe_id(raw: str) -> str:
    text = "".join(ch for ch in (raw or "") if ch.isalnum() or ch in "-_")[:_TURN_ID_MAX]
    return text or uuid4().hex[:8]


def _drive_path(raw: str) -> bool:
    return len(raw) >= 2 and raw[1] == ":"


def begin_cell_work(turn_id: str = "") -> None:
    """Start a new turn's work folder id. Directory is created on first use."""
    _STATES[_data_key()] = _TurnState(turn_id=_safe_id(turn_id))


def cell_work_dir() -> Path:
    """``outputs/work/<turn id>/``, created if needed."""
    key = _data_key()
    state = _STATES.get(key)
    if state is None:
        begin_cell_work()
        state = _STATES[key]
    return ensure(outputs_dir() / "work" / state.turn_id)


def current_cell_work_dir() -> Path | None:
    """This turn's work folder when it already exists, else None."""
    state = _STATES.get(_data_key())
    if state is None:
        return None
    path = outputs_dir() / "work" / state.turn_id
    return path if path.is_dir() else None


def resolve_cell_work_file(
    path_str: str = "",
    *,
    suffixes: frozenset[str] | set[str] | None = None,
) -> str:
    """Bare name (or ``work/<name>``) inside this turn's work folder.

    Falls through as empty so callers can use the #327 documents resolver.
    """
    folder = current_cell_work_dir()
    if folder is None:
        return ""
    wanted = {s.lower() for s in (suffixes or ())}
    raw = (path_str or "").strip()
    if not raw or is_unsafe_windows_path(raw):
        return ""
    if Path(raw).is_absolute() or _drive_path(raw):
        return ""
    parts = [part for part in raw.replace("\\", "/").split("/") if part and part != "."]
    if not parts or ".." in parts:
        return ""
    candidates: list[list[str]] = [parts]
    if parts[0].lower() == "work" and len(parts) > 1:
        candidates.append(parts[1:])
    if len(parts) > 1:
        candidates.append([parts[-1]])
    try:
        folder_real = Path(os.path.realpath(folder))
    except OSError:
        return ""
    for rel in candidates:
        hit = _file_inside(folder_real, rel, wanted)
        if hit is not None:
            return str(hit)
    return ""


def _file_inside(folder_real: Path, rel: list[str], wanted: set[str]) -> Path | None:
    if not rel:
        return None
    try:
        file_real = Path(os.path.realpath(folder_real.joinpath(*rel)))
        file_real.relative_to(folder_real)
    except (OSError, ValueError):
        return None
    if not file_real.is_file():
        return None
    if wanted and file_real.suffix.lower() not in wanted:
        return None
    return file_real
