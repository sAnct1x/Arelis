from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

import httpx

from arelis.paths import display_path
from arelis.tools.base import ToolResult
from arelis.tools.comfy_client import (
    ASPECT_RATIOS,
    DEFAULT_CHECKPOINT,
    DEFAULT_NEGATIVE,
    STYLE_PRESETS,
    apply_style,
    clamp_size,
    fetch_image,
    img2img_workflow,
    inpaint_workflow,
    list_checkpoints,
    long_edge_for,
    pick_checkpoint,
    queue_workflow,
    size_for_aspect,
    snap_px,
    txt2img_workflow,
    upload_image,
    wait_for_image,
)
from arelis.tools.comfy_lifecycle import (
    discover_comfy,
    ensure_comfy_running,
    schedule_comfy_idle_stop,
)
from arelis.tools.image_copy import image_progress_line
from arelis.tools.image_meta import write_sidecar
from arelis.workspace import WorkspaceRoots

# Seeds are drawn from this range so a run is reproducible: the value used is
# echoed back in ToolResult.data, and passing it again as the seed argument
# reproduces the image. 2**31 keeps it inside what ComfyUI accepts.
_SEED_SPACE = 2**31

MASK_REGIONS = ("left", "right", "top", "bottom", "center")
OUTPAINT_DIRS = ("left", "right", "up", "down", "all")
REMBG_MISSING = "[fail:image] Background remove needs rembg (pip install rembg)."

# Kept as a name the error text and older notes still point at. The live
# tool builds a workflow per call so size / style / img2img can change.
DEFAULT_WORKFLOW = txt2img_workflow(
    prompt="PROMPT",
    negative="ugly, blurry",
    width=512,
    height=512,
    seed=0,
    checkpoint=DEFAULT_CHECKPOINT,
    steps=20,
    cfg=7,
)


def clamp_n(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, min(4, parsed))


