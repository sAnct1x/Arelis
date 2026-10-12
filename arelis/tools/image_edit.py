"""Change a picture that already exists: size, crop, rotate, strength, and text.

The gap this fills was found by a real ask -- "make this more vibrant and resize
it to 1280 x 720 for a YouTube thumbnail" -- which had no tool that could do it.
Arelis reached for the three that existed and all three were wrong: `vision`
looks at an image and cannot alter one, `image` creates pixels from a text
prompt and produced an unrelated picture at the right size, and the calculator
was forced in at the end because "1280 x 720" reads as arithmetic. Three Allow
cards, three minutes, and nothing the user asked for.

Resizing and saturation are arithmetic on pixels with an exactly right answer,
so they are done in-process by Pillow. remove_background and upscale are the
exception: a small ONNX model on the CPU, downloaded the first time, with the
GPU left for the chat model. The source file is never
modified: every edit is written as a new file, because the input is usually the
only copy of something somebody sent you. Generative restyle ("make this a
watercolor") is the image tool with path=, not this module.
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
    "tiktok": (1080, 1920),
    "twitter_post": (1600, 900),
    "linkedin_post": (1200, 627),
    "wallpaper_1080p": (1920, 1080),
    "wallpaper_1440p": (2560, 1440),
    "phone_wallpaper": (1080, 1920),
    "icon": (1024, 1024),
}

FIT_MODES = ("cover", "contain", "stretch")
FLIP_MODES = ("horizontal", "vertical")
TEXT_ALIGNS = ("center", "top", "bottom")
CROP_SIDES = ("left", "right", "top", "bottom", "center")
_MAX_OVERLAY_CHARS = 80

# Enhancement factors: 1.0 is untouched. Clamped because a model that decides
# vibrance should be 40 produces a solid colour field, and a tool should not
# have a way to be asked for nonsense and comply.
_MIN_FACTOR = 0.1
_MAX_FACTOR = 3.0

# Scale is "make this twice as big", not a model. 4× on a 4K still is already
# past what this tool is for; 0.1× is a stamp.
_MIN_SCALE = 0.1
_MAX_SCALE = 4.0
_MAX_PAD = 512
_WARMTH_LIFT = 48

# One edge, and total pixels, past which this is no longer a thumbnail tweak.
_MAX_EDGE = 8192
_MAX_PIXELS = 40_000_000

_ADJUSTMENTS = ("vibrance", "contrast", "brightness", "sharpness")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_learned(
    frame: Any,
    source: Path,
    *,
    remove_background: bool,
    upscale: int | None,
) -> tuple[Any, list[str], bool]:
    """Cutout, then model upscale. Raises ValueError with a plain sentence."""
    from arelis.tools.image_models import ModelError

    notes: list[str] = []
    cosmetic = False
    try:
        if remove_background:
            from arelis.config import load_config
            from arelis.tools.image_matting import cutout
            from arelis.tools.image_models import matting_model_name, total_ram_bytes

            tools = load_config().get("tools") or {}
            setting = str((tools.get("image_edit") or {}).get("matting_model") or "auto")
            model = matting_model_name(setting, total_ram_bytes())
            frame = cutout(frame, model)
            notes.append("background removed")
        if upscale:
            from arelis.tools.image_upscale import source_is_science, upscale_image

            _reject_huge(frame.width * upscale, frame.height * upscale)
            frame = upscale_image(frame, upscale)
            notes.append(f"upscaled {upscale}x")
            if source_is_science(source):
                cosmetic = True
                notes.append("This is cosmetic only. It is not for measurement.")
    except ModelError as exc:
        raise ValueError(str(exc)) from None
    return frame, notes, cosmetic


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


def _parse_crop_box(value: Any) -> tuple[int, int, int, int] | None:
    """Object or four numbers. Any of the four present means all four are required."""
    if value is None or value == "" or value == [] or value == {}:
        return None
    if isinstance(value, dict):
        keys = ("left", "top", "right", "bottom")
        present = [key for key in keys if value.get(key) is not None and value.get(key) != ""]
        if not present:
            return None
        if len(present) != 4:
            raise ValueError(
                "crop_box needs left, top, right, and bottom, a rectangle inside the image."
            )
        try:
            left, top, right, bottom = (int(value[key]) for key in keys)
        except (TypeError, ValueError):
            raise ValueError(
                "crop_box needs left, top, right, and bottom as pixel numbers."
            ) from None
    elif isinstance(value, (list, tuple)):
        if len(value) != 4:
            raise ValueError("crop_box needs four numbers: left, top, right, bottom.")
        try:
            left, top, right, bottom = (int(item) for item in value)
        except (TypeError, ValueError):
            raise ValueError(
                "crop_box needs four numbers: left, top, right, bottom."
            ) from None
    else:
        raise ValueError(
            "crop_box must be an object or four numbers: left, top, right, bottom."
        )
    if right <= left or bottom <= top or min(left, top) < 0:
        raise ValueError(
            "crop_box must be a valid rectangle inside the image "
            "(left < right, top < bottom)."
        )
    return left, top, right, bottom


def _reject_huge(width: int, height: int) -> None:
    if max(width, height) > _MAX_EDGE or (width * height) > _MAX_PIXELS:
        raise ValueError(
            f"{width}x{height} is larger than this tool will produce "
            f"(max edge {_MAX_EDGE}px)."
        )


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
        "Edit a local image that already exists: resize, crop, scale or pad it, "
        "rotate or flip it, overlay text, convert to grayscale, blur, invert, "
        "shift warmth, and make it more (or less) vibrant, contrasty, bright or "
        "sharp. Use this for 'resize this', 'make this more vibrant', 'crop the "
        "left half', 'crop this to 16:9', 'upscale this 2×', 'add a border', "
        "'warm it up', 'rotate 90', 'flip it', 'make it black and white', 'add "
        "text in the middle that says Arelis', 'turn this into a YouTube "
        "thumbnail'. Writes a NEW file and never changes the original. "
        "Args: path, then any of width+height or preset (youtube_thumbnail, "
        "youtube_banner, instagram_square, instagram_story, tiktok, twitter_post, "
        "linkedin_post, wallpaper_1080p, wallpaper_1440p, phone_wallpaper, icon), "
        "fit (cover crops to fill, contain pads, stretch distorts), crop "
        "(left/right/top/bottom/center, keep that half; center is the middle "
        "50% on both axes), crop_box (left, top, right, bottom in pixels on the "
        "source), scale (2.0 is 2×, clamped 0.1–4.0, arithmetic, not a model), "
        "pad (border pixels, black or transparent PNG), rotate (degrees "
        "clockwise), flip (horizontal/vertical), grayscale, invert, blur "
        "(radius), text (centered overlay), text_align (center/top/bottom), "
        "warmth (-1.0 cooler … +1.0 warmer), and vibrance/contrast/brightness/"
        "sharpness where 1.0 is unchanged, 1.3 is noticeably more and 0.8 is "
        "less. annotate draws arrows, boxes, and labels in pixels. scale_bar "
        "is a length in pixels plus a label. stretch is linear, asinh, log, "
        "or zscale and does not resample. remove_background cuts the "
        "background out (a PNG with transparency). upscale is 2 or 4 with a "
        "small model. scale stays arithmetic. This is exact pixel work, not "
        "generation: 'make this look like "
        "a watercolor' or 'in the style of' is the image tool with path= "
        "(img2img). Use vision to look at one. 'Add text' on a picture is this "
        "tool, never send_sms."
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
            "crop": {
                "type": "string",
                "enum": list(CROP_SIDES),
                "description": (
                    "Keep that half of the picture. center keeps the middle 50% "
                    "on both axes."
                ),
            },
            "crop_box": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": (
                    "Pixel rectangle on the source: left, top, right, bottom. "
                    "An object or four numbers. Must be a valid rectangle inside "
                    "the image."
                ),
            },
            "scale": {
                "type": "number",
                "description": (
                    "Exact enlarge or shrink. 2.0 is 2×. Clamped to 0.1–4.0. "
                    "Arithmetic, not a model."
                ),
            },
            "pad": {
                "type": "integer",
                "description": (
                    "Border in pixels on every side (0–512). Black, or "
                    "transparent on PNG."
                ),
            },
            "warmth": {
                "type": "number",
                "description": (
                    "Colour temperature. -1.0 cooler, +1.0 warmer. 0 is unchanged."
                ),
            },
            "vibrance": {
                "type": "number",
                "description": "Colour saturation. 1.0 unchanged, 1.3 more vibrant, 0.5 muted.",
            },
            "contrast": {"type": "number", "description": "1.0 unchanged, 1.2 punchier."},
            "brightness": {"type": "number", "description": "1.0 unchanged, 1.15 brighter."},
            "sharpness": {"type": "number", "description": "1.0 unchanged, 1.5 crisper."},
            "rotate": {
                "type": "number",
                "description": "Degrees clockwise. 90 / 180 / 270 are the usual asks.",
            },
            "flip": {
                "type": "string",
                "enum": list(FLIP_MODES),
                "description": "Mirror the picture: horizontal or vertical.",
            },
            "grayscale": {
                "type": "boolean",
                "description": "True converts to black and white.",
            },
            "invert": {
                "type": "boolean",
                "description": "True inverts the colours.",
            },
            "blur": {
                "type": "number",
                "description": "Gaussian blur radius. 1 is a hint, 4 is soft, 12 is heavy.",
            },
            "text": {
                "type": "string",
                "description": (
                    "Glyphs to stamp on the picture (e.g. Arelis). Centered by "
                    "default. Not an SMS, this draws on the image."
                ),
            },
            "text_align": {
                "type": "string",
                "enum": list(TEXT_ALIGNS),
                "description": "Where to place text: center (default), top, or bottom.",
            },
            "format": {
                "type": "string",
                "enum": ["png", "jpg"],
                "description": "Output format. Defaults to png (lossless).",
            },
            # 1b marks. One block so a parallel image_edit edit can rebase.
            "annotate": {
                "type": "array",
                "description": "Arrow, box, and label marks in pixels from the top left.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["arrow", "box", "label"],
                        },
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "x2": {"type": "integer"},
                        "y2": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                },
            },
            "scale_bar": {
                "type": "object",
                "description": "Bar length in pixels, plus a label.",
                "properties": {
                    "length": {"type": "integer"},
                    "label": {"type": "string"},
                },
            },
            "stretch": {
                "type": "string",
                "enum": ["linear", "asinh", "log", "zscale"],
                "description": "linear, asinh, log, or zscale. Same size, no resample.",
            },
            "remove_background": {
                "type": "boolean",
                "description": "Cut out the background. Writes a PNG with transparency.",
            },
            "upscale": {
                "type": "integer",
                "enum": [2, 4],
                "description": "Model enlarge, 2 or 4. scale stays arithmetic.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, workspace: WorkspaceRoots, *, output_dir: str | Path = "") -> None:
        self.workspace = workspace
        self._output_dir = Path(output_dir) if output_dir else None

    def confirm_detail(self, args: dict[str, Any]) -> str:
        from arelis.tools.image_models import allow_detail

        return allow_detail(args)

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
        overlay = str(kwargs.get("text") or "").strip()
        if overlay:
            overlay = overlay[:_MAX_OVERLAY_CHARS]
        align = str(kwargs.get("text_align") or "center").strip().lower()
        if overlay and align not in TEXT_ALIGNS:
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:image_edit] text_align must be one of "
                    f"{', '.join(TEXT_ALIGNS)}."
                ),
            )
        rotate = None
        if kwargs.get("rotate") is not None:
            try:
                rotate = float(kwargs.get("rotate"))
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False, output="[fail:image_edit] rotate must be a number of degrees."
                )
            if rotate != rotate:  # NaN
                return ToolResult(
                    ok=False, output="[fail:image_edit] rotate must be a number of degrees."
                )
            # Wrap into a sane range so 450 and 90 are the same ask.
            rotate = ((rotate + 180.0) % 360.0) - 180.0
            if abs(rotate) < 1e-6:
                rotate = None
        flip = str(kwargs.get("flip") or "").strip().lower()
        if flip:
            if flip in {"h", "mirror"}:
                flip = "horizontal"
            elif flip in {"v"}:
                flip = "vertical"
            if flip not in FLIP_MODES:
                return ToolResult(
                    ok=False,
                    output=(
                        f"[fail:image_edit] flip must be one of {', '.join(FLIP_MODES)}."
                    ),
                )
        else:
            flip = ""
        grayscale = bool(kwargs.get("grayscale"))
        invert = bool(kwargs.get("invert"))
        blur = None
        if kwargs.get("blur") is not None:
            try:
                blur = float(kwargs.get("blur"))
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False, output="[fail:image_edit] blur must be a number."
                )
            if blur != blur or blur <= 0:
                blur = None
            else:
                blur = max(0.3, min(20.0, blur))
        crop = str(kwargs.get("crop") or "").strip().lower()
        if crop:
            if crop not in CROP_SIDES:
                return ToolResult(
                    ok=False,
                    output=(
                        f"[fail:image_edit] crop must be one of {', '.join(CROP_SIDES)}."
                    ),
                )
        else:
            crop = ""
        try:
            crop_box = _parse_crop_box(kwargs.get("crop_box"))
        except ValueError as exc:
            return ToolResult(ok=False, output=f"[fail:image_edit] {exc}")
        scale = None
        if kwargs.get("scale") is not None:
            try:
                scale = float(kwargs.get("scale"))
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False, output="[fail:image_edit] scale must be a number."
                )
            if scale != scale:
                return ToolResult(
                    ok=False, output="[fail:image_edit] scale must be a number."
                )
            scale = max(_MIN_SCALE, min(_MAX_SCALE, scale))
            if abs(scale - 1.0) < 1e-6:
                scale = None
        pad = 0
        if kwargs.get("pad") is not None:
            try:
                pad = round(float(kwargs.get("pad")))
            except (TypeError, ValueError, OverflowError):
                return ToolResult(
                    ok=False, output="[fail:image_edit] pad must be a number of pixels."
                )
            pad = max(0, min(_MAX_PAD, pad))
        warmth = None
        if kwargs.get("warmth") is not None:
            try:
                warmth = float(kwargs.get("warmth"))
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False, output="[fail:image_edit] warmth must be a number."
                )
            if warmth != warmth:
                return ToolResult(
                    ok=False, output="[fail:image_edit] warmth must be a number."
                )
            warmth = max(-1.0, min(1.0, warmth))
            if abs(warmth) < 1e-6:
                warmth = None
        # 1b marks. Parsed here, applied in _edit. Keep this block together.
        try:
            marks = _read_marks(kwargs)
        except ValueError as exc:
            return ToolResult(ok=False, output=f"[fail:image_edit] {exc}")
        # Learned edits. One block so a parallel arithmetic change can rebase.
        remove_background = _truthy(kwargs.get("remove_background"))
        upscale = None
        if kwargs.get("upscale") is not None and kwargs.get("upscale") != "":
            try:
                upscale = int(kwargs.get("upscale"))
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False, output="[fail:image_edit] upscale must be 2 or 4."
                )
            if upscale not in (2, 4):
                return ToolResult(
                    ok=False, output="[fail:image_edit] upscale must be 2 or 4."
                )
        if remove_background:
            fmt_forced = "png"
        else:
            fmt_forced = ""
        if (
            size is None
            and not adjusting
            and not overlay
            and rotate is None
            and not flip
            and not grayscale
            and not invert
            and blur is None
            and not crop
            and crop_box is None
            and scale is None
            and not pad
            and warmth is None
            and not marks.active
            and not remove_background
            and upscale is None
        ):
            return ToolResult(
                ok=False,
                output=(
                    "[fail:image_edit] Nothing to change. Pass a size (width and "
                    "height, or preset=youtube_thumbnail), crop=, scale=2, pad=, "
                    "warmth=, an adjustment "
                    "(vibrance=1.3, contrast=1.1, brightness=1.1, sharpness=1.4), "
                    "rotate=, flip=horizontal, grayscale=true, blur=, "
                    "and/or text= to overlay glyphs. annotate=, scale_bar=, or "
                    "stretch=asinh also count. remove_background=true "
                    "cuts the background out. upscale=4 enlarges with a model."
                ),
            )

        fit = str(kwargs.get("fit") or "cover").strip().lower()
        if fit not in FIT_MODES:
            return ToolResult(
                ok=False,
                output=f"[fail:image_edit] fit must be one of {', '.join(FIT_MODES)}.",
            )
        if not fmt_forced:
            fmt = str(kwargs.get("format") or "png").strip().lower().lstrip(".")
        else:
            fmt = fmt_forced
        if fmt in {"jpeg"}:
            fmt = "jpg"
        if fmt not in {"png", "jpg"}:
            return ToolResult(
                ok=False, output="[fail:image_edit] format must be png or jpg."
            )

        try:
            result = await asyncio.to_thread(
                self._edit,
                source,
                size,
                adjusting,
                fit,
                fmt,
                overlay,
                align,
                rotate,
                flip,
                grayscale,
                invert,
                blur,
                crop,
                crop_box,
                scale,
                pad,
                warmth,
                marks,
                remove_background=remove_background,
                upscale=upscale,
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=f"[fail:image_edit] {exc}")
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
        overlay: str = "",
        align: str = "center",
        rotate: float | None = None,
        flip: str = "",
        grayscale: bool = False,
        invert: bool = False,
        blur: float | None = None,
        crop: str = "",
        crop_box: tuple[int, int, int, int] | None = None,
        scale: float | None = None,
        pad: int = 0,
        warmth: float | None = None,
        marks: _Marks | None = None,
        *,
        remove_background: bool = False,
        upscale: int | None = None,
    ) -> ToolResult:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

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
        if rotate is not None:
            frame = frame.rotate(-rotate, expand=True, resample=Image.BICUBIC)
            notes.append(f"rotated {rotate:g}°")
        if flip == "horizontal":
            frame = ImageOps.mirror(frame)
            notes.append("flipped horizontal")
        elif flip == "vertical":
            frame = ImageOps.flip(frame)
            notes.append("flipped vertical")
        if crop_box is not None:
            frame = _apply_crop_box(frame, crop_box)
            notes.append(
                f"cropped {crop_box[0]},{crop_box[1]}–{crop_box[2]},{crop_box[3]}"
            )
        elif crop:
            frame = _crop_side(frame, crop)
            notes.append(f"cropped {crop}")
        if size is not None and size != frame.size:
            frame, cropped = _fit_to(frame, size, fit)
        elif size == original and rotate is None and not crop and crop_box is None:
            notes.append(f"already {original[0]}x{original[1]}")
        if scale is not None:
            scaled_w = max(1, round(frame.width * scale))
            scaled_h = max(1, round(frame.height * scale))
            _reject_huge(scaled_w, scaled_h)
            if (scaled_w, scaled_h) != frame.size:
                frame = frame.resize((scaled_w, scaled_h), Image.LANCZOS)
            notes.append(f"scaled {scale:g}×")
        if pad:
            padded_w = frame.width + 2 * pad
            padded_h = frame.height + 2 * pad
            _reject_huge(padded_w, padded_h)
            frame = ImageOps.expand(frame, border=pad, fill=_pad_colour(frame.mode))
            notes.append(f"padded {pad}px")

        for key in _ADJUSTMENTS:
            if key not in factors:
                continue
            frame = enhancers[key](frame.convert("RGB") if key == "sharpness" else frame)
            frame = frame.enhance(factors[key])
        if warmth is not None:
            frame = _apply_warmth(frame, warmth)
            notes.append("warmer" if warmth > 0 else "cooler")

        if grayscale:
            alpha = frame.getchannel("A") if frame.mode == "RGBA" else None
            frame = ImageOps.grayscale(frame).convert("RGB")
            if alpha is not None:
                frame = frame.convert("RGBA")
                frame.putalpha(alpha)
            notes.append("grayscale")
        if invert:
            if frame.mode == "RGBA":
                rgb = ImageOps.invert(frame.convert("RGB"))
                alpha = frame.getchannel("A")
                frame = rgb.convert("RGBA")
                frame.putalpha(alpha)
            else:
                frame = ImageOps.invert(frame.convert("RGB"))
            notes.append("inverted")
        if blur is not None:
            frame = frame.filter(ImageFilter.GaussianBlur(radius=blur))
            notes.append(f"blur {blur:g}")

        # Learned edits stay after the arithmetic ones, in this one block.
        cosmetic = False
        if remove_background or upscale:
            frame, learned, cosmetic = _apply_learned(
                frame,
                source,
                remove_background=remove_background,
                upscale=upscale,
            )
            notes.extend(learned)

        # 1b: remap values in place, then draw marks on top. No resample.
        if marks is not None and marks.stretch:
            before_px = frame.size
            frame = _apply_stretch(frame, marks.stretch)
            if frame.size != before_px:
                raise ValueError("stretch must keep the pixel size.")
            notes.append(f"{marks.stretch} stretch, same size")

        if overlay:
            frame = _draw_overlay_text(frame, overlay, align)

        if marks is not None and (marks.items or marks.bar_length):
            frame = _draw_marks(frame, marks)
            if marks.items:
                notes.append(f"{len(marks.items)} marks")
            if marks.bar_length:
                notes.append(f"scale bar {marks.bar_length}px")

        directory = ensure(self.output_dir())
        parts = [source.stem]
        if size is not None:
            parts.append(f"{frame.width}x{frame.height}")
        if crop or crop_box is not None:
            parts.append("crop")
        if scale is not None:
            parts.append(f"scale{int(scale)}" if float(scale).is_integer() else "scale")
        if pad:
            parts.append("pad")
        if rotate is not None:
            parts.append(f"rot{int(rotate)}" if float(rotate).is_integer() else "rot")
        if flip:
            parts.append("flip")
        if grayscale:
            parts.append("gray")
        if invert:
            parts.append("invert")
        if blur is not None:
            parts.append("blur")
        if warmth is not None:
            parts.append("warm")
        if "vibrance" in factors:
            parts.append("vibrant" if factors["vibrance"] > 1 else "muted")
        if overlay:
            parts.append("text")
        if marks is not None and marks.stretch:
            parts.append(marks.stretch)
        if marks is not None and marks.items:
            parts.append("annotate")
        if marks is not None and marks.bar_length:
            parts.append("bar")
        if remove_background:
            parts.append("nobg")
        if upscale:
            parts.append(f"x{upscale}")
        suffix = ".png" if fmt == "png" else ".jpg"
        if fmt == "jpg" and frame.mode != "RGB":
            frame = frame.convert("RGB")
        dest = _unique_dest(directory, "-".join(parts), suffix)
        save_args: dict[str, Any] = {}
        if fmt == "jpg":
            save_args = {"quality": 92, "optimize": True}
        frame.save(dest, **save_args)
        if cosmetic:
            from arelis.tools.image_upscale import mark_cosmetic

            mark_cosmetic(dest)

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
        if overlay:
            shown = overlay if len(overlay) <= 40 else overlay[:39] + "…"
            changes.append(f'{align} text "{shown}"')
        changes.extend(notes)

        rel = display_path(dest)
        return ToolResult(
            ok=True,
            output=f"Saved {rel}, {', '.join(changes)}.",
            data={
                "path": rel,
                "abs_path": str(dest),
                "source": display_path(source),
                "source_px": [original[0], original[1]],
                "result_px": [frame.width, frame.height],
                "cropped": cropped,
                "fit": fit,
                "adjustments": {k: round(v, 3) for k, v in factors.items()},
                "text": overlay,
                "text_align": align if overlay else "",
                "stretch": "" if marks is None else marks.stretch,
                "annotate": 0 if marks is None else len(marks.items),
                "scale_bar": (
                    "" if marks is None or not marks.bar_length else marks.bar_label
                ),
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


def _crop_side(frame: Any, side: str) -> Any:
    """Keep the named half. center is the middle 50% on both axes."""
    width, height = frame.size
    keep_w = max(1, width // 2)
    keep_h = max(1, height // 2)
    if side == "left":
        return frame.crop((0, 0, keep_w, height))
    if side == "right":
        return frame.crop((width - keep_w, 0, width, height))
    if side == "top":
        return frame.crop((0, 0, width, keep_h))
    if side == "bottom":
        return frame.crop((0, height - keep_h, width, height))
    left = (width - keep_w) // 2
    top = (height - keep_h) // 2
    return frame.crop((left, top, left + keep_w, top + keep_h))


def _apply_crop_box(frame: Any, box: tuple[int, int, int, int]) -> Any:
    left, top, right, bottom = box
    width, height = frame.size
    if left < 0 or top < 0 or right > width or bottom > height or right <= left or bottom <= top:
        raise ValueError(
            f"crop_box {left},{top},{right},{bottom} is outside the image "
            f"({width}x{height})."
        )
    return frame.crop(box)


def _apply_warmth(frame: Any, warmth: float) -> Any:
    """More red and less blue when warm; the reverse when cool."""
    from PIL import Image

    lift = round(warmth * _WARMTH_LIFT)
    if lift == 0:
        return frame
    warmer = [max(0, min(255, i + lift)) for i in range(256)]
    cooler = [max(0, min(255, i - lift)) for i in range(256)]
    if frame.mode == "RGBA":
        red, green, blue, alpha = frame.split()
        return Image.merge(
            "RGBA", (red.point(warmer), green, blue.point(cooler), alpha)
        )
    red, green, blue = frame.convert("RGB").split()
    out = Image.merge("RGB", (red.point(warmer), green, blue.point(cooler)))
    return out


def overlay_font_paths() -> tuple[Path, ...]:
    """Desk face first (Zen Kaku Bold), then IBM Plex. Arial is a last resort."""
    bundled = Path(__file__).resolve().parents[1] / "ui" / "fonts"
    return (
        bundled / "ZenKakuGothicNew-Bold.ttf",
        bundled / "ZenKakuGothicNew-Regular.ttf",
        bundled / "IBMPlexSans-SemiBold.ttf",
        bundled / "IBMPlexSans-Regular.ttf",
        Path(r"C:\Windows\Fonts\segoeuib.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    )


def _load_overlay_font(size: int) -> Any:
    from PIL import ImageFont

    for path in overlay_font_paths():
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _ink(mode: str, rgb: tuple[int, int, int]) -> Any:
    return (*rgb, 255) if mode == "RGBA" else rgb


def _draw_overlay_text(frame: Any, text: str, align: str) -> Any:
    """Stamp paper glyphs with a room-dark stroke so they read on any background."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(frame)
    width, height = frame.size
    target_w = max(32, int(width * 0.55))
    lo, hi = 12, max(24, int(min(width, height) * 0.22))
    best = _load_overlay_font(hi)
    while lo <= hi:
        mid = (lo + hi) // 2
        cand = _load_overlay_font(mid)
        bbox = draw.textbbox((0, 0), text, font=cand)
        if (bbox[2] - bbox[0]) <= target_w:
            best = cand
            lo = mid + 1
        else:
            hi = mid - 1
    bbox = draw.textbbox((0, 0), text, font=best)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (width - text_w) // 2 - bbox[0]
    if align == "top":
        y = int(height * 0.12) - bbox[1]
    elif align == "bottom":
        y = int(height * 0.88) - text_h - bbox[1]
    else:
        y = (height - text_h) // 2 - bbox[1]
    size = int(getattr(best, "size", 24) or 24)
    stroke = max(2, size // 16)
    draw.text(
        (x, y),
        text,
        font=best,
        fill=_ink(frame.mode, (248, 241, 234)),
        stroke_width=stroke,
        stroke_fill=_ink(frame.mode, (16, 13, 11)),
    )
    return frame


# --- 1b marks: annotate, scale_bar, stretch. Keep this block together. ---

_MARK_KINDS = ("arrow", "box", "label")
_STRETCHES = ("linear", "asinh", "log", "zscale")
_MAX_MARKS = 40
_MAX_MARK_TEXT = 80


class _Marks:
    """Parsed annotate / scale_bar / stretch. Inactive when the caller sent none."""

    def __init__(
        self,
        items: tuple[dict[str, Any], ...],
        bar_length: int | None,
        bar_label: str,
        stretch: str,
    ) -> None:
        self.items = items
        self.bar_length = bar_length
        self.bar_label = bar_label
        self.stretch = stretch

    @property
    def active(self) -> bool:
        return bool(self.items or self.bar_length or self.stretch)


def _pixel(value: Any, name: str) -> int:
    if isinstance(value, bool) or value is None or value == "":
        raise ValueError(f"{name} must be a pixel number.")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a pixel number.") from None
    if number < 0:
        raise ValueError(f"{name} must be zero or more.")
    return number


def _first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def _load_json(raw: str, what: str) -> Any:
    import json

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(what) from None


def _one_mark(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError(f"annotate item {index} must be an object.")
    kind = str(item.get("kind") or item.get("type") or "").strip().lower()
    if kind not in _MARK_KINDS:
        raise ValueError(f"annotate item {index} kind must be arrow, box, or label.")
    x = _pixel(_first(item, "x", "left"), f"annotate item {index} x")
    y = _pixel(_first(item, "y", "top"), f"annotate item {index} y")
    if kind == "label":
        text = str(item.get("text") or "").replace("\n", " ").strip()
        if not text:
            raise ValueError(f"annotate item {index} needs text.")
        return {"kind": "label", "x": x, "y": y, "text": text[:_MAX_MARK_TEXT]}
    x2 = _pixel(_first(item, "x2", "right"), f"annotate item {index} x2")
    y2 = _pixel(_first(item, "y2", "bottom"), f"annotate item {index} y2")
    if kind == "box" and (x2 <= x or y2 <= y):
        raise ValueError(f"annotate item {index} box needs x < x2 and y < y2.")
    if kind == "arrow" and x == x2 and y == y2:
        raise ValueError(f"annotate item {index} arrow needs two different points.")
    return {"kind": kind, "x": x, "y": y, "x2": x2, "y2": y2}


def _read_annotate(raw: Any) -> list[dict[str, Any]]:
    if raw is None or raw == "" or raw == []:
        return []
    if isinstance(raw, str):
        raw = _load_json(raw, "annotate must be a list of arrow, box, and label items.")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("annotate must be a list of arrow, box, and label items.")
    if len(raw) > _MAX_MARKS:
        raise ValueError(f"annotate takes at most {_MAX_MARKS} items.")
    return [_one_mark(item, index) for index, item in enumerate(raw, start=1)]


def _read_scale_bar(raw: Any) -> tuple[int | None, str]:
    if raw is None or raw == "" or raw == []:
        return None, ""
    if raw == {}:
        raise ValueError("scale_bar needs a length in pixels and a label.")
    if isinstance(raw, str):
        raw = _load_json(raw, "scale_bar needs a length in pixels and a label.")
    label = ""
    length_raw: Any = None
    if isinstance(raw, dict):
        length_raw = _first(raw, "length", "px")
        label = str(raw.get("label") or raw.get("text") or "").strip()
    elif isinstance(raw, (list, tuple)):
        if not raw:
            raise ValueError("scale_bar needs a length in pixels and a label.")
        length_raw = raw[0]
        if len(raw) > 1 and raw[1] is not None:
            label = str(raw[1]).strip()
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        length_raw = raw
    else:
        raise ValueError("scale_bar needs a length in pixels and a label.")
    length = _pixel(length_raw, "scale_bar length")
    if length < 1:
        raise ValueError("scale_bar length must be at least 1 pixel.")
    if length > _MAX_EDGE:
        raise ValueError("scale_bar length is too long.")
    label = label.replace("\n", " ").strip()
    if not label:
        label = f"{length} px"
    return length, label[:_MAX_MARK_TEXT]


def _read_stretch(raw: Any) -> str:
    if raw is None or raw == "" or raw is False:
        return ""
    mode = str(raw).strip().lower()
    if mode in {"none", "off"}:
        return ""
    if mode not in _STRETCHES:
        raise ValueError("stretch must be linear, asinh, log, or zscale.")
    return mode


def _read_marks(kwargs: dict[str, Any]) -> _Marks:
    items = _read_annotate(kwargs.get("annotate"))
    length, label = _read_scale_bar(kwargs.get("scale_bar"))
    stretch = _read_stretch(kwargs.get("stretch"))
    return _Marks(tuple(items), length, label, stretch)


def _apply_stretch(frame: Any, mode: str) -> Any:
    """Pointwise display stretch. The array shape is the pixel grid, unchanged."""
    import numpy as np
    from PIL import Image

    try:
        from astropy.visualization import (
            AsinhStretch,
            ImageNormalize,
            LinearStretch,
            LogStretch,
            ZScaleInterval,
        )
    except ImportError:
        raise ValueError(
            "stretch needs astropy, which is not installed in this copy."
        ) from None

    alpha = frame.getchannel("A") if frame.mode == "RGBA" else None
    values = np.asarray(frame.convert("RGB"), dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return frame
    lo = float(finite.min())
    hi = float(finite.max())
    if hi <= lo:
        return frame

    if mode == "zscale":
        sample = values.mean(axis=-1)
        vmin, vmax = ZScaleInterval().get_limits(sample)
        if not np.isfinite(vmin) or not np.isfinite(vmax) or float(vmax) <= float(vmin):
            vmin, vmax = lo, hi
        norm = ImageNormalize(
            values, vmin=float(vmin), vmax=float(vmax), stretch=LinearStretch()
        )
    else:
        stretches = {
            "linear": LinearStretch(),
            "asinh": AsinhStretch(),
            "log": LogStretch(),
        }
        norm = ImageNormalize(values, vmin=lo, vmax=hi, stretch=stretches[mode])
    scaled = np.asarray(norm(values), dtype=np.float64)
    scaled = np.nan_to_num(scaled, nan=0.0, posinf=1.0, neginf=0.0)
    scaled = np.clip(np.rint(scaled * 255.0), 0, 255).astype(np.uint8)
    if scaled.shape != values.shape:
        raise ValueError("stretch must keep the pixel size.")
    out = Image.fromarray(scaled, mode="RGB")
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out


def _require_inside(width: int, height: int, x: int, y: int, name: str) -> None:
    if x >= width or y >= height:
        raise ValueError(f"{name} at {x},{y} is outside the {width}x{height} image.")


def _draw_arrow(draw: Any, item: dict[str, Any], mode: str, weight: int) -> None:
    import math

    x1, y1 = int(item["x"]), int(item["y"])
    x2, y2 = int(item["x2"]), int(item["y2"])
    ink = _ink(mode, (248, 241, 234))
    edge = _ink(mode, (16, 13, 11))
    draw.line((x1, y1, x2, y2), fill=edge, width=weight + 2)
    draw.line((x1, y1, x2, y2), fill=ink, width=weight)
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    head = max(8, weight * 4)
    px, py = -uy, ux
    tip = (x2, y2)
    left = (x2 - ux * head + px * head * 0.45, y2 - uy * head + py * head * 0.45)
    right = (x2 - ux * head - px * head * 0.45, y2 - uy * head - py * head * 0.45)
    draw.polygon((tip, left, right), fill=edge)
    inset = max(1, weight // 2)
    draw.polygon(
        (
            tip,
            (left[0] + ux * inset, left[1] + uy * inset),
            (right[0] + ux * inset, right[1] + uy * inset),
        ),
        fill=ink,
    )


def _draw_label(draw: Any, frame: Any, item: dict[str, Any]) -> None:
    text = str(item["text"])
    size = max(14, min(frame.size) // 18)
    font = _load_overlay_font(size)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = int(item["x"]) - bbox[0]
    y = int(item["y"]) - bbox[1]
    stroke = max(2, size // 16)
    draw.text(
        (x, y),
        text,
        font=font,
        fill=_ink(frame.mode, (248, 241, 234)),
        stroke_width=stroke,
        stroke_fill=_ink(frame.mode, (16, 13, 11)),
    )


def _draw_scale_bar(draw: Any, frame: Any, length: int, label: str) -> None:
    width, height = frame.size
    margin = max(8, min(28, width // 16, height // 16))
    if length > width - 2 * margin:
        raise ValueError(
            f"scale bar of {length}px does not fit in a {width}px wide image."
        )
    bar_h = max(4, min(width, height) // 80)
    x0 = margin
    y0 = height - margin - bar_h
    edge = _ink(frame.mode, (16, 13, 11))
    ink = _ink(frame.mode, (248, 241, 234))
    draw.rectangle((x0 - 1, y0 - 1, x0 + length + 1, y0 + bar_h + 1), fill=edge)
    draw.rectangle((x0, y0, x0 + length, y0 + bar_h), fill=ink)
    size = max(12, min(width, height) // 22)
    font = _load_overlay_font(size)
    bbox = draw.textbbox((0, 0), label, font=font)
    text_h = bbox[3] - bbox[1]
    text_x = x0 - bbox[0]
    text_y = y0 - text_h - 4 - bbox[1]
    if text_y < 2:
        text_y = 2
    draw.text(
        (text_x, text_y),
        label,
        font=font,
        fill=ink,
        stroke_width=max(1, size // 16),
        stroke_fill=edge,
    )


def _draw_marks(frame: Any, marks: _Marks) -> Any:
    from PIL import ImageDraw

    width, height = frame.size
    draw = ImageDraw.Draw(frame)
    weight = max(2, min(width, height) // 120)
    for index, item in enumerate(marks.items, start=1):
        kind = item["kind"]
        name = f"annotate item {index}"
        _require_inside(width, height, int(item["x"]), int(item["y"]), name)
        if kind == "label":
            _draw_label(draw, frame, item)
            continue
        _require_inside(width, height, int(item["x2"]), int(item["y2"]), name)
        if kind == "box":
            draw.rectangle(
                (item["x"], item["y"], item["x2"], item["y2"]),
                outline=_ink(frame.mode, (16, 13, 11)),
                width=weight + 2,
            )
            draw.rectangle(
                (item["x"], item["y"], item["x2"], item["y2"]),
                outline=_ink(frame.mode, (248, 241, 234)),
                width=weight,
            )
            continue
        _draw_arrow(draw, item, frame.mode, weight)
    if marks.bar_length:
        _draw_scale_bar(draw, frame, marks.bar_length, marks.bar_label)
    if frame.size != (width, height):
        raise ValueError("marks must keep the pixel size.")
    return frame
