"""Pre-upgrade copy of a few records. Never copies secrets.

Dated ``memory.db`` snapshots in ``arelis.memory.backup`` are a different
thing, and they stay off. This writes ``pre-<version>/`` under a folder
next to the user data root (outside the uninstall wipe tree) with an
allowlist: a new file under the records folder is excluded until someone
names it here. ``secrets.yaml`` is refused even then.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

from arelis.memory.backup import _sqlite_copy
from arelis.paths import pre_upgrade_backups_dir, state_dir, user_data_dir

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
    """Copy allowlisted files to ``pre-<from_version>/`` outside the wipe tree.

    Never raises. A failure is a log line and ``None`` so the caller can stop
    the upgrade. Keeps the newest ``PRE_UPGRADE_KEEP`` ``pre-*`` folders and
    only deletes inside the dedicated backups folder. Writes into a temporary
    folder and renames it only when the copy is finished. A failed copy removes
    its ``.partial`` folder right away.
    """
    try:
        return _backup_before_upgrade(from_version, to_version)
    except Exception:
        log.warning("pre-upgrade backup failed; the update will not continue")
        return None


def _backup_before_upgrade(from_version: str, to_version: str | None) -> Path:
    root = state_dir()
    backups = pre_upgrade_backups_dir()
    backups.mkdir(parents=True, exist_ok=True)
    _require_outside_wipe_tree(backups)
    _prune_stale_partial_folders(backups)

    folder_name = _safe_pre_folder_name(from_version)
    dest = backups / folder_name
    partial = backups / f".{folder_name}.{uuid.uuid4().hex}.partial"
    partial.mkdir(parents=True, exist_ok=False)
    if not _is_strictly_inside(partial, backups):
        raise RuntimeError("pre-upgrade backup destination left the backups folder")

    renamed = False
    try:
        for name in PRE_UPGRADE_ALLOWLIST:
            try:
                _copy_allowlisted(name, partial, root)
            except _BackupRefusedError:
                log.error("pre-upgrade backup refused to copy secrets.yaml")

        if dest.exists() or dest.is_symlink():
            _delete_inside_backups(dest, backups)
        os.replace(partial, dest)
        renamed = True
    finally:
        if not renamed and (partial.exists() or partial.is_symlink()):
            _delete_inside_backups(partial, backups)

    if not _is_strictly_inside(dest, backups):
        raise RuntimeError("pre-upgrade backup destination left the backups folder")

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
    if src is None:
        return
    try:
        info = src.lstat()
    except OSError:
        return
    if stat.S_ISLNK(info.st_mode):
        log.debug("pre-upgrade backup skipped a linked file")
        return
    if stat.S_ISDIR(info.st_mode):
        return
    _refuse_secrets_name(src.name)
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        log.debug("pre-upgrade backup skipped a linked file")
        return
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
        tmp_target = dest_dir / f".{src.name}.{uuid.uuid4().hex}.partial"
        _refuse_secrets_name(tmp_target.name)
        if not _is_inside(tmp_target, dest_dir):
            return
        _sqlite_copy(resolved, tmp_target)
        os.replace(tmp_target, target)
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


def _is_partial_backup(path: Path) -> bool:
    name = path.name
    if not (name.startswith(".") or name.endswith(".partial")):
        return False
    return path.is_dir() or path.is_symlink()


def _require_outside_wipe_tree(backups: Path) -> None:
    data_root = user_data_dir()
    if _is_inside(backups, data_root):
        raise RuntimeError("pre-upgrade backup destination is inside the wipe tree")
    expected = pre_upgrade_backups_dir()
    if backups.resolve() != expected.resolve():
        raise RuntimeError("pre-upgrade backup destination left the backups folder")


def _prune_stale_partial_folders(backups: Path) -> None:
    if not backups.is_dir():
        return
    try:
        _require_outside_wipe_tree(backups)
    except RuntimeError:
        return
    for path in list(backups.iterdir()):
        if _is_partial_backup(path):
            _delete_inside_backups(path, backups)


def _prune_pre_upgrade_folders(backups: Path, *, keep: int) -> None:
    if not backups.is_dir():
        return
    try:
        _require_outside_wipe_tree(backups)
    except RuntimeError:
        return
    _prune_stale_partial_folders(backups)
    folders = [
        path
        for path in backups.iterdir()
        if path.name.startswith("pre-")
        and not path.name.endswith(".partial")
        and (path.is_dir() or path.is_symlink())
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
