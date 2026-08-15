from __future__ import annotations

from bs4 import BeautifulSoup

# Below this, an HTML extraction is treated as an empty JS shell rather than
# useful page content. Short enough that a real one-sentence page still passes.
_MIN_READABLE_CHARS = 40


def extract_text(html: str) -> tuple[str, str]:
    """Return (title, readable text) with script/style noise removed."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    text = " ".join(soup.get_text(separator=" ").split())
    return title, text


def content_type_main(headers: dict[str, str] | object) -> str:
    """Primary media type from response headers, lowercased."""
    raw = ""
    if hasattr(headers, "get"):
        raw = headers.get("content-type") or headers.get("Content-Type") or ""
    primary = str(raw).split(";", 1)[0].strip().lower()
    return primary


def looks_like_html(body: str, content_type: str) -> bool:
    if content_type in {"text/html", "application/xhtml+xml"}:
        return True
    sample = body.lstrip()[:2000].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<body" in sample


def looks_like_css(body: str, content_type: str) -> bool:
    if content_type == "text/css":
        return True
    if looks_like_html(body, content_type):
        return False
    sample = body.lstrip()[:8000]
    lowered = sample.lower()
    if "@font-face" in lowered or lowered.startswith("@import"):
        return True
    # Stylesheet without HTML scaffolding: many braces, almost no tags.
    if sample.count("{") >= 3 and sample.count("<") < 2:
        return True
    return False


def thin_readable(text: str) -> bool:
    return len(text.strip()) < _MIN_READABLE_CHARS
