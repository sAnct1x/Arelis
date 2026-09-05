"""Extract text from a local PDF under workspace roots (no cloud OCR)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from arelis.core.document_refs import resolve_drop_file
from arelis.tools.base import ToolResult
from arelis.workspace import ResolvedPath, WorkspaceRoots

_MAX_OUTPUT_CHARS = 20_000
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
        "With multiple projects, qualify paths as name:relative/path. "
        "Do not invent PDF quotes — call this tool first."
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
    ) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.roots = [r.path for r in self.workspace.roots]
        self.max_chars = max(256, int(max_chars))

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
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:empty] No extractable text in {display} "
                    f"(pages {used_pages[0]}-{used_pages[-1]})"
                ),
                data={
                    "path": display,
                    "pages": used_pages,
                    "chars": 0,
                    "fail_class": "fail:empty",
                },
            )

        chars = len(body)
        max_chars = max(256, int(max_chars))
        truncated = False
        if len(body) > max_chars:
            body = body[:max_chars] + f"\n\n[truncated to {max_chars} chars]"
            truncated = True

        header = f"path: {display}\npages: {used_pages[0]}-{used_pages[-1]} of {n_pages}\n"
        return ToolResult(
            ok=True,
            output=header + body,
            data={
                "path": display,
                "pages": used_pages,
                "chars": chars,
                "truncated": truncated,
                "abs_path": str(path),
                "root_name": resolved.root_name,
            },
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
