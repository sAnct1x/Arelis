"""Resolve recently generated image paths for vision / regen turns."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from arelis.paths import display_path, outputs_dir

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# Absolute or project-relative outputs/images paths mentioned in chat/tool notes.
_PATH_MENTION = re.compile(
    r"(?i)("
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+[/\\])?"
    r"outputs[/\\]images[/\\][^\s\"'<>|]+\.(?:png|jpe?g|webp|gif)"
    r"|"
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+[/\\])?"
    r"data[/\\]drops[/\\][^\s\"'<>|]+\.(?:png|jpe?g|webp|gif)"
    r"|"
    r"[A-Za-z]:[\\/][^\s\"'<>|]+[/\\]arelis_\d+[^\s\"'<>|]*\.(?:png|jpe?g|webp|gif)"
    r")"
)

_JUST_MADE = re.compile(
    r"(?i)\b(?:you\s+just\s+(?:created|generated|made|drew)|"
    r"(?:picture|image|photo)\s+you\s+just|"
    r"the\s+(?:picture|image)\s+you\s+just)\b"
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
    return display_path(path)


def latest_output_image_file(*, images_dir: Path | None = None) -> str | None:
    """Newest file under outputs/images/, or None."""
    folder = images_dir or (outputs_dir() / "images")
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
    folder = images_dir or (outputs_dir() / "images")
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


def _attachment_image_path(text: str) -> str | None:
    """First image listed in this turn's Attachments block, if any."""
    from arelis.attachments import parse_attachments_from_turn

    for row in parse_attachments_from_turn(text or ""):
        if str(row.get("kind") or "").lower() != "image":
            continue
        path = str(row.get("path") or "").strip()
        if path:
            return path.replace("\\", "/")
    return None


_STYLE_FROM_ASK = (
    ("watercolor", "watercolor"),
    ("watercolour", "watercolor"),
    ("oil painting", "oil"),
    ("oil paint", "oil"),
    ("photoreal", "photoreal"),
    ("cinematic", "cinematic"),
    ("illustration", "illustration"),
    ("anime", "anime"),
    ("sketch", "sketch"),
)

_N_FROM_ASK = re.compile(
    r"(?i)(?:"
    r"\bn\s*=\s*(?P<n_eq>[1-4])\b|"
    r"\b(?P<n_word>four|4|three|3|two|2)\s+"
    r"(?:versions?|variations?|variants?|pictures?|images?)|"
    r"another\s+(?P<n_another>four|4)\b"
    r")"
)
_N_WORD = {"four": 4, "4": 4, "three": 3, "3": 3, "two": 2, "2": 2}

_MASK_REGION = re.compile(
    r"(?i)\b(?:remove|change|replace|inpaint)\s+(?:the\s+)?"
    r"(?P<region>left|right|top|bottom|center|centre)\b"
)

_CROP_SIDE = re.compile(
    r"(?i)\bcrop(?:ped|ping)?\s+"
    r"(?:(?:to|out)\s+)?"
    r"(?:the\s+)?"
    r"(?:(?P<half>left|right|top|bottom)\s+half|"
    r"(?P<region>left|right|top|bottom|center|centre|middle))"
)

_UPSCALE = re.compile(
    r"(?i)\b("
    r"upscale|upscaled|upscaling|"
    r"enlarge|enlarged|"
    r"(?:make|blow)\s+(?:it|this|that)\s+(?:up|bigger|larger)|"
    r"scale\s*=\s*2|"
    r"2x|"
    r"twice\s+(?:as\s+)?(?:big|large)|"
    r"twice\s+the\s+size"
    r")\b"
)

_BG_REMOVE = re.compile(
    r"(?i)\b(?:remove|cut\s+out|erase|knock\s+out)\s+(?:the\s+)?background\b"
)
_OUTPAINT = re.compile(
    r"(?i)\b(?:outpaint|uncrop|extend\s+(?:the\s+)?(?:canvas|image|picture|photo|png))\b"
)


def n_from_ask(user_text: str = "") -> int | None:
    """Batch count from 'four versions' / n=4, or None."""
    hit = _N_FROM_ASK.search(user_text or "")
    if not hit:
        return None
    raw = hit.group("n_eq") or hit.group("n_word") or hit.group("n_another")
    if not raw:
        return None
    if raw.isdigit():
        return max(1, min(4, int(raw)))
    return _N_WORD.get(raw.lower())


def mask_region_from_ask(user_text: str = "") -> str:
    """left/right/top/bottom/center for a generative region ask, or ''."""
    hit = _MASK_REGION.search(user_text or "")
    if not hit:
        return ""
    region = (hit.group("region") or "").lower()
    return "center" if region == "centre" else region


def crop_from_ask(user_text: str = "") -> str:
    """Pixel crop side from 'crop the left half' / 'crop to the center', or ''."""
    hit = _CROP_SIDE.search(user_text or "")
    if not hit:
        return ""
    raw = (hit.group("half") or hit.group("region") or "").lower()
    if raw in {"center", "centre", "middle"}:
        return "center"
    return raw


def scale_from_ask(user_text: str = "") -> int | None:
    """2 when the ask is an exact enlarge (upscale / 2x / make it bigger)."""
    if _UPSCALE.search(user_text or ""):
        return 2
    return None


