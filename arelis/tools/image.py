from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from arelis.tools.base import ToolResult
from arelis.tools.comfy_lifecycle import ensure_comfy_running, schedule_comfy_idle_stop

# Poll budget for a queued job. Generation on a mid-range GPU is tens of
# seconds, so one minute of one-second polls covers the common case without
# holding the tool call open indefinitely.
_POLL_ATTEMPTS = 60
_POLL_INTERVAL_S = 1.0

# Seeds are drawn from this range so a run is reproducible: the value used is
# echoed back in ToolResult.data, and passing it again as the seed argument
# reproduces the image. 2**31 keeps it inside what ComfyUI accepts.
_SEED_SPACE = 2**31

# Minimal text-to-image workflow placeholder; ComfyUI users typically replace
# this with their own workflow JSON. This posts a simple request and polls history.
DEFAULT_WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "PROMPT", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "ugly, blurry", "clip": ["4", 1]},
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


class ImageTool:
    name = "image"
    description = (
        "Generate a NEW image via local ComfyUI (create pixels from a text prompt). "
        "ComfyUI is a separate program that has to be running on this machine, and "
        "the shipped setup does not start it for you: if the world state says image "
        "generation needs ComfyUI, say it can be done once ComfyUI is running rather "
        "than calling this and reporting a failure. "
        "The finished file is saved for the Workspace panel. "
        "Args: prompt, optional negative/width/height/seed. "
        "This cannot modify an image that already exists — width/height here set "
        "the size of something invented from the prompt, so using it to 'resize' "
        "a file returns a different picture. To change an existing image use "
        "image_edit; to look at one use vision."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Positive image prompt"},
            "negative": {"type": "string", "description": "Negative prompt"},
            "width": {"type": "integer", "description": "Width in pixels (default 512)"},
            "height": {"type": "integer", "description": "Height in pixels (default 512)"},
            "seed": {"type": "integer", "description": "Sampler seed"},
        },
        "required": ["prompt"],
    }

    def __init__(
        self,
        comfy_url: str,
        output_dir: str,
        *,
        # Starting a program on someone's machine is not a thing to do by
        # omission. The shipped config says false; a caller that wants a launch
        # has to ask for one.
        auto_start: bool = False,
        launch_command: str = "",
        launch_cwd: str = "",
        startup_timeout_s: float = 120.0,
    ) -> None:
        self.comfy_url = comfy_url.rstrip("/")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.auto_start = auto_start
        self.launch_command = launch_command
        self.launch_cwd = launch_cwd
        self.startup_timeout_s = startup_timeout_s

    async def run(self, **kwargs: Any) -> ToolResult:
        prompt = kwargs.get("prompt")
        if not prompt:
            return ToolResult(ok=False, output="Missing prompt")
        negative = kwargs.get("negative", "ugly, blurry, low quality")
        width = int(kwargs.get("width", 512))
        height = int(kwargs.get("height", 512))
        seed = int(kwargs.get("seed", uuid.uuid4().int % _SEED_SPACE))

        workflow = json.loads(json.dumps(DEFAULT_WORKFLOW))
        workflow["6"]["inputs"]["text"] = prompt
        workflow["7"]["inputs"]["text"] = negative
        workflow["5"]["inputs"]["width"] = width
        workflow["5"]["inputs"]["height"] = height
        workflow["3"]["inputs"]["seed"] = seed

        client_id = uuid.uuid4().hex
        try:
            boot_error = await ensure_comfy_running(
                self.comfy_url,
                launch_command=self.launch_command,
                launch_cwd=self.launch_cwd,
                startup_timeout_s=self.startup_timeout_s,
                auto_start=self.auto_start,
            )
            if boot_error:
                return ToolResult(
                    ok=False,
                    output=f"[fail:image] {boot_error}",
                )

            async with httpx.AsyncClient(timeout=120) as client:
                queued = await client.post(
                    f"{self.comfy_url}/prompt",
                    json={"prompt": workflow, "client_id": client_id},
                )
                if queued.status_code >= 400:
                    return ToolResult(
                        ok=False,
                        output=(
                            "[fail:image] ComfyUI rejected the workflow. Install a "
                            "checkpoint named v1-5-pruned-emaonly.safetensors or "
                            "customize arelis/tools/image.py DEFAULT_WORKFLOW.\n"
                            f"Response: {queued.text[:500]}"
                        ),
                    )
                prompt_id = queued.json().get("prompt_id")
                # Poll history until an output image appears. The history entry
                # can show up before its outputs are populated, so the presence
                # of prompt_id is not on its own a finish condition: breaking on
                # it reports "queued, check the output folder" for jobs that
                # were about to succeed.
                image_name = None
                for _ in range(_POLL_ATTEMPTS):
                    try:
                        hist = await client.get(f"{self.comfy_url}/history/{prompt_id}")
                        data = hist.json()
                    except Exception:
                        data = {}
                    entry = data.get(prompt_id) or {}
                    for node in (entry.get("outputs") or {}).values():
                        images = node.get("images") or []
                        if images:
                            image_name = images[0].get("filename")
                            break
                    if image_name:
                        break
                    status = (entry.get("status") or {}).get("status_str")
                    if status == "error":
                        return ToolResult(
                            ok=False,
                            output=(
                                f"[fail:image] ComfyUI reported an error for "
                                f"job {prompt_id}."
                            ),
                            data={"prompt_id": prompt_id},
                        )
                    await asyncio.sleep(_POLL_INTERVAL_S)

                if not image_name:
                    return ToolResult(
                        ok=True,
                        output=(
                            f"Queued ComfyUI job {prompt_id}. "
                            "Image may appear in ComfyUI output folder shortly."
                        ),
                        data={"prompt_id": prompt_id, "seed": seed},
                    )

                # Copy the artifact into the Arelis output dir so the workspace
                # panel can display it without reaching into ComfyUI's folders.
                view = await client.get(
                    f"{self.comfy_url}/view",
                    params={"filename": image_name, "type": "output"},
                )
                local_path = self.output_dir / image_name
                if view.status_code == 200:
                    local_path.write_bytes(view.content)
                    schedule_comfy_idle_stop()
                    return ToolResult(
                        ok=True,
                        output=(
                            f"Image saved to {local_path} (seed={seed}). "
                            "It should appear in the Workspace dock."
                        ),
                        data={"path": str(local_path), "prompt_id": prompt_id, "seed": seed},
                    )
                schedule_comfy_idle_stop()
                return ToolResult(
                    ok=True,
                    output=f"ComfyUI produced {image_name} (prompt_id={prompt_id}, seed={seed})",
                    data={"prompt_id": prompt_id, "filename": image_name, "seed": seed},
                )
        except Exception as exc:
            return ToolResult(ok=False, output=f"[fail:image] image failed: {exc}")
