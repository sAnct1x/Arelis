"""Resolve recently generated image paths for vision / regen turns."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Absolute or project-relative outputs/images paths mentioned in chat/tool notes.
_PATH_MENTION = re.compile(
    r"(?i)("
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+[/\\])?"
    r"outputs[/\\]images[/\\][^\s\"'<>|]+\.(?:png|jpe?g|webp|gif)"
    r"|"
    r"[A-Za-z]:[\\/][^\s\"'<>|]+[/\\]arelis_\d+[^\s\"'<>|]*\.(?:png|jpe?g|webp|gif)"
    r")"
)

_JUST_GENERATED = re.compile(
    r"(?i)\b("
    r"(?:just\s+)?(?:generated|made|created|drew)|"
    r"the\s+(?:image|picture|photo)\s+(?:you|we)\s+(?:just\s+)?"
    r"(?:generated|made|created|drew|saved)|"
    r"(?:this|that|the)\s+(?:image|picture|photo|puppy)"
    r")\b"
)

_CAMERA_LOOK = re.compile(
    r"(?i)\b("
    r"(?:look\s+at|see|check|describe|what(?:'s|\s+is)\s+on)\s+"
    r"(?:the\s+)?(?:camera|webcam|cam)\b|"
    r"(?:camera|webcam|cam)\s+(?:feed|view|frame|snapshot|picture|image)\b|"
    r"look\s+at\s+this\b|"
    r"what\s+am\s+i\s+looking\s+at\b|"
    r"what\s+do\s+you\s+see\b|"
    r"what(?:'s|\s+is)\s+(?:in\s+)?(?:front\s+of\s+you|on\s+(?:the\s+)?(?:camera|webcam))\b|"
    r"(?:from|via|using)\s+(?:the\s+)?(?:camera|webcam)\b"
    r")\b"
)

# Camera dock / tool snapshots use this prefix under outputs/images/.
_CAMERA_FILE_PREFIX = "camera_"
# Fresh enough to reuse without a new capture (camera tool + fill_vision_args).
CAMERA_FRESH_S = 30.0


def mentions_recent_image(text: str) -> bool:
    """True when the user points at the last generated/shown image without a path."""
    return bool(_JUST_GENERATED.search(text or ""))


def mentions_camera_look(text: str) -> bool:
    """True when the user asks Arelis to look via the webcam / camera dock."""
    return bool(_CAMERA_LOOK.search(text or ""))


def _history_pairs(history: list[Any] | None) -> list[tuple[str, str, str]]:
    """(role, content, note) newest-last."""
    out: list[tuple[str, str, str]] = []
    for item in history or []:
        if hasattr(item, "role"):
            note = str(getattr(item, "note", "") or "")
            out.append(
                (str(item.role), str(getattr(item, "content", "") or ""), note)
            )
        elif isinstance(item, dict):
            out.append(
                (
                    str(item.get("role") or ""),
                    str(item.get("content") or ""),
                    str(item.get("note") or ""),
                )
            )
    return out


def path_from_text(text: str) -> str | None:
    match = _PATH_MENTION.search(text or "")
    if not match:
        return None
    return match.group(1).strip().rstrip(".,);]")


def _rel_under_project(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(PROJECT_ROOT.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(path)


def latest_output_image_file(*, images_dir: Path | None = None) -> str | None:
    """Newest file under outputs/images/, or None."""
    folder = images_dir or (PROJECT_ROOT / "outputs" / "images")
    try:
        if not folder.is_dir():
            return None
        files = [
            p
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_SUFFIXES
        ]
    except OSError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    return _rel_under_project(newest)


def latest_camera_image_file(
    *,
    images_dir: Path | None = None,
    max_age_s: float | None = None,
) -> str | None:
    """Newest camera_*.jpg|png under outputs/images/, optionally age-capped."""
    folder = images_dir or (PROJECT_ROOT / "outputs" / "images")
    try:
        if not folder.is_dir():
            return None
        files = [
            p
            for p in folder.iterdir()
            if p.is_file()
            and p.suffix.lower() in _IMAGE_SUFFIXES
            and p.name.lower().startswith(_CAMERA_FILE_PREFIX)
        ]
    except OSError:
        return None
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    if max_age_s is not None:
        try:
            age = time.time() - newest.stat().st_mtime
        except OSError:
            return None
        if age > max_age_s:
            return None
    return _rel_under_project(newest)


def latest_generated_image_path(
    history: list[Any] | None = None,
    *,
    images_dir: Path | None = None,
) -> str | None:
    """Best path for 'describe the image you just generated'.

    Prefer a path named in recent chat/tool notes; else newest outputs/images file.
    """
    for _role, content, note in reversed(_history_pairs(history)):
        for blob in (note, content):
            hit = path_from_text(blob)
            if hit:
                return hit.replace("\\", "/")
    return latest_output_image_file(images_dir=images_dir)


def fill_vision_args(
    args: dict[str, Any],
    *,
    history: list[Any] | None = None,
    fallback_path: str | None = None,
    user_text: str | None = None,
) -> dict[str, Any]:
    """Fill missing vision path from camera frame or last generated image."""
    out = dict(args)
    if str(out.get("path") or "").strip():
        return out
    if fallback_path:
        out["path"] = fallback_path
        return out
    # Prefer an explicit path in the user turn (Ask Arelis injects one).
    from_user = path_from_text(user_text or "")
    if from_user:
        out["path"] = from_user.replace("\\", "/")
        return out
    if mentions_camera_look(user_text or ""):
        cam = latest_camera_image_file()
        if cam:
            out["path"] = cam
            return out
    path = latest_generated_image_path(history)
    if path:
        out["path"] = path
    return out


def image_force_call_notice(*, prompt_hint: str = "") -> str:
    """Nudge when image-gen intent is clear but image was never called."""
    hint = (prompt_hint or "").strip()
    extra = f" Prefer prompt about: {hint[:120]}." if hint else ""
    return (
        "You have not called the image tool yet. Call image now with a clear "
        "prompt (include happier / less sad / cute if they asked)."
        f"{extra} Do not web_search for stock photos. Do not claim you cannot "
        "generate images. Allow still applies."
    )
