"""Extract text from a local PDF under workspace roots (no cloud OCR)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from arelis.core.document_refs import resolve_drop_file
from arelis.core.look import OcrInspect, inspect_ocr_text, ocr_deferral
from arelis.paths import outputs_dir
from arelis.tools.base import ToolResult
from arelis.tools.pdf_pages import (
    collect_page_images,
    page_digest,
    write_page_images,
)
from arelis.workspace import ResolvedPath, WorkspaceRoots

_MAX_OUTPUT_CHARS = 20_000
_MAX_INK_PAGES = 20
_SUPPORTED = frozenset({".pdf"})


def _fail(tag: str, message: str, **extra: Any) -> ToolResult:
    """Stable fail tags for the ledger / model (scrape-style)."""
    tag = tag if tag.startswith("fail:") else f"fail:{tag}"
    data: dict[str, Any] = {"fail_class": tag}
    data.update(extra)
    return ToolResult(ok=False, output=f"[{tag}] {message}", data=data)


class DocExtractTool:
    name = "doc_extract"
    description = (
        "Extract text from a local PDF under allowed workspace roots. "
        "Optional 1-based page_start/page_end. "
        "Scanned or handwritten PDFs have no text layer — this tool reads "
        "the page pictures and returns the transcription. Do not call "
        "vision on every page. Do not invent PDF quotes. Do not ask them "
        "to paste."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to PDF, or name:relative/path",
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
        look_pages: Callable[[list[Path]], Awaitable[str]] | None = None,
    ) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.roots = [r.path for r in self.workspace.roots]
        self.max_chars = max(256, int(max_chars))
        self.page_dir = page_dir
        self._ocr_inspect = ocr_inspect
        self._look_pages = look_pages

    def _resolve(self, path_str: str):
        try:
            return self.workspace.resolve_read(path_str)
        except Exception as first:
            drop = resolve_drop_file(path_str, suffixes={".pdf"})
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
        result = await asyncio.to_thread(
            self._extract,
            str(path_str),
            page_start,
            page_end,
            max_chars_i,
        )
        return await self._look_if_ink(result)

    async def _look_if_ink(self, result: ToolResult) -> ToolResult:
        """Ink listing is not the answer — read the pages here, once."""
        data = result.data if isinstance(result.data, dict) else {}
        images = [Path(p) for p in (data.get("page_images") or [])]
        if (
            not result.ok
            or data.get("source") != "ink"
            or self._look_pages is None
            or not images
        ):
            return result
        try:
            body = (await self._look_pages(images) or "").strip()
        except Exception as exc:
            return ToolResult(
                ok=True,
                output=(
                    f"{result.output}\n\n"
                    f"Looking at the pages failed ({type(exc).__name__}: {exc}). "
                    "Call vision on the page images above. Do not ask them to paste."
                ),
                data=dict(data),
            )
        if not body:
            return result
        pages = list(data.get("pages") or [])
        total = int(data.get("n_pages") or (pages[-1] if pages else 1))
        return _text_result(
            str(data.get("path") or ""),
            body,
            pages,
            total,
            self.max_chars,
            source="look",
            abs_path=str(data.get("abs_path") or ""),
            root_name=str(data.get("root_name") or ""),
            page_images=[str(p) for p in images],
        )

    def _extract(
        self,
        path_str: str,
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
            resolved = self._resolve(path_str)
        except PermissionError as exc:
            return _fail("other", str(exc))
        except (ValueError, OSError) as exc:
            return _fail("other", str(exc))

        path = resolved.path
        display = resolved.qualified(multi=len(self.workspace) > 1)
        if not path.is_file():
            return _fail("other", f"Not a file: {display}")
        suffix = path.suffix.lower()
        if suffix not in _SUPPORTED:
            if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return _fail(
                    "other",
                    "This is an image — use vision to describe it, or ocr "
                    "(action=text) to read text in it. doc_extract is PDF-only.",
                    path=display,
                )
            return _fail(
                "other",
                f"Unsupported file type: {path.suffix or '(none)'} (want .pdf)",
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
            used_pages.append(idx + 1)

        body = "\n\n".join(chunks).strip()
        if not body:
            return self._extract_ink(
                path,
                display,
                resolved.root_name,
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
            root_name=resolved.root_name,
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
        pages = collect_page_images(path, start_i, cap_end)
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
    return ToolResult(ok=True, output=header + body, data=data)


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
