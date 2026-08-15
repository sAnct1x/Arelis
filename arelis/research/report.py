"""Fixed-shape research markdown: Question / Findings / Uncertainties / Sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from arelis.config import PROJECT_ROOT

_SLUG = re.compile(r"[^a-z0-9]+")
_DEFAULT_DIR = PROJECT_ROOT / "outputs" / "research"


@dataclass(frozen=True)
class SourceHit:
    title: str
    url: str
    excerpt: str = ""


def slugify(text: str, *, max_len: int = 48) -> str:
    base = _SLUG.sub("-", (text or "").strip().lower()).strip("-") or "report"
    return base[:max_len].rstrip("-")


def excerpt_text(text: str, *, max_chars: int = 600) -> str:
    """Short deterministic excerpt — first paragraphs, not an LLM summary."""
    body = (text or "").strip()
    if not body:
        return ""
    # Drop common scrape header lines (Title:/By:/Published:) for Findings.
    lines = [
        ln
        for ln in body.splitlines()
        if ln.strip()
        and not re.match(
            r"(?i)^(title|by|byline|published|site|strategy|words?)\s*:",
            ln.strip(),
        )
    ]
    joined = " ".join(ln.strip() for ln in lines) if lines else body
    joined = re.sub(r"\s+", " ", joined).strip()
    limit = max(80, int(max_chars))
    if len(joined) <= limit:
        return joined
    cut = joined[: limit - 1].rsplit(" ", 1)[0]
    return (cut or joined[: limit - 1]).rstrip() + "…"


def render_report(
    question: str,
    *,
    sources: list[SourceHit],
    failed: list[str] | None = None,
) -> str:
    """Fixed markdown sections. Sources list only successful hits."""
    q = (question or "").strip() or "(no question)"
    findings_parts: list[str] = []
    for i, hit in enumerate(sources, start=1):
        title = hit.title or hit.url
        excerpt = (hit.excerpt or "").strip()
        if excerpt:
            findings_parts.append(f"{i}. **{title}** — {excerpt}")
        else:
            findings_parts.append(f"{i}. **{title}** — (no extractable text)")
    findings = (
        "\n".join(findings_parts)
        if findings_parts
        else "_No successful page extracts._"
    )

    uncertainties: list[str] = []
    if not sources:
        uncertainties.append("No pages scraped successfully; findings are empty.")
    elif len(sources) == 1:
        uncertainties.append(
            "Only one independent source succeeded; treat claims as single-source."
        )
    if failed:
        uncertainties.append(
            "Failed or skipped URLs: " + "; ".join(failed[:8])
        )
    uncertainties.append(
        "Excerpts are truncated tool output, not an LLM synthesis."
    )
    unc_block = "\n".join(f"- {u}" for u in uncertainties)

    source_lines = [
        f"{i}. [{hit.title or hit.url}]({hit.url})"
        for i, hit in enumerate(sources, start=1)
    ]
    sources_block = (
        "\n".join(source_lines) if source_lines else "_None (no successful scrapes)._"
    )

    return (
        f"# Research report\n\n"
        f"## Question\n\n{q}\n\n"
        f"## Findings\n\n{findings}\n\n"
        f"## Uncertainties\n\n{unc_block}\n\n"
        f"## Sources\n\n{sources_block}\n"
    )


def save_report(
    markdown: str,
    *,
    query: str,
    output_dir: Path | str | None = None,
    day: date | None = None,
) -> Path:
    """Write ``YYYY-MM-DD-slug.md`` under the research output directory."""
    root = Path(output_dir) if output_dir else _DEFAULT_DIR
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    stamp = (day or date.today()).isoformat()
    slug = slugify(query)
    path = root / f"{stamp}-{slug}.md"
    if path.exists():
        for n in range(2, 100):
            candidate = root / f"{stamp}-{slug}-{n}.md"
            if not candidate.exists():
                path = candidate
                break
    path.write_text(markdown, encoding="utf-8")
    return path
