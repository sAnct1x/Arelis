"""Single-frame vision: describe / answer questions about one local image."""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any, Protocol

from arelis.paths import display_path
from arelis.tools.base import ToolResult
from arelis.tools.image_io import (
    CHAT_MAX_EDGE,
    DEFAULT_MAX_EDGE,
    IMAGE_SUFFIXES,
    encode_for_vision,
    resolve_image,
)
from arelis.workspace import WorkspaceRoots

_IMAGE_SUFFIXES = IMAGE_SUFFIXES
_DEFAULT_QUESTION = "Describe this image clearly for the assistant."
_MODEL_MISSING = re.compile(
    r"model\s+['\"]?[\w.:-]+['\"]?\s+not\s+found|not\s+found|pull\s+",
    re.I,
)
# Ollama's 400 when the image plus the question outgrow num_ctx. Worth its own
# message: "vision failed" for a 1440p screenshot sent nobody anywhere.
_CONTEXT_FULL = re.compile(
    r"exceed(?:s)?\s+the\s+available\s+context|exceed_context_size|"
    r"context\s+size\s+\(\d+\s+tokens\)",
    re.I,
)


class _VisionRunner(Protocol):
    async def run_vision(
        self,
        prompt: str,
        images_b64: list[str],
        *,
        model: str | None = None,
        num_ctx: int = 4096,
    ) -> str: ...


class VisionTool:
    name = "vision"
    description = (
        "Look at one local image (png/jpg/webp/gif under a workspace root, "
        "outputs/, or a staged attachment under data/drops/). Use to describe a "
        "screenshot, photo, or diagram, or answer a question about it. "
        "Args: path, optional question. "
        "This only looks — it cannot change an image. To resize, crop or adjust "
        "one use image_edit; to create a new one from a prompt use image."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Workspace-relative or name:rel path to a local image "
                    "(also allowed under outputs/images/)."
                ),
            },
            "question": {
                "type": "string",
                "description": (
                    "Optional question about the image. Default: describe clearly."
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots,
        runner: _VisionRunner,
        *,
        model: str = "qwen2.5vl:3b",
        num_ctx: int = 4096,
        model_available: Any | None = None,
        max_edge: int = DEFAULT_MAX_EDGE,
        chat_max_edge: int = CHAT_MAX_EDGE,
    ) -> None:
        self.workspace = workspace
        self.runner = runner
        self.model = model
        self.num_ctx = int(num_ctx)
        # 3B detour / 4096 window. Chat-sees uses chat_max_edge instead.
        self.max_edge = int(max_edge)
        self.chat_max_edge = int(chat_max_edge)
        # Optional async callable () -> bool; when set, missing models fail loud.
        self._model_available = model_available

    async def _chat_sees(self) -> bool:
        probe = getattr(self.runner, "chat_sees_images", None)
        if probe is None:
            return False
        try:
            return bool(await probe())
        except Exception:
            return False

    def _resolve_image(self, path_str: str) -> Path:
        return resolve_image(self.workspace, path_str)

    async def run(self, **kwargs: Any) -> ToolResult:
        path_str = str(kwargs.get("path") or "").strip()
        question = str(kwargs.get("question") or "").strip() or _DEFAULT_QUESTION
        try:
            path = self._resolve_image(path_str)
        except (ValueError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, output=str(exc))

        chat_sees = await self._chat_sees()
        if self._model_available is not None and not chat_sees:
            try:
                ok = await self._model_available()
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    output=(
                        f"Could not check Ollama models for vision (`{self.model}`): "
                        f"{exc}. Is Ollama running?"
                    ),
                    data={"model": self.model, "code": "MODEL_CHECK_FAILED"},
                )
            if not ok:
                return ToolResult(
                    ok=False,
                    output=(
                        f"Vision model `{self.model}` is not installed. "
                        f"Run: ollama pull {self.model}"
                    ),
                    data={"model": self.model, "code": "MODEL_MISSING"},
                )

        edge = self.chat_max_edge if chat_sees else self.max_edge
        try:
            b64, prepared = await asyncio.to_thread(
                encode_for_vision, path, max_edge=edge
            )
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not read image: {exc}")

        try:
            answer = await self.runner.run_vision(
                question,
                [b64],
                model=self.model,
                num_ctx=self.num_ctx,
            )
        except Exception as exc:
            msg = str(exc)
            if _MODEL_MISSING.search(msg):
                return ToolResult(
                    ok=False,
                    output=(
                        f"Vision model `{self.model}` is not available. "
                        f"Run: ollama pull {self.model}\n({msg[:300]})"
                    ),
                    data={"model": self.model, "code": "MODEL_MISSING"},
                )
            if _CONTEXT_FULL.search(msg):
                # Reachable again only if a downscaled image still will not fit,
                # so say the number rather than repeating "it failed".
                return ToolResult(
                    ok=False,
                    output=(
                        f"The image was still too large for the vision context at "
                        f"{prepared.get('sent_px') or 'its current size'} "
                        f"(num_ctx={self.num_ctx}). Lower tools.vision.max_edge "
                        f"or tools.vision.chat_max_edge, or raise "
                        f"ollama.vision_num_ctx.\n({msg[:200]})"
                    ),
                    data={"model": self.model, "code": "VISION_CONTEXT", **prepared},
                )
            return ToolResult(
                ok=False,
                output=f"Vision failed: {msg[:500]}",
                data={"model": self.model, "code": "VISION_FAILED", **prepared},
            )

        answer = (answer or "").strip()
        if not answer:
            return ToolResult(
                ok=False,
                output="Vision model returned empty text.",
                data={"model": self.model, "path": str(path)},
            )

        digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()[:12]
        rel = display_path(path)
        return ToolResult(
            ok=True,
            output=answer,
            data={
                "path": rel,
                "model": self.model,
                "answer_len": len(answer),
                "answer_hash": digest,
                **prepared,
            },
        )
