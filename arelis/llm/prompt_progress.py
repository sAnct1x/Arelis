"""Prompt-read cursor. The chat stream is silent while the prompt is read.

Ollama does not emit tokens during that read. The runner log still reports
the cursor, and a chunk may carry it when the server knows how. A repeat of
the same count is not progress. The prompt text itself is never taken from
the log.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import IO, Any

# llama.cpp: "prompt processing, n_tokens = 4096, progress = 0.27"
_LLAMA_N = re.compile(
    r"prompt processing,?\s*n_tokens\s*=\s*(\d+)",
    re.IGNORECASE,
)
# MLX runner: msg="Prompt processing progress" processed=2048 total=109972
_MLX_N = re.compile(
    r"Prompt processing progress\b.*?\bprocessed=(\d+)",
    re.IGNORECASE,
)


def prompt_read_position(line: str) -> int | None:
    """Tokens of the prompt read so far, or None when the line is not that."""
    if not line:
        return None
    match = _LLAMA_N.search(line) or _MLX_N.search(line)
    if match is None:
        return None
    return _as_pos(match.group(1))


def prompt_read_from_chunk(data: dict[str, Any]) -> int | None:
    """Cursor from one chat chunk, when the server reports one.

    ``prompt_eval_count`` on the final chunk is the total, not a mid-read
    update, so it is ignored here.
    """
    if not isinstance(data, dict):
        return None
    for key in ("prompt_eval_completed", "prompt_tokens_processed"):
        pos = _as_pos(data.get(key))
        if pos is not None:
            return pos
    nested = data.get("prompt_eval_progress")
    if isinstance(nested, dict):
        for key in ("completed", "processed", "n_tokens"):
            pos = _as_pos(nested.get(key))
            if pos is not None:
                return pos
        return None
    return _as_pos(nested)


def ollama_log_path() -> Path | None:
    """Server log for this OS, or None when it is not there."""
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Ollama" / "server.log")
    candidates.append(Path.home() / ".ollama" / "logs" / "server.log")
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def _as_pos(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        pos = value
    elif isinstance(value, str) and value.strip().isdigit():
        pos = int(value.strip())
    else:
        return None
    if pos <= 0:
        return None
    return pos


async def follow_prompt_read(stop: asyncio.Event) -> AsyncIterator[int]:
    """Yield each forward prompt-read count until ``stop`` is set.

    Starts at the end of the log so an old line is not this request.
    Missing log, or a log that cannot be opened, yields nothing.
    """
    path = ollama_log_path()
    if path is None:
        return

    def _open() -> IO[str]:
        opened = path.open("r", encoding="utf-8", errors="replace")
        opened.seek(0, os.SEEK_END)
        return opened

    try:
        handle = await asyncio.to_thread(_open)
    except OSError:
        return
    last = 0
    try:
        while not stop.is_set():
            line = await asyncio.to_thread(handle.readline)
            if not line:
                try:
                    await asyncio.wait_for(stop.wait(), 0.25)
                except TimeoutError:
                    continue
                return
            pos = prompt_read_position(line)
            if pos is None or pos <= last:
                continue
            last = pos
            yield pos
    finally:
        try:
            await asyncio.to_thread(handle.close)
        except OSError:
            pass
