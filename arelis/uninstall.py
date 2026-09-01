"""What a full uninstall must take with it.

The installer already deletes ``%LOCALAPPDATA%\\Programs\\Arelis`` and
deregisters scheduled tasks. Conversations, secrets, models, her Chrome
profile, and the optional Ollama setup we downloaded live *beside* the
program. Those stay unless the person asks — a reinstall should find
them. This module is that ask.

Never touches a source checkout. Never touches a system Ollama install
or ``%USERPROFILE%\\.ollama``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from arelis.paths import APP_NAME, default_workspace_root, is_source_checkout, user_data_dir


def _localappdata() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    return Path(local) if local else Path.home() / "AppData" / "Local"


def runtime_dir() -> Path:
    """Where setup parked a downloaded Ollama installer. Same as ``setup.engine``."""
    return _localappdata() / "Arelis-runtime"


def looks_like_source_tree(path: Path) -> bool:
    """The two markers ``is_source_checkout`` uses, pointed at a folder we might delete.

    ``Documents\\Arelis`` is the default workspace for an installed copy. It is
    also where a lot of people clone this repository. The running interpreter
    is the published one, so ``is_source_checkout()`` is false — and rmtree
    would erase the checkout. Refuse any target that looks like one.
    """
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    return (resolved / "pyproject.toml").is_file() and (resolved / "tests").is_dir()


def residue_dirs() -> list[Path]:
    """Published leftovers a wipe should remove. Empty on a checkout."""
    if is_source_checkout():
        return []
    seen: set[Path] = set()
    out: list[Path] = []
    local = _localappdata()
    for path in (
        user_data_dir(),
        local / APP_NAME,
        runtime_dir(),
        local / "Arelis-dev",
        default_workspace_root(),
    ):
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        if looks_like_source_tree(resolved):
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _remove_tree(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return True
        shutil.rmtree(path)
        return True
    except OSError:
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()


def purge_user_state() -> list[str]:
    """Remove scheduled tasks, then the published data dirs. Never raises."""
    gone: list[str] = []
    try:
        from arelis.jobs.schedule import remove_all_tasks

        for name in remove_all_tasks():
            gone.append(f"task:{name}")
    except Exception:
        pass
    if is_source_checkout():
        return gone
    for path in residue_dirs():
        try:
            if not path.exists():
                continue
            if _remove_tree(path):
                gone.append(str(path))
        except OSError:
            pass
    return gone
