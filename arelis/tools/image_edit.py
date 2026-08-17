"""Change a picture that already exists: size, crop, and how strong it looks.

The gap this fills was found by a real ask -- "make this more vibrant and resize
it to 1280 x 720 for a YouTube thumbnail" -- which had no tool that could do it.
Arelis reached for the three that existed and all three were wrong: `vision`
looks at an image and cannot alter one, `image` creates pixels from a text
prompt and produced an unrelated picture at the right size, and the calculator
was forced in at the end because "1280 x 720" reads as arithmetic. Three Allow
cards, three minutes, and nothing the user asked for.

Nothing here involves a model. Resizing and saturation are arithmetic on pixels
with an exactly right answer, so they are done in-process by Pillow, take
milliseconds, and produce the same result every time. The source file is never
modified: every edit is written as a new file, because the input is usually the
only copy of something somebody sent you.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arelis.paths import display_path, ensure, outputs_dir
from arelis.tools.base import ToolResult
from arelis.tools.image_io import pillow_error, resolve_image
from arelis.workspace import WorkspaceRoots

# The sizes people ask for by name. Anything else is width/height directly,
# which is why this stays short instead of trying to be a catalogue.
SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "youtube_thumbnail": (1280, 720),
    "youtube_banner": (2048, 1152),
    "instagram_square": (1080, 1080),
    "instagram_story": (1080, 1920),
    "wallpaper_1080p": (1920, 1080),
    "wallpaper_1440p": (2560, 1440),
}

FIT_MODES = ("cover", "contain", "stretch")

# Enhancement factors: 1.0 is untouched. Clamped because a model that decides
# vibrance should be 40 produces a solid colour field, and a tool should not
# have a way to be asked for nonsense and comply.
_MIN_FACTOR = 0.1
_MAX_FACTOR = 3.0

# One edge, and total pixels, past which this is no longer a thumbnail tweak.
_MAX_EDGE = 8192
_MAX_PIXELS = 40_000_000

_ADJUSTMENTS = ("vibrance", "contrast", "brightness", "sharpness")


def _clamp_factor(value: Any, name: str) -> float:
    try:
        factor = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}")
    if factor != factor:  # NaN
        raise ValueError(f"{name} must be a number, got {value!r}")
    return max(_MIN_FACTOR, min(_MAX_FACTOR, factor))


def _percent(factor: float) -> str:
    """1.3 -> '+30%', 0.8 -> '-20%'. How a person reads a change in strength."""
    delta = round((factor - 1.0) * 100)
    return f"{'+' if delta >= 0 else ''}{delta}%"


def _unique_dest(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


class ImageEditTool:
    name = "image_edit"
    description = (
        "Edit a local image that already exists: resize or crop it to a size, and "
        "make it more (or less) vibrant, contrasty, bright or sharp. Use this for "
        "'resize this', 'make this more vibrant', 'crop this to 16:9', 'turn this "
        "into a YouTube thumbnail'. Writes a NEW file and never changes the "
        "original. Args: path, then any of width+height or preset "
        "(youtube_thumbnail, youtube_banner, instagram_square, instagram_story, "
        "wallpaper_1080p, wallpaper_1440p), fit (cover crops to fill, contain "
        "pads, stretch distorts), and vibrance/contrast/brightness/sharpness "
        "where 1.0 is unchanged, 1.3 is noticeably more and 0.8 is less. "
        "This is exact pixel work, not generation: use the image tool to create a "
        "new picture from a text prompt, and the vision tool to look at one."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "The image to edit: workspace-relative, name:rel, or a staged "
                    "attachment path such as data/drops/<day>/<file>.png."
                ),
            },
            "preset": {
                "type": "string",
                "enum": sorted(SIZE_PRESETS),
                "description": "A named output size. Ignored when width/height are given.",
            },
            "width": {"type": "integer", "description": "Target width in pixels."},
            "height": {"type": "integer", "description": "Target height in pixels."},
            "fit": {
                "type": "string",
                "enum": list(FIT_MODES),
                "description": (
                    "How to reconcile a different shape: cover (default) scales to "
                    "fill and centre-crops, contain scales to fit and pads, stretch "
                    "distorts to the exact size."
                ),
            },
            "vibrance": {
                "type": "number",
                "description": "Colour saturation. 1.0 unchanged, 1.3 more vibrant, 0.5 muted.",
            },
            "contrast": {"type": "number", "description": "1.0 unchanged, 1.2 punchier."},
            "brightness": {"type": "number", "description": "1.0 unchanged, 1.15 brighter."},
            "sharpness": {"type": "number", "description": "1.0 unchanged, 1.5 crisper."},
            "format": {
                "type": "string",
                "enum": ["png", "jpg"],
                "description": "Output format. Defaults to png (lossless).",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: WorkspaceRoots, *, output_dir: str | Path = "") -> None:
        self.workspace = workspace
        self._output_dir = Path(output_dir) if output_dir else None

    def output_dir(self) -> Path:
        """Resolved late so a test that moves the data root is believed."""
        return self._output_dir or (outputs_dir() / "images")

    def _target_size(self, kwargs: dict[str, Any]) -> tuple[int, int] | None:
        width = kwargs.get("width")
        height = kwargs.get("height")
        if width is not None or height is not None:
            if width is None or height is None:
                raise ValueError(
                    "Give both width and height, or a preset. A single dimension is "
                    "ambiguous: it could keep the shape or crop to it."
                )
            size = (int(width), int(height))
        else:
            preset = str(kwargs.get("preset") or "").strip().lower()
            if not preset:
                return None
            if preset not in SIZE_PRESETS:
                known = ", ".join(sorted(SIZE_PRESETS))
                raise ValueError(f"Unknown preset `{preset}`. Known: {known}.")
            size = SIZE_PRESETS[preset]
        if min(size) < 1:
            raise ValueError(f"Size must be positive, got {size[0]}x{size[1]}.")
        if max(size) > _MAX_EDGE or (size[0] * size[1]) > _MAX_PIXELS:
            raise ValueError(
                f"{size[0]}x{size[1]} is larger than this tool will produce "
                f"(max edge {_MAX_EDGE}px)."
            )
        return size

    async def run(self, **kwargs: Any) -> ToolResult:
        missing = pillow_error()
        if missing:
            return ToolResult(ok=False, output=f"[fail:image_edit] {missing}")
        try:
            source = resolve_image(self.workspace, str(kwargs.get("path") or ""))
        except (ValueError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, output=f"[fail:image_edit] {exc}")

        try:
            size = self._target_size(kwargs)
            factors = {
                key: _clamp_factor(kwargs[key], key)
                for key in _ADJUSTMENTS
                if kwargs.get(key) is not None
            }
        except ValueError as exc:
            return ToolResult(ok=False, output=f"[fail:image_edit] {exc}")

        adjusting = {k: v for k, v in factors.items() if abs(v - 1.0) > 1e-6}
        if size is None and not adjusting:
            return ToolResult(
                ok=False,
                output=(
                    "[fail:image_edit] Nothing to change. Pass a size (width and "
                    "height, or preset=youtube_thumbnail) and/or an adjustment "
                    "(vibrance=1.3, contrast=1.1, brightness=1.1, sharpness=1.4)."
                ),
            )

        fit = str(kwargs.get("fit") or "cover").strip().lower()
        if fit not in FIT_MODES:
            return ToolResult(
                ok=False,
                output=f"[fail:image_edit] fit must be one of {', '.join(FIT_MODES)}.",
            )
        fmt = str(kwargs.get("format") or "png").strip().lower().lstrip(".")
        if fmt in {"jpeg"}:
            fmt = "jpg"
        if fmt not in {"png", "jpg"}:
            return ToolResult(
                ok=False, output="[fail:image_edit] format must be png or jpg."
            )

        try:
            result = await asyncio.to_thread(
                self._edit, source, size, adjusting, fit, fmt
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=f"[fail:image_edit] Could not edit {display_path(source)}: {exc}",
            )
        return result

    def _edit(
        self,
        source: Path,
        size: tuple[int, int] | None,
        factors: dict[str, float],
        fit: str,
        fmt: str,
    ) -> ToolResult:
        from PIL import Image, ImageEnhance

        enhancers = {
            "vibrance": ImageEnhance.Color,
            "contrast": ImageEnhance.Contrast,
            "brightness": ImageEnhance.Brightness,
            "sharpness": ImageEnhance.Sharpness,
        }

        with Image.open(source) as opened:
            original = opened.size
            frame = opened.convert("RGBA" if fmt == "png" else "RGB")

        notes: list[str] = []
        cropped = False
        if size is not None and size != original:
            frame, cropped = _fit_to(frame, size, fit)
        elif size == original:
            notes.append(f"already {original[0]}x{original[1]}")

        for key in _ADJUSTMENTS:
            if key not in factors:
                continue
            frame = enhancers[key](frame.convert("RGB") if key == "sharpness" else frame)
            frame = frame.enhance(factors[key])

        directory = ensure(self.output_dir())
        parts = [source.stem]
        if size is not None:
            parts.append(f"{frame.width}x{frame.height}")
        if "vibrance" in factors:
            parts.append("vibrant" if factors["vibrance"] > 1 else "muted")
        suffix = ".png" if fmt == "png" else ".jpg"
        if fmt == "jpg" and frame.mode != "RGB":
            frame = frame.convert("RGB")
        dest = _unique_dest(directory, "-".join(parts), suffix)
        save_args: dict[str, Any] = {}
        if fmt == "jpg":
            save_args = {"quality": 92, "optimize": True}
        frame.save(dest, **save_args)

        changes: list[str] = []
        if size is not None:
            arrow = (
                f"{original[0]}x{original[1]} to {frame.width}x{frame.height}"
            )
            if cropped:
                arrow += " (centre-cropped to that shape)"
            elif fit == "contain" and original != (frame.width, frame.height):
                arrow += " (padded to that shape)"
            changes.append(arrow)
        for key in _ADJUSTMENTS:
            if key in factors:
                label = "vibrance" if key == "vibrance" else key
                changes.append(f"{label} {_percent(factors[key])}")
        changes.extend(notes)

        rel = display_path(dest)
        return ToolResult(
            ok=True,
            output=f"Saved {rel} — {', '.join(changes)}.",
            data={
                "path": rel,
                "abs_path": str(dest),
                "source": display_path(source),
                "source_px": [original[0], original[1]],
                "result_px": [frame.width, frame.height],
                "cropped": cropped,
                "fit": fit,
                "adjustments": {k: round(v, 3) for k, v in factors.items()},
            },
        )


def _fit_to(frame: Any, size: tuple[int, int], fit: str) -> tuple[Any, bool]:
    """Scale to the target, returning the frame and whether pixels were cut."""
    from PIL import Image

    target_w, target_h = size
    source_w, source_h = frame.size
    if fit == "stretch":
        return frame.resize((target_w, target_h), Image.LANCZOS), False

    source_ratio = source_w / source_h
    target_ratio = target_w / target_h
    same_shape = abs(source_ratio - target_ratio) < 1e-3

    if fit == "contain" and not same_shape:
        scale = min(target_w / source_w, target_h / source_h)
        scaled = frame.resize(
            (max(1, round(source_w * scale)), max(1, round(source_h * scale))),
            Image.LANCZOS,
        )
        canvas = Image.new(frame.mode, (target_w, target_h), _pad_colour(frame.mode))
        canvas.paste(scaled, ((target_w - scaled.width) // 2, (target_h - scaled.height) // 2))
        return canvas, False

    # cover, and contain when the shape already matches: fill the frame, then
    # take the middle. Centre is the only defensible default without knowing
    # what the subject is, and the reply says a crop happened so it can be
    # argued with.
    scale = max(target_w / source_w, target_h / source_h)
    scaled = frame.resize(
        (max(target_w, round(source_w * scale)), max(target_h, round(source_h * scale))),
        Image.LANCZOS,
    )
    left = (scaled.width - target_w) // 2
    top = (scaled.height - target_h) // 2
    out = scaled.crop((left, top, left + target_w, top + target_h))
    return out, not same_shape


def _pad_colour(mode: str) -> Any:
    return (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0)
