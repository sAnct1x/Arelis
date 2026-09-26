"""Queue a ComfyUI workflow, wait for the file, copy it into Arelis.

The image tool owns the product (prompt, size, style, img2img). This module
owns the HTTP conversation so a restyle and a generate share one poll loop
instead of drifting apart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

# Generation on a mid-range GPU is tens of seconds; SDXL can take longer.
# Two minutes of one-second polls covers the common case without holding the
# tool call open indefinitely.
# DirectML 25-step jobs here run ~3 minutes. 120s reported "not running"
# while the GPU was still stepping.
POLL_ATTEMPTS = 240
POLL_INTERVAL_S = 1.0

DEFAULT_CHECKPOINT = "v1-5-pruned-emaonly.safetensors"
DEFAULT_NEGATIVE = "ugly, blurry, low quality, deformed, extra limbs"

# Long edge used when the caller did not name a size. SDXL wants ~1024;
# SD 1.5 is happier around 768 than the old 512 default.
SDXL_EDGE = 1024
SD15_EDGE = 768
_MAX_EDGE = 2048

ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "square": (1, 1),
    "landscape": (16, 9),
    "portrait": (9, 16),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:2": (3, 2),
    "21:9": (21, 9),
}

STYLE_PRESETS: dict[str, dict[str, str]] = {
    "photoreal": {
        "positive": "photorealistic, detailed, natural lighting, sharp focus",
        "negative": "cartoon, illustration, painting, anime, deformed",
    },
    "illustration": {
        "positive": "digital illustration, clean lines, vibrant colour",
        "negative": "photograph, noisy, blurry, deformed",
    },
    "anime": {
        "positive": "anime style, vibrant, clean lineart",
        "negative": "photograph, realistic skin, noisy",
    },
    "watercolor": {
        "positive": "watercolor painting, soft washes, paper texture",
        "negative": "photograph, harsh digital, neon",
    },
    "oil": {
        "positive": "oil painting, visible brushwork, rich colour",
        "negative": "photograph, digital cartoon, neon",
    },
    "sketch": {
        "positive": "pencil sketch, detailed linework, paper",
        "negative": "photograph, full colour render, neon",
    },
    "cinematic": {
        "positive": "cinematic lighting, film still, shallow depth of field",
        "negative": "flat lighting, snapshot, overexposed",
    },
}

_SDXL_MARKERS = ("sdxl", "sd_xl", "sd-xl", "pony", "illustrious", "flux", "xl_")


def looks_sdxl(checkpoint: str) -> bool:
    name = (checkpoint or "").lower()
    return any(marker in name for marker in _SDXL_MARKERS)


def snap_px(value: int) -> int:
    """Comfy latents want multiples of 8."""
    return max(8, int(value) // 8 * 8)


def long_edge_for(checkpoint: str) -> int:
    return SDXL_EDGE if looks_sdxl(checkpoint) else SD15_EDGE


def size_for_aspect(aspect: str, long_edge: int) -> tuple[int, int]:
    key = (aspect or "").strip().lower()
    if key not in ASPECT_RATIOS:
        known = ", ".join(sorted(ASPECT_RATIOS))
        raise ValueError(f"Unknown aspect `{aspect}`. Known: {known}.")
    ratio_w, ratio_h = ASPECT_RATIOS[key]
    edge = snap_px(min(_MAX_EDGE, max(64, int(long_edge))))
    if ratio_w >= ratio_h:
        width = edge
        height = snap_px(round(edge * ratio_h / ratio_w))
    else:
        height = edge
        width = snap_px(round(edge * ratio_w / ratio_h))
    return width, height


def clamp_size(width: int, height: int) -> tuple[int, int]:
    width, height = snap_px(width), snap_px(height)
    if min(width, height) < 64:
        raise ValueError(f"Size must be at least 64px, got {width}x{height}.")
    if max(width, height) > _MAX_EDGE:
        raise ValueError(
            f"{width}x{height} is larger than this tool will generate "
            f"(max edge {_MAX_EDGE}px)."
        )
    return width, height


def apply_style(prompt: str, negative: str, style: str) -> tuple[str, str]:
    key = (style or "").strip().lower()
    if not key:
        return prompt, negative
    preset = STYLE_PRESETS.get(key)
    if preset is None:
        known = ", ".join(sorted(STYLE_PRESETS))
        raise ValueError(f"Unknown style `{style}`. Known: {known}.")
    extra_pos = preset["positive"]
    extra_neg = preset["negative"]
    merged = prompt.strip()
    if extra_pos and extra_pos not in merged:
        merged = f"{merged}, {extra_pos}" if merged else extra_pos
    merged_neg = negative.strip() or DEFAULT_NEGATIVE
    if extra_neg and extra_neg not in merged_neg:
        merged_neg = f"{merged_neg}, {extra_neg}"
    return merged, merged_neg


def pick_checkpoint(available: list[str], preferred: str = "") -> str:
    want = (preferred or "").strip()
    # Config wins even when the listing is empty or stale — Comfy still has
    # the file, and a rejection names the ones it can see.
    if want:
        return want
    if not available:
        return DEFAULT_CHECKPOINT
    for name in available:
        if looks_sdxl(name):
            return name
    return available[0]


def txt2img_workflow(
    *,
    prompt: str,
    negative: str,
    width: int,
    height: int,
    seed: int,
    checkpoint: str,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler",
    scheduler: str = "normal",
) -> dict[str, Any]:
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(steps),
                "cfg": float(cfg),
                "sampler_name": sampler,
                "scheduler": scheduler,
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": int(width), "height": int(height), "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "arelis", "images": ["8", 0]},
        },
    }


def img2img_workflow(
    *,
    prompt: str,
    negative: str,
    seed: int,
    checkpoint: str,
    image_name: str,
    denoise: float = 0.55,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler",
    scheduler: str = "normal",
) -> dict[str, Any]:
    denoise = max(0.15, min(0.95, float(denoise)))
    workflow = txt2img_workflow(
        prompt=prompt,
        negative=negative,
        width=512,
        height=512,
        seed=seed,
        checkpoint=checkpoint,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        scheduler=scheduler,
    )
    workflow["10"] = {
        "class_type": "LoadImage",
        "inputs": {"image": image_name},
    }
    workflow["5"] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["10", 0], "vae": ["4", 2]},
    }
    workflow["3"]["inputs"]["denoise"] = denoise
    return workflow


def inpaint_workflow(
    *,
    prompt: str,
    negative: str,
    seed: int,
    checkpoint: str,
    image_name: str,
    mask_name: str,
    denoise: float = 0.75,
    steps: int = 25,
    cfg: float = 7.0,
    sampler: str = "euler",
    scheduler: str = "normal",
) -> dict[str, Any]:
    """Inpaint via VAEEncodeForInpaint. Mask: white=change, black=keep."""
    denoise = max(0.15, min(0.95, float(denoise)))
    workflow = txt2img_workflow(
        prompt=prompt,
        negative=negative,
        width=512,
        height=512,
        seed=seed,
        checkpoint=checkpoint,
        steps=steps,
        cfg=cfg,
        sampler=sampler,
        scheduler=scheduler,
    )
    workflow["10"] = {
        "class_type": "LoadImage",
        "inputs": {"image": image_name},
    }
    workflow["11"] = {
        "class_type": "LoadImage",
        "inputs": {"image": mask_name},
    }
    workflow["12"] = {
        "class_type": "ImageToMask",
        "inputs": {"image": ["11", 0], "channel": "red"},
    }
    workflow["5"] = {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": ["10", 0],
            "vae": ["4", 2],
            "mask": ["12", 0],
            "grow_mask_by": 6,
        },
    }
    workflow["3"]["inputs"]["denoise"] = denoise
    return workflow


async def list_checkpoints(client: httpx.AsyncClient, comfy_url: str) -> list[str]:
    base = comfy_url.rstrip("/")
    try:
        listed = await client.get(f"{base}/models/checkpoints")
        if listed.status_code < 400:
            payload = listed.json()
            if isinstance(payload, list):
                return [str(name) for name in payload if str(name).strip()]
    except Exception:
        pass
    try:
        info = await client.get(f"{base}/object_info/CheckpointLoaderSimple")
        if info.status_code >= 400:
            return []
        data = info.json() or {}
        node = data.get("CheckpointLoaderSimple") or data
        required = ((node.get("input") or {}).get("required") or {})
        raw = required.get("ckpt_name")
        names = raw[0] if isinstance(raw, list) and raw else []
        if isinstance(names, list):
            return [str(name) for name in names if str(name).strip()]
    except Exception:
        return []
    return []


async def upload_image(
    client: httpx.AsyncClient, comfy_url: str, path: Path
) -> str:
    """Put a local file in Comfy's input folder. Returns the name LoadImage wants."""
    data = path.read_bytes()
    files = {"image": (path.name, data, "application/octet-stream")}
    posted = await client.post(f"{comfy_url.rstrip('/')}/upload/image", files=files)
    posted.raise_for_status()
    payload = posted.json() or {}
    name = str(payload.get("name") or path.name).strip()
    sub = str(payload.get("subfolder") or "").strip()
    if sub:
        return f"{sub}/{name}"
    return name


