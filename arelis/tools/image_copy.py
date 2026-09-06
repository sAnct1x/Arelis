"""Human copy for generate and pixel-edit. Status, confirm, and progress."""

from __future__ import annotations

from typing import Any


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _count(args: dict[str, Any]) -> int:
    try:
        return max(1, min(4, int(args.get("n") or 1)))
    except (TypeError, ValueError):
        return 1


def image_errand(args: dict[str, Any] | None = None) -> str:
    """What the shimmer says while Comfy runs."""
    args = args or {}
    if _truthy(args.get("remove_background")):
        return "cutting out the background"
    if str(args.get("outpaint") or "").strip():
        return "growing the picture"
    if str(args.get("mask_region") or "").strip() or args.get("mask_box") is not None:
        return "changing part of the picture"
    if str(args.get("path") or "").strip():
        return "restyling the picture"
    n = _count(args)
    if n > 1:
        return f"making {n} pictures"
    return "making a picture"


def image_edit_errand(args: dict[str, Any] | None = None) -> str:
    """What the shimmer says while Pillow runs."""
    args = args or {}
    if str(args.get("text") or "").strip():
        return "adding text to the picture"
    if str(args.get("crop") or args.get("crop_box") or "").strip():
        return "cropping the picture"
    if args.get("scale") is not None or args.get("width") is not None:
        return "resizing the picture"
    if args.get("rotate") is not None:
        return "rotating the picture"
    if _truthy(args.get("grayscale")):
        return "making the picture black and white"
    return "editing the picture"


def image_progress_line(
    *,
    index: int = 1,
    n: int = 1,
    step: int = 0,
    total: int = 0,
) -> str:
    """Composer shimmer while a Comfy job is still sampling."""
    count = max(1, min(4, int(n)))
    which = max(1, min(count, int(index)))
    if count > 1:
        base = f"making picture {which} of {count}"
    else:
        base = "making a picture"
    if int(total) > 0:
        return f"✦ {base} ({int(step)}/{int(total)})…"
    return f"✦ {base}…"


def image_confirm_headline(args: dict[str, Any] | None = None) -> str:
    args = args or {}
    if _truthy(args.get("remove_background")):
        return "cut out the background"
    if str(args.get("outpaint") or "").strip():
        return "grow this picture"
    if str(args.get("mask_region") or "").strip() or args.get("mask_box") is not None:
        return "change part of this picture"
    style = str(args.get("style") or "").strip()
    if str(args.get("path") or "").strip():
        return f"restyle this as {style}" if style else "restyle this picture"
    n = _count(args)
    if n > 1:
        return f"make {n} pictures"
    return "make a picture"


def image_edit_confirm_headline(args: dict[str, Any] | None = None) -> str:
    args = args or {}
    overlay = str(args.get("text") or "").strip()
    if overlay:
        shown = overlay if len(overlay) <= 24 else overlay[:23] + "…"
        return f'add "{shown}" to this picture'
    if str(args.get("crop") or args.get("crop_box") or "").strip():
        return "crop this picture"
    if args.get("scale") is not None:
        try:
            scale = float(args.get("scale"))
        except (TypeError, ValueError):
            scale = 0.0
        if scale == 2:
            return "enlarge this picture"
        return "resize this picture"
    if args.get("width") is not None or args.get("height") is not None:
        return "resize this picture"
    if _truthy(args.get("grayscale")):
        return "make this picture black and white"
    if args.get("rotate") is not None:
        return "rotate this picture"
    return "edit this picture"
