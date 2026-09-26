"""Extract text from a local PDF, DOCX, or PPTX under workspace roots."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.core.document_refs import resolve_drop_file
from arelis.core.look import OcrInspect, inspect_ocr_text, ocr_deferral
from arelis.paths import outputs_dir
from arelis.tools.base import ToolResult
from arelis.tools.office_text import (
    extract_docx_text,
    extract_pptx_slides,
    sniff_office_kind,
)
from arelis.tools.pdf_pages import (
    RasterizerMissingError,
    collect_page_images,
    page_digest,
    write_page_images,
)
from arelis.workspace import ResolvedPath, WorkspaceRoots

_MAX_OUTPUT_CHARS = 20_000
_MAX_INK_PAGES = 20
_SUPPORTED = frozenset({".pdf", ".docx", ".pptx"})
_DROP_SUFFIXES = _SUPPORTED
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_TABLEISH_LINE = re.compile(r"\S(?:\t|  +)\S")
_OFFICE_KINDS = frozenset({"docx", "pptx"})


def _fail(tag: str, message: str, **extra: Any) -> ToolResult:
    """Stable fail tags for the ledger / model (scrape-style)."""
    tag = tag if tag.startswith("fail:") else f"fail:{tag}"
    data: dict[str, Any] = {"fail_class": tag}
    data.update(extra)
    return ToolResult(ok=False, output=f"[{tag}] {message}", data=data)


class DocExtractTool:
    name = "doc_extract"
    description = (
        "Extract text from a local PDF, Word (.docx), or PowerPoint (.pptx) "
        "under workspace roots. Optional page_start/page_end (PDF pages or "
        "PPTX slides). DOCX tables are cell text. Scanned PDFs have no text "
        "layer — this reads the page pictures. Do not invent quotes or ask "
        "them to paste. Not for images or .exe."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to PDF, DOCX, or PPTX, or name:relative/path",
            },
            "page_start": {
                "type": "integer",
                "description": "First page to extract (1-based, inclusive)",
            },
            "page_end": {
                "type": "integer",
                "description": "Last page to extract (1-based, inclusive)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters of extracted text to return",
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        roots: list[str] | WorkspaceRoots,
        *,
        max_chars: int = _MAX_OUTPUT_CHARS,
        page_dir: Path | None = None,
        ocr_inspect: Callable[[Path], OcrInspect] | None = None,
    ) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.roots = [r.path for r in self.workspace.roots]
        self.max_chars = max(256, int(max_chars))
        self.page_dir = page_dir
        self._ocr_inspect = ocr_inspect

    def _resolve(self, path_str: str):
        try:
            return self.workspace.resolve_read(path_str)
        except Exception as first:
            drop = resolve_drop_file(path_str, suffixes=_DROP_SUFFIXES)
            if drop:
                path = Path(drop)
                return ResolvedPath(
                    path=path,
                    root_name="outputs",
                    root=path.parent,
                )
            raise first

    async def run(self, **kwargs: Any) -> ToolResult:
        path_str = kwargs.get("path")
        if not path_str:
            return _fail("other", "Missing path")
        page_start = kwargs.get("page_start")
        page_end = kwargs.get("page_end")
        max_chars = kwargs.get("max_chars", self.max_chars)
        try:
            max_chars_i = int(max_chars)
        except (TypeError, ValueError):
            max_chars_i = self.max_chars
        return await asyncio.to_thread(
            self._extract,
            str(path_str),
            page_start,
            page_end,
            max_chars_i,
        )

    def _extract(
        self,
        path_str: str,
        page_start: Any,
        page_end: Any,
        max_chars: int,
    ) -> ToolResult:
        try:
            resolved = self._resolve(path_str)
        except PermissionError as exc:
            return _fail("other", str(exc))
        except (ValueError, OSError) as exc:
            return _fail("other", str(exc))

        path = resolved.path
        display = resolved.qualified(multi=len(self.workspace) > 1)
        if not path.is_file():
            return _fail("other", f"Not a file: {display}")

        kind = _document_kind(path)
        if kind is None:
            return _unsupported(path, display)
        if kind == "docx":
            return self._extract_docx(path, display, resolved.root_name, max_chars)
        if kind == "pptx":
            return self._extract_pptx(
                path, display, resolved.root_name, page_start, page_end, max_chars
            )
        return self._extract_pdf(
            path, display, resolved.root_name, page_start, page_end, max_chars
        )

    def _extract_docx(
        self,
        path: Path,
        display: str,
        root_name: str,
        max_chars: int,
    ) -> ToolResult:
        """Word files never go through PdfReader or the ink page-image path."""
        try:
            body = extract_docx_text(path)
        except ImportError:
            return _fail(
                "other",
                "python-docx is not installed; pip install python-docx",
            )
        except Exception as exc:
            return _fail("other", f"doc_extract failed to open DOCX: {exc}", path=display)
        if not body:
            return _fail("empty", f"DOCX has no extractable text: {display}", path=display)
        return _text_result(
            display,
            body,
            [1],
            1,
            max_chars,
            source="docx",
            abs_path=str(path),
            root_name=root_name,
        )

    def _extract_pptx(
        self,
        path: Path,
        display: str,
        root_name: str,
        page_start: Any,
        page_end: Any,
        max_chars: int,
    ) -> ToolResult:
        try:
            slides = extract_pptx_slides(path)
        except Exception as exc:
            return _fail("other", f"doc_extract failed to open PPTX: {exc}", path=display)
        n_pages = len(slides)
        if n_pages == 0:
            return _fail("empty", f"PPTX has no slides: {display}", path=display)
        start_i, end_i, range_err = _page_bounds(page_start, page_end, n_pages)
        if range_err:
            return _fail("other", range_err, path=display)
        used_pages = list(range(start_i + 1, end_i + 2))
        blocks = []
        for number in used_pages:
            text = (slides[number - 1] or "").strip()
            blocks.append(f"slide {number}:\n{text}" if text else f"slide {number}:")
        body = "\n\n".join(blocks).strip()
        if not any((slides[n - 1] or "").strip() for n in used_pages):
            return _fail("empty", f"PPTX has no extractable text: {display}", path=display)
        return _text_result(
            display,
            body,
            used_pages,
            n_pages,
            max_chars,
            source="pptx",
            abs_path=str(path),
            root_name=root_name,
        )

    def _extract_pdf(
        self,
        path: Path,
        display: str,
        root_name: str,
        page_start: Any,
        page_end: Any,
        max_chars: int,
    ) -> ToolResult:
        try:
            from pypdf import PdfReader
        except ImportError:
            return _fail(
                "other",
                "pypdf is not installed; pip install pypdf",
            )

        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            return _fail("other", f"doc_extract failed to open PDF: {exc}")

        if getattr(reader, "is_encrypted", False):
            unlocked = False
            try:
                # Empty-password PDFs are common; anything else is a hard fail
                # (no password argument on this tool — by design).
                status = reader.decrypt("")  # type: ignore[misc]
                unlocked = bool(status) and not reader.is_encrypted
            except Exception:
                unlocked = False
            if not unlocked:
                return _fail("encrypted", f"PDF is encrypted: {display}", path=display)

        n_pages = len(reader.pages)
        if n_pages == 0:
            return _fail("empty", f"PDF has no pages: {display}", path=display)

        start_i, end_i, range_err = _page_bounds(page_start, page_end, n_pages)
        if range_err:
            return _fail("other", range_err, path=display)

        chunks: list[str] = []
        layout_chunks: list[str] = []
        used_pages: list[int] = []
        for idx in range(start_i, end_i + 1):
            try:
                text = reader.pages[idx].extract_text() or ""
            except Exception as exc:
                return _fail(
                    "other",
                    f"Failed extracting page {idx + 1}: {exc}",
                    path=display,
                )
            text = text.strip()
            if text:
                chunks.append(text)
            layout = _layout_text(reader.pages[idx])
            if layout:
                layout_chunks.append(layout)
            used_pages.append(idx + 1)

        body = "\n\n".join(chunks).strip()
        fields = _pdf_form_fields(reader)
        extra: dict[str, Any] = {}
        table_note = _tableish_note(layout_chunks, body)
        if fields:
            extra["form_fields"] = fields
            field_block = _format_form_fields(fields)
            body = f"{body}\n\n{field_block}".strip() if body else field_block
        if table_note:
            extra["table_structure"] = "extracted text, not a parser"
            extra["table_text"] = table_note
            body = f"{body}\n\n{table_note}".strip() if body else table_note

        if not body:
            return self._extract_ink(
                path,
                display,
                root_name,
                start_i,
                end_i,
                n_pages,
                used_pages,
                max_chars,
            )

        return _text_result(
            display,
            body,
            used_pages,
            n_pages,
            max_chars,
            source="text",
            abs_path=str(path),
            root_name=root_name,
            extra=extra or None,
        )

    def _extract_ink(
        self,
        path: Path,
        display: str,
        root_name: str,
        start_i: int,
        end_i: int,
        n_pages: int,
        used_pages: list[int],
        max_chars: int,
    ) -> ToolResult:
        """No text layer: write page pictures. OCR only if we cannot look."""
        cap_end = min(end_i, start_i + _MAX_INK_PAGES - 1)
        try:
            pages = collect_page_images(path, start_i, cap_end)
        except RasterizerMissingError as exc:
            return _fail(
                "rasterizer",
                (
                    f"{display} has no text layer and no embedded page images, "
                    f"and the rasterizer is missing ({exc}). "
                    "Install pypdfium2 (pip install -e .) so scanned pages "
                    "can be rendered. Do not ask them to paste."
                ),
                path=display,
                source="empty",
            )
        if not pages:
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:empty] No extractable text or page images in "
                    f"{display} (pages {used_pages[0]}-{used_pages[-1]}). "
                    "Do not ask them to paste. Say the PDF could not be read."
                ),
                data={
                    "path": display,
                    "pages": used_pages,
                    "chars": 0,
                    "fail_class": "fail:empty",
                    "source": "empty",
                },
            )

        dest = self.page_dir or (
            outputs_dir() / "images" / "pdf_pages" / f"{path.stem}_{page_digest(path)}"
        )
        written = write_page_images(pages, dest)
        # Default Tesseract on tablet ink is slow and garbage. Only OCR
        # when a test (or caller) injected an inspector.
        ocr_body, ocr_ok = ("", False)
        if self._ocr_inspect is not None:
            ocr_body, ocr_ok = self._ocr_pages(written)
        if ocr_ok and ocr_body:
            return _text_result(
                display,
                ocr_body,
                [item.page for item in pages],
                n_pages,
                max_chars,
                source="ocr",
                abs_path=str(path),
                root_name=root_name,
                page_images=[str(p) for p in written],
            )

        more = ""
        if cap_end < end_i:
            more = (
                f"\nStopped at page {cap_end + 1} of {end_i + 1}. "
                f"Call again with page_start={cap_end + 2}."
            )
        listing = "\n".join(
            f"  {item.page}: {dest_path}"
            for item, dest_path in zip(pages, written, strict=True)
        )
        output = (
            f"path: {display}\n"
            f"pages: {pages[0].page}-{pages[-1].page} of {n_pages}\n"
            f"source: ink\n"
            "No text layer — scanned or handwritten PDF.\n"
            "Page images (call vision on each path; do not ask them to paste; "
            "do not give up):\n"
            f"{listing}{more}"
        )
        return ToolResult(
            ok=True,
            output=output,
            data={
                "path": display,
                "pages": [item.page for item in pages],
                "chars": 0,
                "truncated": cap_end < end_i,
                "abs_path": str(path),
                "root_name": root_name,
                "source": "ink",
                "page_images": [str(p) for p in written],
                "n_pages": n_pages,
            },
        )

    def _ocr_pages(self, paths: list[Path]) -> tuple[str, bool]:
        """Return (text, accepted). Missing Tesseract is not a failure."""
        chunks: list[str] = []
        confs: list[float] = []
        for path in paths:
            try:
                inspect = self._inspect_page(path)
            except Exception:
                # One bad page must not abort the rest of the extract.
                return "", False
            if inspect.text:
                chunks.append(inspect.text)
            if inspect.mean_conf is not None:
                confs.append(inspect.mean_conf)
        body = "\n\n".join(chunks).strip()
        mean = (sum(confs) / len(confs)) if confs else None
        features = inspect_ocr_text(body, mean_conf=mean)
        if ocr_deferral(features) is not None:
            return body, False
        return body, True

    def _inspect_page(self, path: Path) -> OcrInspect:
        if self._ocr_inspect is not None:
            return self._ocr_inspect(path)
        from arelis.tools.ocr import run_tesseract_inspect, tesseract_available

        if not tesseract_available():
            return inspect_ocr_text("")
        return run_tesseract_inspect(path)


def _text_result(
    display: str,
    body: str,
    used_pages: list[int],
    n_pages: int,
    max_chars: int,
    *,
    source: str,
    abs_path: str,
    root_name: str,
    page_images: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    chars = len(body)
    max_chars = max(256, int(max_chars))
    truncated = False
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n\n[truncated to {max_chars} chars]"
        truncated = True
    first = used_pages[0] if used_pages else 1
    last = used_pages[-1] if used_pages else n_pages
    header = f"path: {display}\npages: {first}-{last} of {n_pages}\nsource: {source}\n"
    data: dict[str, Any] = {
        "path": display,
        "pages": used_pages,
        "chars": chars,
        "truncated": truncated,
        "abs_path": abs_path,
        "root_name": root_name,
        "source": source,
    }
    if page_images:
        data["page_images"] = page_images
    if extra:
        data.update(extra)
    return ToolResult(ok=True, output=header + body, data=data)


def _document_kind(path: Path) -> str | None:
    """Content wins when the bytes are unambiguously PDF or Office.

    A .docx named notes.pdf is a lie: it is still a docx. Suffix is the
    fallback only when the file does not speak (empty, truncated, unknown).
    A zip that is not Office is never sent down the PDF ink path.
    """
    try:
        head = path.read_bytes()[:8]
    except OSError:
        head = b""
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(b"PK"):
        sniffed = sniff_office_kind(path)
        if sniffed in _OFFICE_KINDS:
            return sniffed
        return None
    suffix = path.suffix.lower()
    if suffix in _SUPPORTED:
        return suffix.lstrip(".")
    return None


def _unsupported(path: Path, display: str) -> ToolResult:
    suffix = path.suffix.lower()
    if suffix in _IMAGE_SUFFIXES:
        return _fail(
            "unsupported",
            "This is an image — use vision to describe it, or ocr "
            "(action=text) to read text in it. doc_extract reads "
            ".pdf, .docx, and .pptx.",
            path=display,
        )
    return _fail(
        "unsupported",
        f"Unsupported file type: {path.suffix or '(none)'} "
        "(want .pdf, .docx, or .pptx)",
        path=display,
    )


def _pdf_form_fields(reader: Any) -> dict[str, str]:
    try:
        raw = reader.get_form_text_fields() or {}
    except Exception:
        # AcroForm is optional; a broken field dict is not a failed extract.
        return {}
    out: dict[str, str] = {}
    for name, value in raw.items():
        if name is None:
            continue
        out[str(name)] = "" if value is None else str(value)
    return out


def _format_form_fields(fields: dict[str, str]) -> str:
    lines = ["form fields:"]
    for name, value in fields.items():
        lines.append(f"  {name}: {value}")
    return "\n".join(lines)


def _layout_text(page: Any) -> str:
    try:
        text = page.extract_text(extraction_mode="layout") or ""
    except Exception:
        # Layout mode is a hint. If pypdf rejects it, the page still has
        # the ordinary text extract above.
        return ""
    return text.strip()


def _tableish_note(layout_chunks: list[str], body: str) -> str:
    """Best-effort columns from the text layer. Not a table parser."""
    layout = "\n\n".join(chunk for chunk in layout_chunks if chunk).strip()
    if not layout or layout == body.strip():
        return ""
    hits = [line for line in layout.splitlines() if _TABLEISH_LINE.search(line)]
    if len(hits) < 2:
        return ""
    return (
        "[extracted text — not a guaranteed table parse]\n" + layout
    )


def _page_bounds(
    page_start: Any,
    page_end: Any,
    n_pages: int,
) -> tuple[int, int, str | None]:
    """Return 0-based inclusive start/end or an error message."""
    start = 1 if page_start is None else page_start
    end = n_pages if page_end is None else page_end
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        return 0, 0, "page_start and page_end must be integers"
    if start_i < 1 or end_i < 1:
        return 0, 0, "page_start and page_end are 1-based (minimum 1)"
    if start_i > n_pages:
        return 0, 0, f"page_start {start_i} past end of document ({n_pages} pages)"
    if end_i > n_pages:
        end_i = n_pages
    if end_i < start_i:
        return 0, 0, f"page_end {end_i} is before page_start {start_i}"
    return start_i - 1, end_i - 1, None


def build_simple_pdf_bytes(text: str) -> bytes:
    """Minimal one-page PDF with extractable Helvetica text (tests/fixtures)."""
    safe = (
        (text or " ")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    content = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET"
    content_b = content.encode("latin-1", errors="replace")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(content_b)} >>\nstream\n".encode("latin-1")
            + content_b
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    body = b"".join(objects)
    offsets = [0]
    pos = len(header)
    for obj in objects:
        offsets.append(pos)
        pos += len(obj)
    xref_start = pos
    xref = [f"xref\n0 {len(offsets)}\n".encode("latin-1"), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("latin-1"))
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode("latin-1")
    return header + body + b"".join(xref) + trailer
