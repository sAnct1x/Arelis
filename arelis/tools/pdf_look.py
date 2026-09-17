"""Read ink PDF page images in a few VL batches. One extract, not 17 looks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from arelis.tools.image_io import encode_for_vision

_LOOK_QUESTION = (
    "These are consecutive pages of handwritten homework or notes, in order. "
    "Transcribe each page: equations, diagrams, and the student's asides. "
    "Label pages. Do not invent missing work."
)

# One page per VL call. A 5-page batch on the 9B hung until the HTTP timeout.
_CHAT_BATCH = 1
_CHAT_EDGE = 768
_DETROUR_BATCH = 1
_DETROUR_EDGE = 768

LookPages = Callable[[Sequence[Path]], Awaitable[str]]


async def look_page_images(
    paths: Sequence[Path],
    *,
    run_vision: Callable[..., Awaitable[str]],
    chat_sees: bool,
    model: str | None = None,
    num_ctx: int = 4096,
) -> str:
    """Transcribe page pictures in a few batched VL calls."""
    files = [Path(p) for p in paths if Path(p).is_file()]
    if not files:
        return ""
    batch = _CHAT_BATCH if chat_sees else _DETROUR_BATCH
    edge = _CHAT_EDGE if chat_sees else _DETROUR_EDGE
    chunks: list[str] = []
    for index in range(0, len(files), batch):
        slice_paths = files[index : index + batch]
        images: list[str] = []
        for path in slice_paths:
            payload, _meta = encode_for_vision(path, max_edge=edge)
            images.append(payload)
        first = index + 1
        last = index + len(slice_paths)
        prompt = f"{_LOOK_QUESTION} Pages {first}-{last} of {len(files)}."
        text = (
            await run_vision(
                prompt,
                images,
                model=model,
                num_ctx=num_ctx,
            )
            or ""
        ).strip()
        if text:
            chunks.append(f"--- pages {first}-{last} ---\n{text}")
    return "\n\n".join(chunks).strip()
