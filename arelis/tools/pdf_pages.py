"""Pull page pictures out of a PDF that has no text layer.

Phone scans and tablet notes (Samsung / GoodNotes) ship as a JPEG per page.
pypdf.extract_text() is empty on those. The images are still in the file.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RasterizerMissingError(RuntimeError):
    """pypdfium2 is not installed; scanned pages cannot be rendered."""

_INK_PATH_LINE = re.compile(
    r"^\s+\d+:\s+(.+\.(?:jpg|jpeg|png|webp))\s*$",
    re.IGNORECASE,
)
_INK_VISION_QUESTION = (
    "Transcribe this handwritten homework page only. "
    "Equations, labels, short asides. No critique. No commentary. "
    "Do not invent missing work."
)
_MAX_INK_VISION = 4

_IMAGE_SUFFIX = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class PageImage:
    """One rendered or embedded page, 1-based."""

    page: int
    data: bytes
    suffix: str


def is_ink_extract(output: str) -> bool:
    """True when doc_extract wrote page images instead of a text layer."""
    body = (output or "").lower()
    return "source: ink" in body or (
        "no text layer" in body and "page images" in body
    )


def ink_page_paths(output: str) -> list[str]:
    """Absolute page-image paths from an ink doc_extract listing."""
    found: list[str] = []
    for line in (output or "").splitlines():
        match = _INK_PATH_LINE.match(line)
        if match:
            found.append(match.group(1).strip())
    return found


def is_ink_page_image(path: Path | str) -> bool:
    """True for JPEGs doc_extract wrote under outputs/images/pdf_pages/."""
    return "pdf_pages" in {part.lower() for part in Path(path).parts}


def ink_vision_walk(paths: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """One vision call with every page. The tool looks at them one at a time."""
    files = [str(p).strip() for p in paths if str(p).strip()]
    if not files:
        return []
    if len(files) == 1:
        return [("vision", {"path": files[0], "question": _INK_VISION_QUESTION})]
    return [
        (
            "vision",
            {"paths": files, "question": _INK_VISION_QUESTION},
        )
    ]


def ink_vision_notice(paths: list[str], *, limit: int = _MAX_INK_VISION) -> str:
    """Nudge: call vision on the ink pages. Do not dump the listing."""
    listed = "\n".join(f"  vision path={p}" for p in paths[:limit])
    extra = ""
    if len(paths) > limit:
        extra = f"\nThen the remaining {len(paths) - limit} pages."
    return (
        "That PDF is ink (no text layer). Call vision now on these page images "
        f"(several calls in one round are fine):\n{listed}{extra}\n"
        "Do not dump the path list as the answer. Do not ask them to paste."
    )


def page_digest(path: Path) -> str:
    """Short stable id so two PDFs named homework.pdf do not collide."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:8]


def extract_embedded_pages(
    path: Path,
    start_i: int,
    end_i: int,
) -> list[PageImage]:
    """Largest embedded image on each page in the inclusive 0-based range."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    found: list[PageImage] = []
    last = min(end_i, len(reader.pages) - 1)
    for idx in range(max(0, start_i), last + 1):
        page = reader.pages[idx]
        images = list(getattr(page, "images", []) or [])
        if not images:
            continue
        best = max(images, key=_image_area)
        data = getattr(best, "data", None)
        if not data:
            continue
        suffix = _suffix_for(getattr(best, "name", "") or "")
        found.append(PageImage(page=idx + 1, data=bytes(data), suffix=suffix))
    return found


def raster_pages(
    path: Path,
    start_i: int,
    end_i: int,
    *,
    scale: float = 2.0,
) -> list[PageImage]:
    """Render pages with pypdfium2 when there are no embedded images.

    Distinguishes "nothing to render" (empty list) from "I cannot render"
    (RasterizerMissingError). A silent [] on ImportError is how a scanned PDF
    used to read as nothing on the installer.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise RasterizerMissingError(
            "pypdfium2 is not installed. Scanned or handwritten PDFs "
            "cannot be rendered. Install Arelis with its core dependencies "
            "(pip install -e .)."
        ) from exc

    pdf = pdfium.PdfDocument(str(path))
    found: list[PageImage] = []
    last = min(end_i, len(pdf) - 1)
    for idx in range(max(0, start_i), last + 1):
        page = pdf[idx]
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil()
        from io import BytesIO

        buf = BytesIO()
        pil.save(buf, format="PNG")
        found.append(PageImage(page=idx + 1, data=buf.getvalue(), suffix=".png"))
    return found