def _fill_existing_image_path(
    out: dict[str, Any],
    ask: str,
    history: list[Any] | None,
) -> None:
    """Stamp path= from this turn or the last generated file when missing."""
    if str(out.get("path") or "").strip():
        return
    just_made = bool(_JUST_MADE.search(ask))
    attached = None if just_made else _attachment_image_path(ask)
    if attached:
        out["path"] = attached
        return
    from_user = path_from_text(ask)
    if from_user and not just_made:
        out["path"] = from_user.replace("\\", "/")
        return
    path = latest_generated_image_path(history)
    if path:
        out["path"] = path


def style_from_ask(user_text: str = "") -> str:
    """Named image style mentioned in the ask, or ''."""
    lowered = (user_text or "").lower()
    for needle, style in _STYLE_FROM_ASK:
        if needle in lowered:
            return style
    return ""


def fill_image_gen_args(
    args: dict[str, Any],
    *,
    history: list[Any] | None = None,
    user_text: str | None = None,
) -> dict[str, Any]:
    """Fill img2img path / style / surgical args from this turn or last file."""
    from arelis.attachments import (
        wants_image_restyle,
        wants_image_surgical,
        wants_image_variations,
        wants_same_seed,
    )

    out = dict(args)
    ask = user_text or ""
    if wants_same_seed(ask) and out.get("seed") is None:
        last = latest_generated_image_path(history)
        if last:
            from arelis.tools.image_meta import read_named_sidecar

            meta = read_named_sidecar(last)
            seed = meta.get("seed")
            if seed is not None:
                try:
                    out["seed"] = int(seed)
                except (TypeError, ValueError):
                    pass
            prompt = str(meta.get("prompt") or "").strip()
            asked = str(out.get("prompt") or "").strip()
            if prompt and (not asked or wants_same_seed(asked) or wants_same_seed(ask)):
                # "Do that again" is not a new subject — reuse the last prompt.
                if not re.search(r"(?i)\b(?:of|with)\s+a\b", ask):
                    out["prompt"] = prompt
            if not str(out.get("style") or "").strip() and meta.get("style"):
                out["style"] = str(meta["style"])
    needs_path = wants_image_restyle(ask) or wants_image_surgical(ask)
    if not needs_path and wants_image_variations(ask):
        needs_path = bool(
            _attachment_image_path(ask)
            or _JUST_MADE.search(ask)
            or re.search(
                r"(?i)\b(?:this|that)\s+(?:picture|image|photo|png)\b",
                ask,
            )
        )
    if needs_path:
        _fill_existing_image_path(out, ask, history)
    if wants_image_restyle(ask) and out.get("denoise") is None:
        out["denoise"] = 0.55
    if not str(out.get("style") or "").strip():
        style = style_from_ask(ask)
        if style:
            out["style"] = style
    if out.get("n") is None:
        batch = n_from_ask(ask)
        if batch:
            out["n"] = batch
    if out.get("remove_background") is None and _BG_REMOVE.search(ask):
        out["remove_background"] = True
    if not str(out.get("outpaint") or "").strip() and _OUTPAINT.search(ask):
        out["outpaint"] = "all"
    if not str(out.get("mask_region") or "").strip():
        region = mask_region_from_ask(ask)
        if region:
            out["mask_region"] = region
    return out


def fill_image_edit_args(
    args: dict[str, Any],
    *,
    history: list[Any] | None = None,
    user_text: str | None = None,
) -> dict[str, Any]:
    """Fill missing image_edit path, crop, scale, and overlay from this turn."""
    from arelis.attachments import overlay_text_from_ask

    out = dict(args)
    ask = user_text or ""
    _fill_existing_image_path(out, ask, history)
    if not str(out.get("crop") or "").strip():
        crop = crop_from_ask(ask)
        if crop:
            out["crop"] = crop
    if out.get("scale") is None:
        scale = scale_from_ask(ask)
        if scale:
            out["scale"] = scale
    if not str(out.get("text") or "").strip():
        overlay = overlay_text_from_ask(ask)
        if overlay:
            out["text"] = overlay
            lowered = ask.lower()
            if "center" in lowered or "centre" in lowered or "middle" in lowered:
                out.setdefault("text_align", "center")
    return out


def fill_vision_args(
    args: dict[str, Any],
    *,
    history: list[Any] | None = None,
    fallback_path: str | None = None,
    user_text: str | None = None,
) -> dict[str, Any]:
    """Fill missing vision path: this-turn paste, then camera, then last generate."""
    out = dict(args)
    if str(out.get("path") or "").strip():
        return out
    if fallback_path:
        out["path"] = fallback_path
        return out
    attached = _attachment_image_path(user_text or "")
    if attached:
        out["path"] = attached
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
        "prompt (include happier / less sad / cute if they asked). "
        "If they asked to restyle a picture that already exists, pass path= "
        "as well. Four versions is n=4. Cut-out is remove_background=true + "
        "path. Extend/uncrop is outpaint=all + path. Change the "
        "left/right/top/bottom/center is mask_region= + path."
        f"{extra} Do not web_search for stock photos. Do not claim you cannot "
        "generate images. Allow still applies."
    )
