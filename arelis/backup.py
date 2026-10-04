"""Pre-upgrade copy of a few records. Never copies secrets.

Dated ``memory.db`` snapshots in ``arelis.memory.backup`` are a different
thing, and they stay off. This writes ``backups/pre-<version>/`` with an
allowlist: a new file under the records folder is excluded until someone
names it here. ``secrets.yaml`` is refused even then.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from arelis.memory.backup import _sqlite_copy
from arelis.paths import state_dir

log = logging.getLogger(__name__)

# Basenames under state_dir(). New secret-shaped files stay out by default.
PRE_UPGRADE_ALLOWLIST: tuple[str, ...] = (
    "memory.db",
    "rooms.yaml",
    "jobs.yaml",
    "config.local.yaml",
    "contacts.yaml",
    "profile.yaml",
    "lessons.yaml",
)

PRE_UPGRADE_KEEP = 2
_SECRETS_NAME = "secrets.yaml"
_UNSAFE_FOLDER = re.compile(r"[^\w.\-]+", re.ASCII)


class _BackupRefusedError(ValueError):
    """A name this backup is forbidden to copy."""


def backup_before_upgrade(from_version: str, to_version: str | None = None) -> Path | None:
    """Copy allowlisted files to ``backups/pre-<from_version>/``.

    Never raises. A failure is a log line and ``None`` so an in-app update
    still starts the installer. Keeps the newest ``PRE_UPGRADE_KEEP`` ``pre-*``
    folders and only deletes inside ``state_dir()/backups``.
    """
    try:
        return _backup_before_upgrade(from_version, to_version)
    except Exception:
        log.warning("pre-upgrade backup failed; the update will continue")
        return None


def _backup_before_upgrade(from_version: str, to_version: str | None) -> Path:
    root = state_dir()
    backups = root / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    if not _is_inside(backups, root):
        raise RuntimeError("pre-upgrade backup destination left the records folder")

    folder_name = _safe_pre_folder_name(from_version)
    dest = backups / folder_name
    dest.mkdir(parents=True, exist_ok=True)
    if not _is_strictly_inside(dest, backups):
        raise RuntimeError("pre-upgrade backup destination left the backups folder")

    for name in PRE_UPGRADE_ALLOWLIST:
        try:
            _copy_allowlisted(name, dest, root)
        except _BackupRefusedError:
            log.error("pre-upgrade backup refused to copy secrets.yaml")
        except Exception:
            log.warning("pre-upgrade backup skipped a file; the update will continue")

    _prune_pre_upgrade_folders(backups, keep=PRE_UPGRADE_KEEP)

    extra = f" toward {to_version}" if to_version else ""
    log.info(
        "pre-upgrade backup saved %s%s; passwords and tokens were not copied",
        folder_name,
        extra,
    )
    return dest


def _copy_allowlisted(name: str, dest_dir: Path, root: Path) -> None:
    _refuse_secrets_name(name)
    src = _source_path(name, root)
    if src is None or not src.exists():
        return
    if src.is_dir():
        return
    _refuse_secrets_name(src.name)
    resolved = src.resolve()
    _refuse_secrets_name(resolved.name)
    if not _is_inside(resolved, root):
        log.warning("pre-upgrade backup skipped a file that is not in the records folder")
        return

    target = dest_dir / src.name
    _refuse_secrets_name(target.name)
    if not _is_inside(target, dest_dir):
        return
    if name == "memory.db":
        _sqlite_copy(resolved, target)
        return
    shutil.copy2(resolved, target)


def _source_path(name: str, root: Path) -> Path | None:
    if name == "profile.yaml":
        try:
            from arelis.profile import resolve_profile_path

            path = resolve_profile_path()
        except Exception:
            # optional, absence is normal
            path = root / name
        if not _is_inside(path, root):
            return None
        return path
    return root / name


def _refuse_secrets_name(name: str) -> None:
    if Path(name).name.lower() == _SECRETS_NAME:
        raise _BackupRefusedError("secrets.yaml is never copied")


def _safe_pre_folder_name(version: str) -> str:
    cleaned = _UNSAFE_FOLDER.sub("_", str(version).strip()).strip("._") or "unknown"
    return f"pre-{cleaned}"


def _prune_pre_upgrade_folders(backups: Path, *, keep: int) -> None:
    if not backups.is_dir():
        return
    if not _is_inside(backups, state_dir()):
        return
    folders = [
        path
        for path in backups.iterdir()
        if path.name.startswith("pre-") and (path.is_dir() or path.is_symlink())
    ]
    folders.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    for stale in folders[max(0, int(keep)) :]:
        _delete_inside_backups(stale, backups)


def _delete_inside_backups(path: Path, backups: Path) -> None:
    if not _is_strictly_inside(path, backups):
        log.warning("pre-upgrade backup would not delete a folder outside backups")
        return
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            return
        if path.is_dir():
            shutil.rmtree(path)
    except OSError:
        log.warning("pre-upgrade backup could not remove an old copy")


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError, RuntimeError):
        return False


def _is_strictly_inside(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except (OSError, RuntimeError):
        return False
    return resolved != root_resolved and resolved.is_relative_to(root_resolved)