def mask_from_region(width: int, height: int, region: str) -> Any:
    """White = change, black = keep. Sides ~40%; center is 50%."""
    from PIL import Image, ImageDraw

    key = (region or "").strip().lower()
    if key not in MASK_REGIONS:
        known = ", ".join(MASK_REGIONS)
        raise ValueError(f"Unknown mask_region `{region}`. Known: {known}.")
    mask = Image.new("L", (int(width), int(height)), 0)
    draw = ImageDraw.Draw(mask)
    w, h = int(width), int(height)
    if key == "left":
        draw.rectangle([0, 0, max(0, int(w * 0.4) - 1), h - 1], fill=255)
    elif key == "right":
        draw.rectangle([int(w * 0.6), 0, w - 1, h - 1], fill=255)
    elif key == "top":
        draw.rectangle([0, 0, w - 1, max(0, int(h * 0.4) - 1)], fill=255)
    elif key == "bottom":
        draw.rectangle([0, int(h * 0.6), w - 1, h - 1], fill=255)
    else:
        x0, y0 = w // 4, h // 4
        draw.rectangle([x0, y0, x0 + w // 2 - 1, y0 + h // 2 - 1], fill=255)
    return mask


def mask_from_box(width: int, height: int, box: list[Any]) -> Any:
    from PIL import Image, ImageDraw

    if len(box) != 4:
        raise ValueError("mask_box must be [x, y, w, h] in source pixels.")
    x, y, box_w, box_h = (int(v) for v in box)
    mask = Image.new("L", (int(width), int(height)), 0)
    ImageDraw.Draw(mask).rectangle(
        [x, y, x + max(0, box_w) - 1, y + max(0, box_h) - 1], fill=255
    )
    return mask


def pad_for_outpaint(source: Any, direction: str) -> tuple[Any, Any]:
    """Grow the canvas ~25% and mask only the pad so original pixels stay."""
    from PIL import Image, ImageDraw

    key = (direction or "").strip().lower()
    if key not in OUTPAINT_DIRS:
        known = ", ".join(OUTPAINT_DIRS)
        raise ValueError(f"Unknown outpaint `{direction}`. Known: {known}.")
    if isinstance(source, (str, Path)):
        with Image.open(source) as opened:
            rgb = opened.convert("RGB")
    else:
        rgb = source.convert("RGB")
    w, h = rgb.size
    pad_w = snap_px(max(8, round(w * 0.25)))
    pad_h = snap_px(max(8, round(h * 0.25)))
    left = pad_w if key in {"left", "all"} else 0
    right = pad_w if key in {"right", "all"} else 0
    top = pad_h if key in {"up", "all"} else 0
    bottom = pad_h if key in {"down", "all"} else 0
    canvas = Image.new("RGB", (w + left + right, h + top + bottom), (0, 0, 0))
    canvas.paste(rgb, (left, top))
    mask = Image.new("L", canvas.size, 255)
    ImageDraw.Draw(mask).rectangle(
        [left, top, left + w - 1, top + h - 1], fill=0
    )
    return canvas, mask


def upscale_png(path: Path, factor: int = 2) -> Path:
    from PIL import Image

    with Image.open(path) as opened:
        frame = opened.copy()
    out = frame.resize(
        (max(1, frame.width * factor), max(1, frame.height * factor)),
        Image.LANCZOS,
    )
    out.save(path)
    return path


def rembg_cut(path: Path) -> Path:
    try:
        from rembg import remove as rembg_remove
    except ImportError:
        raise RuntimeError(REMBG_MISSING) from None
    from PIL import Image

    with Image.open(path) as opened:
        cut = rembg_remove(opened)
    if isinstance(cut, (bytes, bytearray)):
        path.write_bytes(cut)
    else:
        cut.save(path, format="PNG")
    return path


def _png_bytes(frame: Any, name: str) -> tuple[bytes, str]:
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    return buffer.getvalue(), name


def _prepare_img2img_bytes(source: Path, width: int, height: int) -> tuple[bytes, str]:
    """Resize to the sampler size so the latent matches what was asked for."""
    from PIL import Image

    with Image.open(source) as opened:
        frame = opened.convert("RGB")
        if frame.size != (width, height):
            frame = frame.resize((width, height), Image.LANCZOS)
        return _png_bytes(frame, f"{source.stem}-src.png")


def _mask_rgb_bytes(mask_l: Any, name: str) -> tuple[bytes, str]:
    from PIL import Image

    rgb = Image.new("RGB", mask_l.size, (0, 0, 0))
    rgb.paste(mask_l.convert("RGB"))
    return _png_bytes(rgb, name)


class ImageTool:
    name = "image"
    description = (
        "Generate pixels via local ComfyUI, or restyle an existing image "
        "(img2img) when you pass path. "
        "A discoverable local ComfyUI install is started on the first call. "
        "The finished file is saved for the Workspace panel. "
        "Args: prompt; optional negative/width/height/seed/aspect/style/steps/cfg; "
        "n (1–4 variations, different seeds); upscale=2 (LANCZOS 2×); "
        "path + optional denoise to restyle; "
        "mask_region or mask_box to inpaint; outpaint to grow a side; "
        "remove_background (needs rembg). "
        "aspect is square, landscape, portrait, 16:9, 9:16, 4:3, 3:2, 21:9. "
        "style is photoreal, illustration, anime, watercolor, oil, sketch, cinematic. "
        "This cannot do an exact resize, crop, rotate, or text overlay — those have "
        "a right answer and belong on image_edit. Using this to 'resize' a file "
        "returns a different picture. To look at one use vision."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Positive image prompt"},
            "negative": {"type": "string", "description": "Negative prompt"},
            "width": {"type": "integer", "description": "Width in pixels"},
            "height": {"type": "integer", "description": "Height in pixels"},
            "aspect": {
                "type": "string",
                "enum": sorted(ASPECT_RATIOS),
                "description": "Named shape. Ignored when width and height are given.",
            },
            "style": {
                "type": "string",
                "enum": sorted(STYLE_PRESETS),
                "description": "Look to fold into the prompt.",
            },
            "seed": {"type": "integer", "description": "Sampler seed"},
            "steps": {"type": "integer", "description": "Sampler steps (default from config)."},
            "cfg": {"type": "number", "description": "Classifier-free guidance."},
            "n": {
                "type": "integer",
                "description": "Variations (1–4). Sequential jobs, different seeds.",
            },
            "upscale": {
                "type": "integer",
                "enum": [2],
                "description": "2 = Pillow LANCZOS 2× on each result. No extra model.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Existing local image to restyle (img2img), inpaint, or outpaint. "
                    "Required for 'make this look like a watercolor' / 'in the style of'."
                ),
            },
            "denoise": {
                "type": "number",
                "description": (
                    "How far img2img/inpaint may wander from the source. 0.35 keeps the "
                    "composition, 0.55 is a restyle, 0.75 is the inpaint default."
                ),
            },
            "mask_region": {
                "type": "string",
                "enum": list(MASK_REGIONS),
                "description": "Inpaint this side or the center (white=change).",
            },
            "mask_box": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 4,
                "maxItems": 4,
                "description": "Inpaint box [x, y, w, h] in source pixels.",
            },
            "outpaint": {
                "type": "string",
                "enum": list(OUTPAINT_DIRS),
                "description": "Grow the canvas on this side (or all) and inpaint the pad.",
            },
            "remove_background": {
                "type": "boolean",
                "description": "Cut the background (needs rembg). PNG with alpha.",
            },
        },
        "required": ["prompt"],
    }

    def __init__(
        self,
        comfy_url: str,
        output_dir: str,
        *,
        # Starting a program on someone's machine is not a thing to do by
        # omission. The shipped config says false; discovering a Comfy folder
        # is the other grant.
        auto_start: bool = False,
        launch_command: str = "",
        launch_cwd: str = "",
        startup_timeout_s: float = 120.0,
        workspace: WorkspaceRoots | None = None,
        checkpoint: str = "",
        default_width: int = 768,
        default_height: int = 768,
        steps: int = 25,
        cfg: float = 7.0,
        sampler: str = "euler",
        default_n: int = 1,
        on_progress: Any = None,
    ) -> None:
        self.comfy_url = comfy_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.auto_start = auto_start
        self.launch_command = launch_command
        self.launch_cwd = launch_cwd
        self.startup_timeout_s = startup_timeout_s
        self.workspace = workspace
        self.checkpoint = (checkpoint or "").strip()
        self.default_width = int(default_width)
        self.default_height = int(default_height)
        self.steps = int(steps)
        self.cfg = float(cfg)
        self.sampler = (sampler or "euler").strip() or "euler"
        self.default_n = clamp_n(default_n, 1)
        self._on_progress = on_progress

    def set_progress(self, fn: Any) -> None:
        """Optional ``fn(line)`` for the composer shimmer while Comfy samples."""
        self._on_progress = fn

    def _note(self, line: str) -> None:
        cb = self._on_progress
        if cb is None:
            return
        try:
            cb(line)
        except Exception:
            pass

    def _resolve_source(self, path_str: str) -> Path:
        from arelis.tools.image_io import resolve_image

        return resolve_image(self.workspace, path_str)

    def _resolve_size(
        self,
        kwargs: dict[str, Any],
        checkpoint: str,
        source: Path | None,
    ) -> tuple[int, int]:
        width = kwargs.get("width")
        height = kwargs.get("height")
        if width is not None or height is not None:
            if width is None or height is None:
                raise ValueError(
                    "Give both width and height, or an aspect. A single "
                    "dimension is ambiguous."
                )
            return clamp_size(int(width), int(height))
        aspect = str(kwargs.get("aspect") or "").strip()
        edge = long_edge_for(checkpoint)
        if aspect:
            return size_for_aspect(aspect, edge)
        if source is not None:
            from PIL import Image

            with Image.open(source) as opened:
                src_w, src_h = opened.size
            scale = min(1.0, edge / float(max(src_w, src_h)))
            return clamp_size(
                snap_px(round(src_w * scale)),
                snap_px(round(src_h * scale)),
            )
        return clamp_size(self.default_width, self.default_height)

    def _launch_target(self) -> tuple[str, bool]:
        cwd = (self.launch_cwd or "").strip()
        if cwd:
            return cwd, self.auto_start
        found = discover_comfy()
        if found is not None:
            return str(found), True
        return "", self.auto_start

    async def _upload_bytes(
        self, client: httpx.AsyncClient, data: bytes, name: str
    ) -> str:
        tmp = self.output_dir / name
        tmp.write_bytes(data)
        try:
            return await upload_image(client, self.comfy_url, tmp)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    def _write_meta(
        self,
        local_path: Path,
        *,
        prompt: str,
        negative: str,
        seed: int,
        checkpoint: str,
        width: int,
        height: int,
        style: str,
        mode: str,
        source: str,
        denoise: float,
        n: int,
    ) -> None:
        write_sidecar(
            local_path,
            prompt=prompt,
            negative=negative,
            seed=seed,
            checkpoint=checkpoint,
            width=width,
            height=height,
            style=style,
            mode=mode,
            source=source,
            denoise=denoise,
            n=n,
        )

    def _finish_pixels(
        self,
        local_path: Path,
        *,
        upscale: bool,
        remove_bg: bool,
    ) -> tuple[Path, int, int]:
        if upscale:
            local_path = upscale_png(local_path, 2)
        if remove_bg:
            local_path = rembg_cut(local_path)
        from PIL import Image

        with Image.open(local_path) as opened:
            width, height = opened.size
        return local_path, width, height

    async def run(self, **kwargs: Any) -> ToolResult:
        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(ok=False, output="Missing prompt")
        negative = str(kwargs.get("negative") or DEFAULT_NEGATIVE)
        seed = int(kwargs.get("seed", uuid.uuid4().int % _SEED_SPACE))
        steps = int(kwargs.get("steps") or self.steps)
        cfg = float(kwargs.get("cfg") if kwargs.get("cfg") is not None else self.cfg)
        style = str(kwargs.get("style") or "").strip()
        path_str = str(kwargs.get("path") or "").strip()
        denoise_raw = kwargs.get("denoise")
        n = clamp_n(kwargs.get("n"), self.default_n)
        upscale = int(kwargs.get("upscale") or 0) == 2
        remove_bg = bool(kwargs.get("remove_background"))
        mask_region = str(kwargs.get("mask_region") or "").strip().lower()
        outpaint = str(kwargs.get("outpaint") or "").strip().lower()
        mask_box = kwargs.get("mask_box")

        try:
            prompt, negative = apply_style(prompt, negative, style)
        except ValueError as exc:
            return ToolResult(ok=False, output=f"[fail:image] {exc}")

        source: Path | None = None
        if path_str:
            try:
                source = self._resolve_source(path_str)
            except (ValueError, PermissionError, FileNotFoundError) as exc:
                return ToolResult(ok=False, output=f"[fail:image] {exc}")

        if mask_box is not None and not isinstance(mask_box, (list, tuple)):
            return ToolResult(
                ok=False, output="[fail:image] mask_box must be [x, y, w, h]."
            )
        if mask_region and mask_region not in MASK_REGIONS:
            known = ", ".join(MASK_REGIONS)
            return ToolResult(
                ok=False,
                output=f"[fail:image] Unknown mask_region `{mask_region}`. Known: {known}.",
            )
        if outpaint and outpaint not in OUTPAINT_DIRS:
            known = ", ".join(OUTPAINT_DIRS)
            return ToolResult(
                ok=False,
                output=f"[fail:image] Unknown outpaint `{outpaint}`. Known: {known}.",
            )
        if (mask_region or mask_box is not None or outpaint) and source is None:
            return ToolResult(
                ok=False,
                output="[fail:image] Inpaint and outpaint need path= to the source image.",
            )
        if remove_bg:
            try:
                from rembg import remove as _rembg_probe
            except ImportError:
                return ToolResult(ok=False, output=REMBG_MISSING)
            del _rembg_probe

        rembg_only = (
            remove_bg
            and source is not None
            and not mask_region
            and mask_box is None
            and not outpaint
            and denoise_raw is None
            and not style
        )
        source_label = display_path(source) if source else ""

        if rembg_only:
            assert source is not None
            dest = self.output_dir / f"{source.stem}-nobg.png"
            dest.write_bytes(source.read_bytes())
            try:
                dest = rembg_cut(dest)
            except RuntimeError as exc:
                return ToolResult(ok=False, output=str(exc))
            from PIL import Image

            with Image.open(dest) as opened:
                width, height = opened.size
            self._write_meta(
                dest,
                prompt=prompt,
                negative=negative,
                seed=seed,
                checkpoint="",
                width=width,
                height=height,
                style=style,
                mode="remove_bg",
                source=source_label,
                denoise=0.0,
                n=1,
            )
            return ToolResult(
                ok=True,
                output=f"Background removed, saved to {dest}.",
                data={
                    "path": str(dest),
                    "paths": [str(dest)],
                    "seed": seed,
                    "width": width,
                    "height": height,
                    "style": style,
                    "source": source_label,
                    "mode": "remove_bg",
                    "n": 1,
                },
            )

        launch_cwd, auto_start = self._launch_target()
        try:
            boot_error = await ensure_comfy_running(
                self.comfy_url,
                launch_command=self.launch_command,
                launch_cwd=launch_cwd,
                startup_timeout_s=self.startup_timeout_s,
                auto_start=auto_start,
            )
            if boot_error:
                return ToolResult(
                    ok=False,
                    output=f"[fail:image] {boot_error}",
                )

            async with httpx.AsyncClient(timeout=120) as client:
                available = await list_checkpoints(client, self.comfy_url)
                checkpoint = pick_checkpoint(available, self.checkpoint)
                try:
                    width, height = self._resolve_size(kwargs, checkpoint, source)
                except ValueError as exc:
                    return ToolResult(ok=False, output=f"[fail:image] {exc}")

                mode = "txt2img"
                denoise = 1.0
                image_name = ""
                mask_name = ""
                work_w, work_h = width, height

                if source is not None and outpaint:
                    mode = "outpaint"
                    denoise = 0.75 if denoise_raw is None else float(denoise_raw)
                    try:
                        canvas, mask = pad_for_outpaint(source, outpaint)
                    except ValueError as exc:
                        return ToolResult(ok=False, output=f"[fail:image] {exc}")
                    work_w, work_h = canvas.size
                    try:
                        payload, upload_name = _png_bytes(canvas, f"{source.stem}-out.png")
                        image_name = await self._upload_bytes(client, payload, upload_name)
                        mask_payload, mask_upload = _mask_rgb_bytes(
                            mask, f"{source.stem}-outmask.png"
                        )
                        mask_name = await self._upload_bytes(client, mask_payload, mask_upload)
                    except Exception as exc:
                        return ToolResult(
                            ok=False,
                            output=f"[fail:image] Could not prepare outpaint: {exc}",
                        )
                elif source is not None and (mask_region or mask_box is not None):
                    mode = "inpaint"
                    denoise = 0.75 if denoise_raw is None else float(denoise_raw)
                    from PIL import Image

                    try:
                        with Image.open(source) as opened:
                            src_w, src_h = opened.size
                            if mask_box is not None:
                                mask = mask_from_box(src_w, src_h, list(mask_box))
                                rgb = opened.convert("RGB")
                                if rgb.size != (width, height):
                                    rgb = rgb.resize((width, height), Image.LANCZOS)
                                    mask = mask.resize((width, height), Image.NEAREST)
                            else:
                                rgb = opened.convert("RGB")
                                if rgb.size != (width, height):
                                    rgb = rgb.resize((width, height), Image.LANCZOS)
                                mask = mask_from_region(rgb.width, rgb.height, mask_region)
                        work_w, work_h = rgb.size
                        payload, upload_name = _png_bytes(rgb, f"{source.stem}-src.png")
                        image_name = await self._upload_bytes(client, payload, upload_name)
                        mask_payload, mask_upload = _mask_rgb_bytes(
                            mask, f"{source.stem}-mask.png"
                        )
                        mask_name = await self._upload_bytes(client, mask_payload, mask_upload)
                    except Exception as exc:
                        return ToolResult(
                            ok=False,
                            output=f"[fail:image] Could not read {display_path(source)}: {exc}",
                        )
                elif source is not None:
                    mode = "img2img"
                    denoise = 0.55 if denoise_raw is None else float(denoise_raw)
                    try:
                        payload, upload_name = _prepare_img2img_bytes(
                            source, width, height
                        )
                        image_name = await self._upload_bytes(client, payload, upload_name)
                    except Exception as exc:
                        return ToolResult(
                            ok=False,
                            output=f"[fail:image] Could not read {display_path(source)}: {exc}",
                        )

                paths: list[str] = []
                seeds: list[int] = []
                last_prompt_id = ""
                out_w, out_h = work_w, work_h

                for index in range(n):
                    job_seed = (seed + index) % _SEED_SPACE
                    self._note(image_progress_line(index=index + 1, n=n))
                    if mode in {"inpaint", "outpaint"}:
                        workflow = inpaint_workflow(
                            prompt=prompt,
                            negative=negative,
                            seed=job_seed,
                            checkpoint=checkpoint,
                            image_name=image_name,
                            mask_name=mask_name,
                            denoise=denoise,
                            steps=steps,
                            cfg=cfg,
                            sampler=self.sampler,
                        )
                    elif mode == "img2img":
                        workflow = img2img_workflow(
                            prompt=prompt,
                            negative=negative,
                            seed=job_seed,
                            checkpoint=checkpoint,
                            image_name=image_name,
                            denoise=denoise,
                            steps=steps,
                            cfg=cfg,
                            sampler=self.sampler,
                        )
                    else:
                        workflow = txt2img_workflow(
                            prompt=prompt,
                            negative=negative,
                            width=width,
                            height=height,
                            seed=job_seed,
                            checkpoint=checkpoint,
                            steps=steps,
                            cfg=cfg,
                            sampler=self.sampler,
                        )

                    prompt_id, queue_error = await queue_workflow(
                        client, self.comfy_url, workflow, uuid.uuid4().hex
                    )
                    if queue_error:
                        hint = (
                            f" Install a checkpoint named {checkpoint} or set "
                            "tools.image.checkpoint to one ComfyUI already has."
                            if available
                            else (
                                " Install a checkpoint named "
                                f"{DEFAULT_CHECKPOINT} or set tools.image.checkpoint."
                            )
                        )
                        known = ""
                        if available:
                            shown = ", ".join(available[:8])
                            known = f" Available: {shown}."
                        return ToolResult(
                            ok=False,
                            output=(
                                "[fail:image] ComfyUI rejected the workflow."
                                f"{hint}{known}\nResponse: {queue_error}"
                            ),
                        )

                    image_file, wait_error = await wait_for_image(
                        client,
                        self.comfy_url,
                        prompt_id or "",
                        on_progress=lambda step, total, i=index: self._note(
                            image_progress_line(
                                index=i + 1, n=n, step=step, total=total
                            )
                        ),
                    )
                    if wait_error or not image_file:
                        return ToolResult(
                            ok=False,
                            output=(
                                "[fail:image] "
                                f"{wait_error or 'ComfyUI timed out without an image.'}"
                            ),
                            data={"prompt_id": prompt_id, "paths": paths},
                        )

                    local_path = await fetch_image(
                        client, self.comfy_url, image_file, self.output_dir
                    )
                    if local_path is None:
                        return ToolResult(
                            ok=False,
                            output=(
                                f"[fail:image] ComfyUI produced {image_file} "
                                "but it could not be saved."
                            ),
                            data={"prompt_id": prompt_id, "paths": paths},
                        )
                    try:
                        local_path, out_w, out_h = self._finish_pixels(
                            local_path, upscale=upscale, remove_bg=remove_bg
                        )
                    except RuntimeError as exc:
                        return ToolResult(ok=False, output=str(exc))
                    self._write_meta(
                        local_path,
                        prompt=prompt,
                        negative=negative,
                        seed=job_seed,
                        checkpoint=checkpoint,
                        width=out_w,
                        height=out_h,
                        style=style,
                        mode=mode,
                        source=source_label,
                        denoise=denoise,
                        n=n,
                    )
                    paths.append(str(local_path))
                    seeds.append(job_seed)
                    last_prompt_id = prompt_id or ""

                schedule_comfy_idle_stop()
                kind = {
                    "img2img": "Restyle",
                    "inpaint": "Inpaint",
                    "outpaint": "Outpaint",
                }.get(mode, "Image")
                extra = ""
                if source is not None:
                    extra = f" from {source_label}"
                if style:
                    extra += f", style={style}"
                listed = ", ".join(paths)
                seed_bit = (
                    f"seed={seeds[0]}"
                    if len(seeds) == 1
                    else f"seeds={', '.join(str(s) for s in seeds)}"
                )
                return ToolResult(
                    ok=True,
                    output=(
                        f"{kind} saved to {listed} ({seed_bit}, "
                        f"{out_w}x{out_h}{extra}). "
                        "It should appear in the Workspace dock."
                    ),
                    data={
                        "path": paths[0],
                        "paths": paths,
                        "prompt_id": last_prompt_id,
                        "seed": seeds[0],
                        "seeds": seeds,
                        "checkpoint": checkpoint,
                        "width": out_w,
                        "height": out_h,
                        "style": style,
                        "source": source_label,
                        "denoise": denoise,
                        "mode": mode,
                        "n": n,
                    },
                )
        except Exception as exc:
            return ToolResult(ok=False, output=f"[fail:image] image failed: {exc}")


def schedule_image_progress(bus: Any, line: str) -> None:
    """Push a composer shimmer line without blocking the sampler poll."""
    import asyncio

    from arelis.core.events import Event, EventType

    try:
        asyncio.get_running_loop().create_task(
            bus.publish(
                Event(EventType.STATUS, {"message": line, "image_progress": True})
            )
        )
    except RuntimeError:
        pass
