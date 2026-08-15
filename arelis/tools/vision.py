"""Single-frame vision: describe / answer questions about one local image."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path
from typing import Any, Protocol

from arelis.config import PROJECT_ROOT
from arelis.paths import outputs_dir, user_data_dir
from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_DEFAULT_QUESTION = "Describe this image clearly for the assistant."
_MODEL_MISSING = re.compile(
    r"model\s+['\"]?[\w.:-]+['\"]?\s+not\s+found|not\s+found|pull\s+",
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
        "See one local image (png/jpg/webp/gif under workspace roots or "
        "outputs/images/). Use to describe a screenshot, photo, or diagram, or "
        "answer a question about it. Args: path, optional question. "
        "This is NOT image generation — use the image tool to generate via ComfyUI."
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
    ) -> None:
        self.workspace = workspace
        self.runner = runner
        self.model = model
        self.num_ctx = int(num_ctx)
        # Optional async callable () -> bool; when set, missing models fail loud.
        self._model_available = model_available

    def _resolve_image(self, path_str: str) -> Path:
        raw = (path_str or "").strip()
        if not raw:
            raise ValueError("Missing path")

        # Prefer workspace / granted-external; then outputs/images/.
        try:
            resolved = self.workspace.resolve_read(raw)
            path = resolved.path
        except (ValueError, PermissionError, FileNotFoundError):
            # Allow outputs/images even when multi-root resolve is picky.
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (user_data_dir() / candidate).resolve()
            else:
                candidate = candidate.resolve()
            images_root = (outputs_dir() / "images").resolve()
            try:
                candidate.relative_to(images_root)
            except ValueError as exc:
                raise PermissionError(
                    f"Path is outside workspace roots and outputs/images/: {raw}"
                ) from exc
            path = candidate

        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            raise ValueError(
                f"Unsupported image type `{path.suffix}` "
                f"(use png/jpg/webp/gif)"
            )
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        return path

    async def run(self, **kwargs: Any) -> ToolResult:
        path_str = str(kwargs.get("path") or "").strip()
        question = str(kwargs.get("question") or "").strip() or _DEFAULT_QUESTION
        try:
            path = self._resolve_image(path_str)
        except (ValueError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, output=str(exc))

        if self._model_available is not None:
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

        try:
            raw = path.read_bytes()
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not read image: {exc}")

        b64 = base64.b64encode(raw).decode("ascii")
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
            return ToolResult(
                ok=False,
                output=f"Vision failed: {msg[:500]}",
                data={"model": self.model, "code": "VISION_FAILED"},
            )

        answer = (answer or "").strip()
        if not answer:
            return ToolResult(
                ok=False,
                output="Vision model returned empty text.",
                data={"model": self.model, "path": str(path)},
            )

        digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()[:12]
        try:
            rel = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(path)
        return ToolResult(
            ok=True,
            output=answer,
            data={
                "path": rel,
                "model": self.model,
                "answer_len": len(answer),
                "answer_hash": digest,
            },
        )
