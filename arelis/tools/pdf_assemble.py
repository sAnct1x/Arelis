"""Merge, split, and rotate PDFs under workspace roots.

pypdf PdfReader / PdfWriter — the same stack doc_extract and the document
index already use. Form fill is not here: appearances and XFA are not a
one-liner in pypdf, and a half-filled form that looks blank is worse than
saying no. Use `document` to write a new PDF instead.

Default dest is <active-root>/outputs/<stem>.pdf (unique, never the source).
An explicit dest goes through WorkspaceRoots.resolve(..., for_create=True).
Sources go through resolve_read. Parent registers this like document:

    from arelis.tools.pdf_assemble import PdfAssembleTool
    if attended and (tools_cfg.get("pdf") or {}).get("enabled", True):
        registry.register(PdfAssembleTool(workspace))

All three verbs create a file. risk=write so Allow stays without a policy
row. If this tool is ever flipped to risk=read:

    PDF_WRITE_ACTIONS = frozenset({"merge", "split", "rotate"})
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from arelis.paths import display_path, ensure
from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

# Parent policy.py: add this under "pdf" if risk is ever read + write-actions.
PDF_WRITE_ACTIONS = frozenset({"merge", "split", "rotate"})
WRITE_ACTIONS = PDF_WRITE_ACTIONS

_ACTIONS = PDF_WRITE_ACTIONS
_SAFE_STEM = re.compile(r"[^a-zA-Z0-9._-]+")
_PAGE_TOKEN = re.compile(r"^(\d+)(?:-(\d+))?$")

MAX_SOURCE_PAGES = 50
MAX_FILE_BYTES = 8 * 1024 * 1024


def parse_pages(spec: str) -> list[int]:
    """1-based inclusive ranges: ``1-3,5`` → [1, 2, 3, 5]. Order is kept."""
    text = (spec or "").strip()
    if not text:
        raise ValueError("pages is empty.")
    out: list[int] = []
    seen: set[int] = set()
    for raw in text.split(","):
        token = raw.strip()
        if not token:
            continue
        match = _PAGE_TOKEN.fullmatch(token)
        if match is None:
            raise ValueError(f"pages {spec!r} is not a page list (try 1-3,5).")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < 1:
            raise ValueError("pages are 1-based; 0 is not a page.")
        if end < start:
            raise ValueError(f"page range {token} is backwards.")
        for number in range(start, end + 1):
            if number in seen:
                continue
            seen.add(number)
            out.append(number)
    if not out:
        raise ValueError("pages is empty.")
    return out


def _unique_dest(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1


def _stem(raw: str, fallback: str) -> str:
    leaf = Path((raw or "").replace("\\", "/")).name
    stem = _SAFE_STEM.sub("-", Path(leaf).stem).strip(".-")
    return stem or fallback


def _parse_path_list(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


def _degrees(raw: Any) -> int:
    if raw is None or raw == "":
        raise ValueError("rotate needs degrees: 90, 180, or 270.")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("rotate degrees must be 90, 180, or 270.") from exc
    if value not in {90.0, 180.0, 270.0}:
        raise ValueError("rotate degrees must be 90, 180, or 270 — not 0 or 45.")
    return int(value)


class PdfAssembleTool:
    name = "pdf"
    description = (
        "Merge, split, or rotate PDFs under workspace roots. Writes a NEW file "
        "(never overwrites a source). Default dest is the active project's "
        "outputs/ folder; pass dest= for another workspace path. merge takes "
        "paths (comma list or JSON array) in that order. split needs path plus "
        "pages (1-based, e.g. 1-3,5). rotate needs path plus degrees 90/180/270 "
        "and optional pages (those pages only, rotated). Caps: 50 source pages "
        "copied, 8 MB per file. Form fill is not supported — pypdf appearances "
        "are not reliable here; use document to make a new PDF. Allow is required. "
        "Do not use doc_extract (that reads) or document (that creates from text)."
    )
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["merge", "split", "rotate"],
                "description": (
                    "merge concatenates PDFs in paths order; split writes the "
                    "pages list; rotate writes a new file at 90/180/270 degrees"
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Source PDF for split/rotate, or a single merge input "
                    "(name:relative/path when multi-root)"
                ),
            },
            "paths": {
                "type": "string",
                "description": (
                    "merge: comma-separated paths or a JSON array, in the "
                    "order they should appear"
                ),
            },
            "pages": {
                "type": "string",
                "description": (
                    "1-based page list for split (required) or rotate "
                    "(optional), e.g. 1-3,5"
                ),
            },
            "degrees": {
                "type": "integer",
                "description": "rotate only: 90, 180, or 270 clockwise",
                "enum": [90, 180, 270],
            },
            "dest": {
                "type": "string",
                "description": (
                    "Output PDF path under a workspace root. Omitted: a new "
                    "file under the active project's outputs/ — never the source"
                ),
            },
        },
        "required": ["action"],
    }

    def __init__(self, roots: list[str] | WorkspaceRoots) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))

    async def run(self, **kwargs: Any) -> ToolResult:
        return await asyncio.to_thread(self._run, kwargs)

    def _run(self, kwargs: dict[str, Any]) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                ok=False,
                output=(
                    "Unknown action. Use merge, split, or rotate. "
                    "Form fill is not supported."
                ),
            )
        try:
            sources = self._sources(action, kwargs)
            picked = self._page_picks(action, kwargs, sources)
            dest = self._dest(
                str(kwargs.get("dest") or "").strip(),
                action=action,
                sources=sources,
                pages=picked,
                degrees=kwargs.get("degrees"),
            )
            n_pages, degrees = self._write(action, sources, picked, dest, kwargs)
        except PermissionError as exc:
            return ToolResult(ok=False, output=str(exc))
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not assemble PDF: {exc}")
        except Exception as exc:
            return ToolResult(ok=False, output=f"Could not assemble PDF: {exc}")

        shown = display_path(dest)
        extra = f", rotated {degrees}" if degrees else ""
        return ToolResult(
            ok=True,
            output=(
                f"Wrote {shown} ({n_pages} page{'s' if n_pages != 1 else ''}"
                f"{extra}). Open that file."
            ),
            data={
                "path": shown,
                "abs_path": str(dest.resolve()),
                "action": action,
                "pages": picked,
                "n_pages": n_pages,
                "degrees": degrees,
                "sources": [display_path(path) for path in sources],
            },
        )

    def _sources(self, action: str, kwargs: dict[str, Any]) -> list[Path]:
        raw_paths = _parse_path_list(kwargs.get("paths"))
        raw_path = str(kwargs.get("path") or "").strip()
        if action == "merge":
            items = raw_paths or _parse_path_list(raw_path)
            if not items:
                raise ValueError("merge needs paths (comma list or JSON array).")
        else:
            if not raw_path:
                raise ValueError(f"{action} needs path.")
            items = [raw_path]
        found: list[Path] = []
        for item in items:
            resolved = self.workspace.resolve_read(item)
            path = resolved.path
            if not path.is_file():
                raise ValueError(f"No PDF at {item!r}.")
            if path.suffix.lower() != ".pdf":
                raise ValueError(f"{item!r} is not a PDF.")
            try:
                size = path.stat().st_size
            except OSError as exc:
                raise ValueError(f"Cannot read {item!r}: {exc}") from exc
            if size > MAX_FILE_BYTES:
                raise ValueError(
                    f"{item!r} is over {MAX_FILE_BYTES // (1024 * 1024)} MB."
                )
            found.append(path)
        return found

    def _page_picks(
        self,
        action: str,
        kwargs: dict[str, Any],
        sources: list[Path],
    ) -> list[int]:
        from pypdf import PdfReader

        raw = str(kwargs.get("pages") or "").strip()
        if action == "split" and not raw:
            raise ValueError("split needs pages, e.g. 1-3,5.")
        wanted = parse_pages(raw) if raw else None

        counts: list[int] = []
        total = 0
        for path in sources:
            reader = PdfReader(str(path))
            if getattr(reader, "is_encrypted", False):
                raise ValueError(f"{path.name} is encrypted.")
            n = len(reader.pages)
            if n < 1:
                raise ValueError(f"{path.name} has no pages.")
            counts.append(n)
            total += n

        if action == "merge":
            if total > MAX_SOURCE_PAGES:
                raise ValueError(
                    f"Refusing {total} source pages (cap {MAX_SOURCE_PAGES})."
                )
            return list(range(1, total + 1))

        n = counts[0]
        if wanted is None:
            if n > MAX_SOURCE_PAGES:
                raise ValueError(
                    f"Refusing {n} source pages (cap {MAX_SOURCE_PAGES})."
                )
            return list(range(1, n + 1))
        missing = [page for page in wanted if page > n]
        if missing:
            raise ValueError(
                f"{sources[0].name} has {n} page(s); {missing[0]} is past the end."
            )
        if len(wanted) > MAX_SOURCE_PAGES:
            raise ValueError(
                f"Refusing {len(wanted)} source pages (cap {MAX_SOURCE_PAGES})."
            )
        return wanted

    def _dest(
        self,
        raw: str,
        *,
        action: str,
        sources: list[Path],
        pages: list[int],
        degrees: Any,
    ) -> Path:
        source_set = {path.resolve() for path in sources}
        stem = self._default_stem(action, sources, pages, degrees)
        if raw:
            leaf = Path(raw.replace("\\", "/"))
            dest_str = raw if leaf.suffix.lower() == ".pdf" else f"{raw}.pdf"
            dest = self.workspace.resolve(dest_str, for_create=True).path
            if dest.resolve() in source_set:
                raise ValueError(
                    "Refusing to overwrite a source PDF. Omit dest or pick another path."
                )
            if dest.exists():
                dest = _unique_dest(dest.parent, dest.stem, ".pdf")
        else:
            folder = self.workspace.resolve("outputs", for_create=True).path
            ensure(folder)
            dest = _unique_dest(folder, stem, ".pdf")
            if dest.resolve() in source_set:
                dest = _unique_dest(folder, f"{stem}-out", ".pdf")
        ensure(dest.parent)
        if dest.resolve() in source_set:
            raise ValueError(
                "Refusing to overwrite a source PDF. Omit dest or pick another path."
            )
        return dest

    def _default_stem(
        self,
        action: str,
        sources: list[Path],
        pages: list[int],
        degrees: Any,
    ) -> str:
        base = _stem(sources[0].name, action)
        if action == "merge":
            return f"{base}-merged" if len(sources) == 1 else "merged"
        if action == "split":
            label = ",".join(str(n) for n in pages[:8])
            return _stem(f"{base}-p{label}", f"{base}-split")
        deg = ""
        try:
            deg = str(_degrees(degrees))
        except ValueError:
            deg = ""
        return f"{base}-rot{deg}" if deg else f"{base}-rot"

    def _write(
        self,
        action: str,
        sources: list[Path],
        pages: list[int],
        dest: Path,
        kwargs: dict[str, Any],
    ) -> tuple[int, int | None]:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        degrees: int | None = None
        if action == "merge":
            for path in sources:
                writer.append(str(path))
        elif action == "split":
            reader = PdfReader(str(sources[0]))
            for number in pages:
                writer.add_page(reader.pages[number - 1])
        else:
            degrees = _degrees(kwargs.get("degrees"))
            reader = PdfReader(str(sources[0]))
            for number in pages:
                page = reader.pages[number - 1]
                page.rotate(degrees)
                writer.add_page(page)
        try:
            with dest.open("wb") as handle:
                writer.write(handle)
        except Exception:
            if dest.exists():
                dest.unlink(missing_ok=True)
            raise
        return len(writer.pages), degrees
