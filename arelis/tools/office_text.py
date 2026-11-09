"""Read text out of local Office files. No cloud. No python-pptx."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

_SLIDE_NAME = re.compile(r"ppt/slides/slide(\d+)\.xml$")
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def sniff_office_kind(path: Path) -> str:
    """Return 'docx' or 'pptx' from the zip, or '' if it is not Office.

    Filename is ignored. A Word file saved as notes.pdf is still a docx.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return ""
    if "word/document.xml" in names:
        return "docx"
    if any(_SLIDE_NAME.match(name) for name in names):
        return "pptx"
    types = ""
    if "[Content_Types].xml" in names:
        try:
            with zipfile.ZipFile(path) as zf:
                types = zf.read("[Content_Types].xml").decode("utf-8", errors="replace")
        except (OSError, zipfile.BadZipFile, KeyError):
            types = ""
    if "wordprocessingml" in types:
        return "docx"
    if "presentationml" in types:
        return "pptx"
    return ""


def extract_docx_text(path: Path) -> str:
    """The document as markdown, in reading order.

    Headings keep their level, list paragraphs become bullets, and each table
    sits where it is in the document as a markdown table. This is what
    doc_extract shows and what document from_path= converts, so a docx turned
    into a PDF or markdown file keeps its structure.
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    chunks: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            line = _docx_paragraph(Paragraph(child, doc))
            if line:
                chunks.append(line)
        elif tag == "tbl":
            rendered = _render_docx_table(Table(child, doc))
            if rendered:
                chunks.append(rendered)
    return "\n\n".join(chunks).strip()


def _docx_paragraph(paragraph: object) -> str:
    text = (getattr(paragraph, "text", "") or "").strip()
    if not text:
        return ""
    style = getattr(getattr(paragraph, "style", None), "name", "") or ""
    lowered = style.lower()
    if lowered == "title":
        return f"# {text}"
    match = re.match(r"heading\s*(\d)", lowered)
    if match:
        return "#" * max(1, min(int(match.group(1)), 6)) + f" {text}"
    if lowered.startswith("list number"):
        return f"1. {text}"
    if lowered.startswith("list") or _numbered(paragraph):
        return f"- {text}"
    return text


def _numbered(paragraph: object) -> bool:
    element = getattr(paragraph, "_p", None)
    p_pr = getattr(element, "pPr", None)
    return p_pr is not None and getattr(p_pr, "numPr", None) is not None


def extract_pptx_slides(path: Path) -> list[str]:
    """One string per slide, ordered by slide number. Empty slides stay ''."""
    slides: dict[int, str] = {}
    try:
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                match = _SLIDE_NAME.match(name)
                if not match:
                    continue
                number = int(match.group(1))
                slides[number] = _slide_text(zf.read(name))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"not a pptx zip: {exc}") from exc
    if not slides:
        return []
    last = max(slides)
    return [slides.get(idx, "") for idx in range(1, last + 1)]


def _render_docx_table(table: object) -> str:
    rows_out: list[list[str]] = []
    for row in getattr(table, "rows", []):
        cells = []
        for cell in getattr(row, "cells", []):
            text = " ".join((cell.text or "").split()).replace("|", "/")
            cells.append(text)
        if any(cells):
            rows_out.append(cells)
    if not rows_out:
        return ""
    width = max(len(r) for r in rows_out)
    lines = []
    for idx, cells in enumerate(rows_out):
        cells = cells + [""] * (width - len(cells))
        lines.append("| " + " | ".join(cells) + " |")
        if idx == 0:
            lines.append("|" + "---|" * width)
    return "\n".join(lines)


def _slide_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    parts: list[str] = []
    for node in root.iter(f"{{{_A_NS}}}t"):
        text = (node.text or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()
