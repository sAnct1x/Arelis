"""Transcribe a workspace audio file with the already-loaded voice engine.

Sherpa / faster-whisper already sit behind voice. This tool only points them
at a file. It never constructs a WhisperModel and never downloads weights —
on a 12 GB card that would evict qwen3.5:9b mid-turn.

Parent injects `transcribe_fn` (preferred) or a warm `stt` instance. A cold
engine fails honestly instead of loading.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

_AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".flac", ".m4a", ".ogg"})
_VIDEO_SUFFIXES = frozenset({".mp4", ".mkv"})
_MAX_BYTES = 50 * 1024 * 1024
_DEFAULT_MAX_CHARS = 12_000
_ENGINE_NOT_LOADED = (
    "voice engine not loaded — I will not pull Whisper onto the GPU mid-turn."
)
_VIDEO_REFUSED = (
    "Video is not supported — this checkout has no ffmpeg/imageio to extract "
    "audio. Use wav, mp3, flac, m4a, or ogg."
)

TranscribeFn = Callable[[Path], str]


def _as_workspace(workspace: WorkspaceRoots | list[str]) -> WorkspaceRoots:
    if isinstance(workspace, WorkspaceRoots):
        return workspace
    return WorkspaceRoots.from_paths(list(workspace))


def _suffix_list() -> str:
    return ", ".join(sorted(s.lstrip(".") for s in _AUDIO_SUFFIXES))


class TranscribeTool:
    name = "transcribe"
    description = (
        "Transcribe a local audio file under workspace roots with the already "
        "loaded voice engine (Sherpa / Whisper). action=file path=… "
        f"Audio only: {_suffix_list()}. Not video (no ffmpeg extract). "
        "Will not load Whisper mid-turn — if the ear is cold, it says so."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["file"],
                "description": "Transcribe a workspace audio file (default file).",
            },
            "path": {
                "type": "string",
                "description": "Audio path under workspace roots, or name:relative/path",
            },
            "max_chars": {
                "type": "integer",
                "description": (
                    f"Max transcript characters to return (default {_DEFAULT_MAX_CHARS})"
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        workspace: WorkspaceRoots | list[str],
        *,
        transcribe_fn: TranscribeFn | None = None,
        stt: Any | None = None,
        max_bytes: int = _MAX_BYTES,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> None:
        self.workspace = _as_workspace(workspace)
        self._transcribe_fn = transcribe_fn
        self._stt = stt
        self.max_bytes = max(1, int(max_bytes))
        self.max_chars = max(64, int(max_chars))

    def _resolve(self, path_str: str):
        return self.workspace.resolve_read(path_str)

    def _engine_fn(self) -> TranscribeFn | None:
        if self._transcribe_fn is not None:
            return self._transcribe_fn
        if not self._stt_ready():
            return None
        stt = self._stt
        blocking = getattr(stt, "_transcribe_blocking", None)
        if callable(blocking):
            return lambda path: blocking(str(path), "turn")
        transcribe = getattr(stt, "transcribe", None)
        if callable(transcribe) and not asyncio.iscoroutinefunction(transcribe):
            return transcribe
        return None

    def _stt_ready(self) -> bool:
        """True only when a turn ear is already in memory.

        loaded() on SpeechToText also wants the wake Whisper. A file read
        should use the warm Sherpa turn ear without demanding that GPU load.
        """
        stt = self._stt
        if stt is None:
            return False
        loaded = getattr(stt, "loaded", None)
        if callable(loaded) and loaded():
            return True
        in_mem = getattr(stt, "_backend_in_memory", None)
        resolved = getattr(stt, "resolved_backend", None)
        if callable(in_mem) and callable(resolved):
            try:
                return bool(in_mem(resolved()))
            except Exception:
                # Silence is correct: a half-built backend is "not ready".
                # Raising would look like a transcribe failure and invite
                # loading Whisper to recover. Cold stays cold.
                return False
        return False

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "file").strip().lower() or "file"
        if action != "file":
            return ToolResult(
                ok=False,
                output="Unknown action. Use file.",
            )
        raw = str(kwargs.get("path") or "").strip()
        if not raw:
            return ToolResult(ok=False, output="Missing path.")
        try:
            max_chars = int(kwargs.get("max_chars") or self.max_chars)
        except (TypeError, ValueError):
            max_chars = self.max_chars
        max_chars = max(64, max_chars)

        try:
            resolved = self._resolve(raw)
        except PermissionError as exc:
            return ToolResult(ok=False, output=str(exc) or "Path escapes workspace roots.")
        except (ValueError, FileNotFoundError) as exc:
            return ToolResult(ok=False, output=str(exc) or "Missing path.")
        except Exception as exc:
            return ToolResult(ok=False, output=f"Path error: {exc}")

        path = resolved.path
        suffix = path.suffix.lower()
        if suffix in _VIDEO_SUFFIXES:
            return ToolResult(ok=False, output=_VIDEO_REFUSED)
        if suffix not in _AUDIO_SUFFIXES:
            return ToolResult(
                ok=False,
                output=(
                    f"Unsupported suffix {suffix or '(none)'}. "
                    f"Audio only: {_suffix_list()}."
                ),
            )
        if not path.is_file():
            return ToolResult(ok=False, output=f"Audio file not found: {path}")
        size = path.stat().st_size
        if size > self.max_bytes:
            mb = size / (1024 * 1024)
            cap = self.max_bytes / (1024 * 1024)
            return ToolResult(
                ok=False,
                output=(
                    f"File is {mb:.1f} MB; transcribe refuses files over "
                    f"{cap:.0f} MB."
                ),
            )

        fn = self._engine_fn()
        if fn is None:
            return ToolResult(ok=False, output=_ENGINE_NOT_LOADED)

        try:
            text = await asyncio.to_thread(fn, path)
        except Exception as exc:
            return ToolResult(ok=False, output=f"Transcribe failed: {exc}")

        cleaned = redact_secrets((text or "").strip())
        if not cleaned:
            return ToolResult(
                ok=True,
                output=f"No speech detected in {path.name}.",
                data={
                    "path": str(path),
                    "chars": 0,
                    "empty": True,
                    "truncated": False,
                },
            )
        truncated = len(cleaned) > max_chars
        body = cleaned[:max_chars]
        if truncated:
            body += f"\n…(truncated, {len(cleaned)} chars total)"
        return ToolResult(
            ok=True,
            output=f"Transcript of {path.name} ({len(cleaned)} chars):\n{body}",
            data={
                "path": str(path),
                "chars": len(cleaned),
                "empty": False,
                "truncated": truncated,
            },
        )
