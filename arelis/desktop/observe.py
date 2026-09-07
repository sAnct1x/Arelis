"""A look is sight: grab, then read. Highlighting is not required.

Whole-page OCR first. If they named a problem / paragraph and it is
missing — or the page is huge and the first pass is empty — tile the
still and read again. Misses stay misses. Do not invent the page.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_ORD = (
    r"(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|"
    r"sixth|seventh|eighth|ninth|tenth)"
)
_PROBLEM = re.compile(r"(?i)\b(?:problem|question)\s+([\d.]+)\b")
_PARAGRAPH = re.compile(rf"(?i)\b({_ORD}\s+paragraph)\b")
_BARE_NUMBER = re.compile(r"^[\d.]+$")

OcrFn = Callable[[Path], str]


@dataclass(frozen=True)
class ObserveRead:
    text: str
    found: tuple[str, ...]
    missed: tuple[str, ...]
    tiled: bool
    source: str


def look_needles(text: str) -> list[str]:
    """Problem numbers and paragraph names they asked about."""
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    if _BARE_NUMBER.match(raw):
        out.append(raw)
    for match in _PROBLEM.finditer(raw):
        out.append(match.group(1))
    for match in _PARAGRAPH.finditer(raw):
        out.append(match.group(1).lower())
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def needle_in(haystack: str, needle: str) -> bool:
    blob = " ".join((haystack or "").lower().split())
    want = " ".join((needle or "").lower().split())
    return bool(want) and want in blob


def tile_boxes(
    width: int,
    height: int,
    *,
    max_edge: int = 1600,
    overlap: float = 0.12,
) -> list[tuple[int, int, int, int]]:
    """Overlapping tiles so a problem number on a 4K page can still be read."""
    if width <= 0 or height <= 0:
        return []
    if width <= max_edge and height <= max_edge:
        return [(0, 0, width, height)]
    step_x = max(1, int(max_edge * (1.0 - overlap)))
    step_y = max(1, int(max_edge * (1.0 - overlap)))
    boxes: list[tuple[int, int, int, int]] = []
    y = 0
    while y < height:
        h = min(max_edge, height - y)
        x = 0
        while x < width:
            w = min(max_edge, width - x)
            boxes.append((x, y, w, h))
            if x + w >= width:
                break
            x += step_x
        if y + h >= height:
            break
        y += step_y
    return boxes


def _default_ocr(path: Path) -> str:
    from arelis.tools.ocr import run_tesseract

    return run_tesseract(path)


def read_still(
    path: Path,
    *,
    needles: list[str] | None = None,
    ocr: OcrFn | None = None,
    max_edge: int = 1600,
) -> ObserveRead:
    """Read a look still. Tile when a named needle is missing on a huge page."""
    reader = ocr or _default_ocr
    wanted = [n for n in (needles or []) if str(n).strip()]
    whole = (reader(path) or "").strip()
    found = [n for n in wanted if needle_in(whole, n)]
    missed = [n for n in wanted if n not in found]
    if wanted and not missed:
        return ObserveRead(
            text=whole, found=tuple(found), missed=(), tiled=False, source="whole"
        )
    if not wanted and whole:
        return ObserveRead(
            text=whole, found=(), missed=(), tiled=False, source="whole"
        )
    try:
        from PIL import Image

        with Image.open(path) as im:
            width, height = im.size
            boxes = tile_boxes(width, height, max_edge=max_edge)
            if len(boxes) <= 1:
                return ObserveRead(
                    text=whole,
                    found=tuple(found),
                    missed=tuple(missed),
                    tiled=False,
                    source="whole",
                )
            rgb = im.convert("RGB")
    except OSError as exc:
        raise RuntimeError(f"Could not open still {path}: {exc}") from exc
    chunks = [whole] if whole else []
    for x, y, w, h in boxes:
        tile_path = _write_tile(rgb, x, y, w, h)
        try:
            piece = (reader(tile_path) or "").strip()
        finally:
            tile_path.unlink(missing_ok=True)
        if not piece:
            continue
        chunks.append(piece)
        joined = "\n".join(chunks)
        found = [n for n in wanted if needle_in(joined, n)]
        missed = [n for n in wanted if n not in found]
        if wanted and not missed:
            break
    return ObserveRead(
        text="\n".join(chunks).strip(),
        found=tuple(found),
        missed=tuple(missed),
        tiled=True,
        source="tiles",
    )


def _write_tile(image: object, x: int, y: int, w: int, h: int) -> Path:
    crop = image.crop((x, y, x + w, y + h))  # type: ignore[attr-defined]
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    dest = Path(handle.name)
    handle.close()
    crop.save(dest, "PNG")
    return dest


def format_observe(seen: ObserveRead) -> str:
    """Speakable receipt for the model. Misses stay misses."""
    how = "tiled pass" if seen.tiled else "whole page"
    lines = [f"Read ({how}):"]
    body = (seen.text or "").strip()
    if body:
        lines.append(body)
    else:
        lines.append("(no readable text)")
    if seen.found:
        lines.append("Found: " + ", ".join(seen.found))
    if seen.missed:
        lines.append(
            "Could not resolve: "
            + ", ".join(seen.missed)
            + ". I will not invent it."
        )
    return "\n".join(lines)