def collect_page_images(
    path: Path,
    start_i: int,
    end_i: int,
) -> list[PageImage]:
    """Embedded images first; rasterize only pages that had none."""
    embedded = extract_embedded_pages(path, start_i, end_i)
    have = {item.page for item in embedded}
    missing = [
        idx
        for idx in range(max(0, start_i), end_i + 1)
        if (idx + 1) not in have
    ]
    if not missing:
        return embedded
    rasters = raster_pages(path, missing[0], missing[-1])
    extra = [item for item in rasters if item.page not in have]
    merged = embedded + extra
    merged.sort(key=lambda item: item.page)
    return merged


def write_page_images(pages: list[PageImage], dest_dir: Path) -> list[Path]:
    """Write page_01.jpg (etc.) under dest_dir. Returns paths in page order."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for item in pages:
        dest = dest_dir / f"page_{item.page:02d}{item.suffix}"
        dest.write_bytes(item.data)
        written.append(dest)
    return written


def build_jpeg_page_pdf_bytes(jpeg: bytes, width: int, height: int) -> bytes:
    """One-page PDF whose only content is an embedded JPEG (no text layer)."""
    w = max(1, int(width))
    h = max(1, int(height))
    content = f"q {w} 0 0 {h} 0 0 cm /Im0 Do Q\n".encode("ascii")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            + f"/MediaBox [0 0 {w} {h}] ".encode("ascii")
            + b"/Resources << /XObject << /Im0 5 0 R >> >> "
            + b"/Contents 4 0 R >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"endstream\nendobj\n"
        ),
        (
            b"5 0 obj\n<< /Type /XObject /Subtype /Image "
            + f"/Width {w} /Height {h} ".encode("ascii")
            + b"/ColorSpace /DeviceRGB /BitsPerComponent 8 "
            + b"/Filter /DCTDecode "
            + f"/Length {len(jpeg)} >>\nstream\n".encode("ascii")
            + jpeg
            + b"\nendstream\nendobj\n"
        ),
    ]
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = b"".join(objects)
    offsets = [0]
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)
    xref_start = pos
    xref = [f"xref\n0 {len(offsets)}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode("ascii")
    return header + body + b"".join(xref) + trailer


def build_vector_page_pdf_bytes(width: int = 200, height: int = 80) -> bytes:
    """One-page PDF with a filled rectangle only — no text, no images.

    extract_embedded_pages finds nothing here. The only way to see the
    page is raster_pages / pypdfium2, which is the installer hole.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    # Fill the page black so a PNG render is obviously not empty.
    content = f"0 0 0 rg\n0 0 {w} {h} re\nf\n".encode("ascii")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            + f"/MediaBox [0 0 {w} {h}] ".encode("ascii")
            + b"/Contents 4 0 R >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"endstream\nendobj\n"
        ),
    ]
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = b"".join(objects)
    offsets = [0]
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)
    xref_start = pos
    xref = [f"xref\n0 {len(offsets)}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode("ascii")
    return header + body + b"".join(xref) + trailer


def _image_area(image: object) -> int:
    pil = getattr(image, "image", None)
    if pil is not None:
        size = getattr(pil, "size", None)
        if size and len(size) == 2:
            return int(size[0]) * int(size[1])
    data = getattr(image, "data", b"") or b""
    return len(data)


def _suffix_for(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in _IMAGE_SUFFIX:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"
