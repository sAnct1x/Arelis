"""Single-frame vision: describe / answer questions about one local image."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
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
# Three 1024px homework pages in one shot sat on qwen3.5:9b until the 300s
# HTTP timeout, then she OCR'd ink and answered from soup. One smaller page
# at a time actually returns.
_INK_EDGE = 768
_PAGE_LOOK_S = 90.0


class _VisionRunner(Protocol):
    async def run_vision(
        self,
        prompt: str,
        images_b64: list[str],
        *,
        model: str | None = None,
        num_ctx: int = 4096,
        think: bool | None = None,
    ) -> str: ...


class VisionTool:
    name = "vision"
    description = (
        "Look at local images (png/jpg/webp/gif under a workspace root, "
        "outputs/, or a staged attachment under data/drops/). Use to describe a "
        "screenshot, photo, diagram, or handwritten PDF pages. "
        "Args: path for one image, or paths=[...] for several pages in one "
        "call (homework scans). Optional question. "
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
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Several page images in one look (ink PDF). Prefer this "
                    "over many separate vision calls."
                ),
            },
            "question": {
                "type": "string",
                "description": ("Optional question about the image. Default: describe clearly."),
            },
        },
        "required": [],
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
        self.is_cancelled: Any = None

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

    def _collect_paths(self, kwargs: dict[str, Any]) -> list[str]:
        raw = kwargs.get("paths")
        if isinstance(raw, str):
            extra = [part.strip() for part in raw.split(",") if part.strip()]
        elif isinstance(raw, (list, tuple)):
            extra = [str(part).strip() for part in raw if str(part).strip()]
        else:
            extra = []
        # A filled leftover `path=` (last generate) must not become page 1
        # when the call already named the homework pages.
        if extra:
            return extra
        single = str(kwargs.get("path") or "").strip()
        return [single] if single else []

    async def run(self, **kwargs: Any) -> ToolResult:
        path_list = self._collect_paths(kwargs)
        question = str(kwargs.get("question") or "").strip() or _DEFAULT_QUESTION
        if not path_list:
            return ToolResult(ok=False, output="Missing path")
        try:
            paths = [self._resolve_image(item) for item in path_list]
        except (ValueError, PermissionError, FileNotFoundError) as exc:
            return ToolResult(ok=False, output=str(exc))
        path = paths[0]

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

        from arelis.tools.pdf_pages import is_ink_page_image

        ink = len(paths) > 1 or any(is_ink_page_image(item) for item in paths)
        edge = _INK_EDGE if ink else (self.chat_max_edge if chat_sees else self.max_edge)
        if len(paths) > 1:
            return await self._look_pages(paths, question, edge=edge)

        try:
            encoded, prepared = await self._encode_one(paths[0], edge)
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not read image: {exc}")
        prepared["page_count"] = 1

        text, fatal = await self._look_one(
            question,
            encoded,
            prepared,
            timeout_s=_PAGE_LOOK_S if ink else 0.0,
            think=False if ink else None,
        )
        if fatal is not None:
            return fatal
        answer = (text or "").strip()
        if not answer:
            return ToolResult(
                ok=False,
                output="Vision model returned empty text.",
                data={"model": self.model, "path": str(path), **prepared},
            )
        return self._ok_result(path, answer, prepared)

    def _cancelled(self) -> bool:
        probe = getattr(self, "is_cancelled", None)
        if not callable(probe):
            return False
        try:
            return bool(probe())
        except Exception:
            return False

    async def _emit_progress(self, text: str) -> None:
        sink = getattr(self.runner, "think_sink", None)
        if not callable(sink) or not text:
            return
        maybe = sink(text)
        if inspect.isawaitable(maybe):
            await maybe

    async def _encode_one(self, path: Path, edge: int) -> tuple[list[str], dict[str, Any]]:
        b64, meta = await asyncio.to_thread(encode_for_vision, path, max_edge=edge)
        return [b64], dict(meta)

    async def _look_one(
        self,
        prompt: str,
        encoded: list[str],
        prepared: dict[str, Any],
        *,
        timeout_s: float = 0.0,
        think: bool | None = None,
    ) -> tuple[str | None, ToolResult | None]:
        """One VL shot. Returns (text, None) or (None, fatal ToolResult)."""
        try:
            call = self.runner.run_vision(
                prompt,
                encoded,
                model=self.model,
                num_ctx=self.num_ctx,
                think=think,
            )
            if timeout_s > 0:
                answer = await asyncio.wait_for(call, timeout=timeout_s)
            else:
                answer = await call
            return (answer or "").strip(), None
        except TimeoutError:
            return None, None
        except Exception as exc:
            return None, self._vision_error(exc, prepared)

    def _vision_error(self, exc: Exception, prepared: dict[str, Any]) -> ToolResult:
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

    async def _look_pages(
        self,
        paths: list[Path],
        question: str,
        *,
        edge: int,
    ) -> ToolResult:
        """One page per VL call. Three-at-once hung the 9B for five minutes."""
        n = len(paths)
        chunks: list[str] = []
        seen = 0
        prepared: dict[str, Any] = {"page_count": n, "walk": True}
        for index, item in enumerate(paths, start=1):
            if self._cancelled():
                chunks.append(f"--- page {index} of {n}: stopped ---")
                break
            await self._emit_progress(f"looking at page {index} of {n}\n")
            try:
                encoded, meta = await self._encode_one(item, edge)
            except OSError as exc:
                chunks.append(f"--- page {index} of {n}: {exc} ---")
                continue
            prepared = {**prepared, **meta, "page_count": n, "walk": True}
            prompt = f"{question} (page {index} of {n}.)"
            text, fatal = await self._look_one(
                prompt,
                encoded,
                prepared,
                timeout_s=_PAGE_LOOK_S,
                think=False,
            )
            if fatal is not None and seen == 0:
                return fatal
            if fatal is not None:
                chunks.append(f"--- page {index} of {n}: {fatal.output} ---")
                break
            if text:
                seen += 1
                chunks.append(f"--- page {index} of {n} ---\n{text}")
            else:
                chunks.append(f"--- page {index} of {n}: look timed out ---")
        body = "\n\n".join(chunks).strip()
        if seen == 0:
            return ToolResult(
                ok=False,
                output=(
                    "Vision timed out on every page. "
                    "The images may be too heavy for this model — try again, "
                    "or look at one page by name."
                ),
                data={"model": self.model, "code": "VISION_TIMEOUT", **prepared},
            )
        return self._ok_result(paths[0], body, prepared)

    def _ok_result(self, path: Path, answer: str, prepared: dict[str, Any]) -> ToolResult:
        digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()[:12]
        rel = display_path(path)
        from arelis.look_scratch import forget_look_scratch, is_look_scratch

        if is_look_scratch(path):
            forget_look_scratch(path)
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