async def queue_workflow(
    client: httpx.AsyncClient,
    comfy_url: str,
    workflow: dict[str, Any],
    client_id: str,
) -> tuple[str | None, str]:
    """Queue a prompt. Returns (prompt_id, error). Error is empty on success."""
    queued = await client.post(
        f"{comfy_url.rstrip('/')}/prompt",
        json={"prompt": workflow, "client_id": client_id},
    )
    if queued.status_code >= 400:
        return None, queued.text[:500]
    prompt_id = str((queued.json() or {}).get("prompt_id") or "").strip()
    if not prompt_id:
        return None, "ComfyUI queued the workflow but returned no prompt_id."
    return prompt_id, ""


def _history_error(entry: dict[str, Any]) -> str:
    """Pull the real Comfy exception (OOM, missing node) out of history."""
    messages = (entry.get("status") or {}).get("messages") or []
    bits: list[str] = []
    for item in messages:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        payload = item[1]
        if not isinstance(payload, dict):
            continue
        msg = str(
            payload.get("exception_message") or payload.get("message") or ""
        ).strip()
        if msg and msg not in bits:
            bits.append(msg)
    return " ".join(bits)


async def wait_for_image(
    client: httpx.AsyncClient,
    comfy_url: str,
    prompt_id: str,
    *,
    attempts: int = POLL_ATTEMPTS,
    interval_s: float = POLL_INTERVAL_S,
    on_progress: Callable[[int, int], object] | None = None,
) -> tuple[str | None, str]:
    """Poll history until an output filename appears.

    Returns (filename, error). A timeout is a failure: no filename and a
    non-empty error. Callers must not report a queued job as success.
    """
    total = max(1, int(attempts))
    for step in range(total):
        if on_progress is not None:
            try:
                on_progress(step + 1, total)
            except Exception:
                pass
        try:
            hist = await client.get(f"{comfy_url.rstrip('/')}/history/{prompt_id}")
            data = hist.json()
        except Exception:
            data = {}
        entry = data.get(prompt_id) or {}
        for node in (entry.get("outputs") or {}).values():
            images = node.get("images") or []
            if images:
                name = str(images[0].get("filename") or "").strip()
                if name:
                    return name, ""
        status = (entry.get("status") or {}).get("status_str")
        if status == "error":
            detail = _history_error(entry)
            return None, detail or f"ComfyUI reported an error for job {prompt_id}."
        await asyncio.sleep(interval_s)
    seconds = max(1, round(total * float(interval_s)))
    return None, (
        f"ComfyUI did not produce an image for job {prompt_id} "
        f"within {seconds}s."
    )


async def fetch_image(
    client: httpx.AsyncClient,
    comfy_url: str,
    image_name: str,
    dest_dir: Path,
) -> Path | None:
    view = await client.get(
        f"{comfy_url.rstrip('/')}/view",
        params={"filename": image_name, "type": "output"},
    )
    if view.status_code != 200 or not view.content:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = dest_dir / Path(image_name).name
    local.write_bytes(view.content)
    return local
