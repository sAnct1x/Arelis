"""Throwaway stills she took to look — not pictures she made for you.

Browser / desk / OCR-screen captures live under outputs/images/ with a
prefix. After vision or OCR reads one, it goes. Leftovers from a crashed
turn are swept at the end of the turn and again on launch. Generated
images, image_edit outputs, and your drops are not this.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from arelis.paths import outputs_dir

log = logging.getLogger(__name__)

LOOK_PREFIXES = ("browser_", "desktop_", "ocr_screen_")
CAMERA_PREFIX = "camera_"
LOOK_KEEP = 4
CAMERA_KEEP = 2

_KEEP_ASK = re.compile(
    r"(?i)\b("
    r"(?:save|keep|don't delete|do not delete)\b.{0,48}\b"
    r"(?:screenshot|screen ?shot|capture|still)\b|"
    r"(?:screenshot|screen ?shot|capture|still)\b.{0,48}\b"
    r"(?:save|keep)\b"
    r")"
)

_pending: set[Path] = set()
_hold = False


def hold_look_files(on: bool) -> None:
    """This turn asked to keep the capture — forget/sweep must not unlink it."""
    global _hold
    _hold = bool(on)


def images_dir() -> Path:
    return outputs_dir() / "images"


def is_look_scratch(path: Path | str) -> bool:
    """True for a throwaway look still under outputs/images/."""
    try:
        resolved = Path(path).expanduser().resolve()
        root = images_dir().resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    name = resolved.name.lower()
    return name.startswith(LOOK_PREFIXES)


def keep_look_files(text: str) -> bool:
    """True when they asked to keep the capture, not just look at it."""
    return bool(_KEEP_ASK.search(text or ""))


def note_look_scratch(path: Path | str) -> None:
    raw = Path(path)
    if not is_look_scratch(raw):
        return
    try:
        _pending.add(raw.expanduser().resolve())
    except OSError:
        _pending.add(raw)


def forget_look_scratch(path: Path | str) -> bool:
    """Unlink a look still. False when it was not scratch or already gone."""
    if _hold:
        return False
    raw = Path(path)
    try:
        resolved = raw.expanduser().resolve()
    except OSError:
        resolved = raw
    _pending.discard(resolved)
    _pending.discard(raw)
    if not is_look_scratch(resolved) and not is_look_scratch(raw):
        return False
    target = resolved if resolved.is_file() else raw
    if not target.is_file():
        return False
    try:
        target.unlink()
        return True
    except OSError:
        log.debug("look scratch unlink failed: %s", target, exc_info=True)
        return False


def clear_look_pending() -> None:
    global _hold
    _pending.clear()
    _hold = False


def sweep_look_scratch(*, keep: bool = False) -> int:
    """End of turn: drop unused look stills from this turn, unless they said keep."""
    if keep:
        clear_look_pending()
        return 0
    removed = 0
    for path in list(_pending):
        if forget_look_scratch(path):
            removed += 1
    clear_look_pending()
    return removed


def prune_look_scratch(
    *,
    directory: Path | None = None,
    keep: int = LOOK_KEEP,
    camera_keep: int = CAMERA_KEEP,
) -> int:
    """Launch leftover: newest look stills stay, the rest go."""
    root = directory if directory is not None else images_dir()
    if not root.is_dir():
        return 0
    removed = _prune_prefix(root, LOOK_PREFIXES, max(0, int(keep)))
    removed += _prune_prefix(root, (CAMERA_PREFIX,), max(0, int(camera_keep)))
    return removed


def _prune_prefix(root: Path, prefixes: tuple[str, ...], keep: int) -> int:
    try:
        files = [
            p
            for p in root.iterdir()
            if p.is_file() and p.name.lower().startswith(prefixes)
        ]
    except OSError:
        return 0
    files.sort(key=lambda p: p.stat().st_mtime)
    removed = 0
    for stale in files[: max(0, len(files) - keep)]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            log.debug("look scratch prune failed: %s", stale, exc_info=True)
    return removed
