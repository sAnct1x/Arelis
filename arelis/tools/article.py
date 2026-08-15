"""Article extraction that beats naive get_text().

A personal research assistant does not need a headless Chrome farm. It needs
to pull the *story* out of a messy HTML document: kill the nav, keep the
paragraphs, notice paywalls, and when the main URL is a JS shell, try the AMP
or print twin before giving up.

Strategies (best score wins; near-ties can merge unique paragraphs):

1. JSON-LD NewsArticle / Article / BlogPosting (HTML bodies unwrapped)
2. Microdata ``itemprop=articleBody``
3. ``<article>`` / ``<main>`` / common CMS content classes
4. Paragraph lattice (longest run of consecutive prose ``<p>`` blocks)
5. Density scoring over block nodes (readability-style)
6. ``<noscript>`` rescue when the live DOM is a JS shell
7. Open Graph description as a short fallback
8. Cleaned full-body text (worst, but better than nothing)

No new dependencies — BeautifulSoup + lxml already in the project.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, NavigableString, Tag

from arelis.tools.html_text import thin_readable

# Chrome-ish enough that a few CDNs stop serving the "please enable JS" stub.
BROWSER_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,*/*;q=0.8"
)
BROWSER_ACCEPT_LANGUAGE = "en-US,en;q=0.9"

_NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "iframe",
    "form",
    "nav",
    "footer",
    "header",
    "aside",
    "button",
)
_NOISE_ATTR = re.compile(
    r"(nav|menu|sidebar|footer|header|cookie|consent|banner|promo|share|"
    r"social|comment|related|recommend|advert|sponsor|modal|popup|subscribe|"
    r"newsletter|breadcrumb|toolbar|byline-tools)",
    re.I,
)
_PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscription required",
    "create a free account",
    "sign in to read",
    "sign in to continue",
    "already a subscriber",
    "metered paywall",
    "for subscribers only",
    "this article is for subscribers",
    "register to continue",
    "become a member to read",
    "members only",
)
_CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "checking your browser",
    "cf-browser-verification",
    "enable javascript and cookies",
    "please enable cookies",
    "captcha",
    "verify you are human",
)
_BOILERPLATE_LINE = re.compile(
    r"^(share this|share on|follow us|sign up for|subscribe to our|"
    r"advertisement|skip to (content|main)|cookie (policy|settings)|"
    r"we use cookies|accept (all )?cookies|newsletter|"
    r"read more:?|related (stories|articles)|most (read|popular)|"
    r"log ?in|sign ?in|create (an )?account)\b",
    re.I,
)
_AMP_HINT = re.compile(r"(/amp/?$|/amp/|[?&](amp|outputtype=amp)=)", re.I)
_PRINT_HINT = re.compile(r"(print|printable|printview)", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
# Pull ld+json from the raw markup — a soup parse will eat <p> inside the JSON.
_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


@dataclass
class ArticleExtract:
    title: str = ""
    text: str = ""
    byline: str = ""
    published: str = ""
    site: str = ""
    description: str = ""
    strategy: str = ""
    score: float = 0.0
    diagnosis: str = ""  # set when extraction is weak
    amp_url: str = ""
    print_url: str = ""
    canonical_url: str = ""
    outbound: list[tuple[str, str]] = field(default_factory=list)  # (text, url)
    word_count: int = 0

    @property
    def ok(self) -> bool:
        return not thin_readable(self.text) and self.score >= 40.0


def scrape_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": BROWSER_ACCEPT,
        "Accept-Language": BROWSER_ACCEPT_LANGUAGE,
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }


def extract_article(html: str, *, base_url: str = "") -> ArticleExtract:
    """Run every strategy and return the best article-shaped extract."""
    raw = html or ""
    soup = BeautifulSoup(raw, "lxml")
    meta = _meta_bundle(soup, base_url=base_url)
    candidates: list[ArticleExtract] = []

    json_ld = _from_json_ld(raw, meta)
    if json_ld is not None:
        candidates.append(json_ld)
    micro = _from_microdata(soup, meta, base_url=base_url)
    if micro is not None:
        candidates.append(micro)

    for node, label in _semantic_roots(soup):
        text = _node_text(node)
        if not text:
            continue
        candidates.append(
            _pack(
                meta,
                title=meta.title or _nearest_heading(node) or "",
                text=text,
                strategy=label,
                score=_score(text, label),
                outbound=_outbound_links(node, base_url, limit=8),
            )
        )

    lattice = _from_paragraph_lattice(soup, meta, base_url=base_url)
    if lattice is not None:
        candidates.append(lattice)

    density = _from_density(soup, meta, base_url=base_url)
    if density is not None:
        candidates.append(density)

    noscript = _from_noscript(soup, meta, base_url=base_url)
    if noscript is not None:
        candidates.append(noscript)

    if meta.description and len(meta.description) >= 80:
        candidates.append(
            _pack(
                meta,
                title=meta.title,
                text=meta.description,
                strategy="og-description",
                score=_score(meta.description, "og-description") * 0.55,
            )
        )

    # Last resort: cleaned body (noisy, but sometimes the only prose).
    body = soup.body or soup
    cleaned = _strip_noise(body)
    fallback_text = _node_text(cleaned)
    if fallback_text:
        candidates.append(
            _pack(
                meta,
                title=meta.title,
                text=fallback_text,
                strategy="full-body",
                score=_score(fallback_text, "full-body") * 0.35,
                outbound=_outbound_links(cleaned, base_url, limit=8),
            )
        )

    if not candidates:
        empty = ArticleExtract(
            title=meta.title,
            site=meta.site,
            amp_url=meta.amp_url,
            print_url=meta.print_url,
            canonical_url=meta.canonical_url,
            diagnosis=_diagnose(html, ""),
        )
        return empty

    # Soft-merge near-ties: a density hit often has paragraphs JSON-LD dropped.
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    best = ranked[0]
    if len(ranked) > 1 and ranked[1].score >= best.score * 0.82:
        merged = _merge_unique_paragraphs(best, ranked[1])
        if merged.score >= best.score:
            best = merged

    best.text = _scrub_boilerplate(best.text)
    best.word_count = len(best.text.split())
    if not best.title:
        best.title = meta.title
    if not best.byline:
        best.byline = meta.byline
    if not best.published:
        best.published = meta.published
    if not best.site:
        best.site = meta.site
    if not best.amp_url:
        best.amp_url = meta.amp_url
    if not best.print_url:
        best.print_url = meta.print_url
    if not best.canonical_url:
        best.canonical_url = meta.canonical_url
    # Re-score after scrub — paywall CTAs shouldn't inflate length.
    best.score = _score(best.text, best.strategy.split("+")[0])
    if not best.ok:
        best.diagnosis = _diagnose(html, best.text)
    return best


def format_article(extract: ArticleExtract, *, max_chars: int) -> str:
    """Model-facing document: metadata header + body + extraction footer."""
    lines: list[str] = []
    if extract.title:
        lines.append(f"# {extract.title}")
        lines.append("")
    meta_bits: list[str] = []
    if extract.site:
        meta_bits.append(f"Site: {extract.site}")
    if extract.byline:
        meta_bits.append(f"By: {extract.byline}")
    if extract.published:
        meta_bits.append(f"Published: {extract.published}")
    words = extract.word_count or len(extract.text.split())
    if words:
        minutes = max(1, round(words / 220))
        meta_bits.append(f"Length: ~{words} words ({minutes} min read)")
    if meta_bits:
        lines.extend(meta_bits)
        lines.append("")
    body = extract.text.strip()
    truncated, was_cut = _truncate_at_sentence(body, max_chars)
    lines.append(truncated)
    if was_cut:
        lines.append("")
        lines.append(f"[truncated to {max_chars} chars]")
    lines.append("")
    lines.append(f"[extracted via {extract.strategy or 'unknown'}]")
    if extract.outbound:
        lines.append("On-page links:")
        for label, href in extract.outbound[:6]:
            tip = label[:80] if label else href
            lines.append(f"- {tip} -> {href}")
    return "\n".join(lines).strip() + "\n"


def sibling_urls(extract: ArticleExtract, *, page_url: str) -> list[str]:
    """Alternate URLs worth a second fetch when the primary extract is thin."""
    out: list[str] = []

    def _add(candidate: str) -> None:
        if not candidate:
            return
        absolute = urljoin(page_url, candidate)
        if absolute.rstrip("/") == page_url.rstrip("/"):
            return
        if absolute not in out:
            out.append(absolute)

    for candidate in (extract.amp_url, extract.print_url):
        _add(candidate)

    parsed = urlparse(page_url)
    if parsed.scheme in {"http", "https"} and parsed.path:
        path = parsed.path.rstrip("/")
        if not _AMP_HINT.search(page_url):
            _add(urlunparse(parsed._replace(path=f"{path}/amp")))
            _add(urlunparse(parsed._replace(path=f"{path}.amp")))
            _add(urlunparse(parsed._replace(path=f"{path}/amp.html")))
            # Query-flag AMP used by some publishers.
            q = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if "amp" not in q and "outputType" not in q:
                q["amp"] = "1"
                _add(urlunparse(parsed._replace(query=urlencode(q))))
    return out[:5]


# --- internals -------------------------------------------------------------


@dataclass
class _Meta:
    title: str = ""
    description: str = ""
    byline: str = ""
    published: str = ""
    site: str = ""
    amp_url: str = ""
    print_url: str = ""
    canonical_url: str = ""


def _pack(
    meta: _Meta,
    *,
    title: str,
    text: str,
    strategy: str,
    score: float,
    outbound: list[tuple[str, str]] | None = None,
    byline: str | None = None,
    published: str | None = None,
) -> ArticleExtract:
    return ArticleExtract(
        title=title,
        text=_scrub_boilerplate(_normalize_ws(text)),
        byline=byline if byline is not None else meta.byline,
        published=published if published is not None else meta.published,
        site=meta.site,
        description=meta.description,
        strategy=strategy,
        score=score,
        amp_url=meta.amp_url,
        print_url=meta.print_url,
        canonical_url=meta.canonical_url,
        outbound=outbound or [],
        word_count=len(text.split()),
    )


def _meta_content(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def _meta_bundle(soup: BeautifulSoup, *, base_url: str) -> _Meta:
    title = _meta_content(soup, "og:title", "twitter:title")
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    description = _meta_content(
        soup, "og:description", "twitter:description", "description"
    )
    byline = _meta_content(soup, "author", "article:author", "og:article:author")
    published = _meta_content(
        soup,
        "article:published_time",
        "og:article:published_time",
        "pubdate",
        "publishdate",
        "date",
    )
    site = _meta_content(soup, "og:site_name", "application-name")
    amp = ""
    amp_link = soup.find("link", rel=lambda v: v and "amphtml" in str(v).lower())
    if amp_link and amp_link.get("href"):
        amp = urljoin(base_url, str(amp_link["href"]).strip())
    print_url = ""
    for link in soup.find_all("a", href=True):
        href = str(link.get("href") or "")
        label = link.get_text(" ", strip=True)
        if _PRINT_HINT.search(href) or _PRINT_HINT.search(label):
            print_url = urljoin(base_url, href)
            break
    canonical = ""
    canon = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    if canon and canon.get("href"):
        canonical = urljoin(base_url, str(canon["href"]).strip())
    return _Meta(
        title=title,
        description=description,
        byline=byline,
        published=published,
        site=site,
        amp_url=amp,
        print_url=print_url,
        canonical_url=canonical,
    )


def _unwrap_html_fragment(raw: str) -> str:
    """JSON-LD articleBody is often HTML; peel tags without inventing prose."""
    text = html_lib.unescape(raw or "").strip()
    if "<" not in text:
        return _normalize_ws(text)
    frag = BeautifulSoup(text, "lxml")
    for tag in frag(["script", "style"]):
        tag.decompose()
    plain = frag.get_text("\n", strip=True)
    if len(plain) < 40:
        plain = _TAG_RE.sub(" ", text)
    return _normalize_ws(plain)


def _from_json_ld(html: str, meta: _Meta) -> ArticleExtract | None:
    blobs: list[dict[str, Any]] = []
    for match in _LD_JSON_RE.finditer(html or ""):
        raw = html_lib.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Trailing commas / multi-object dumps — salvage first object.
            try:
                data = json.loads(raw.rstrip().rstrip(","))
            except json.JSONDecodeError:
                continue
        if isinstance(data, list):
            blobs.extend(x for x in data if isinstance(x, dict))
        elif isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                blobs.extend(x for x in data["@graph"] if isinstance(x, dict))
            else:
                blobs.append(data)

    best: ArticleExtract | None = None
    for item in blobs:
        types = item.get("@type") or ""
        if isinstance(types, list):
            type_l = " ".join(str(t).lower() for t in types)
        else:
            type_l = str(types).lower()
        if not any(
            key in type_l
            for key in ("article", "newsarticle", "blogposting", "report", "techarticle")
        ):
            continue
        body = _unwrap_html_fragment(
            str(item.get("articleBody") or item.get("text") or item.get("description") or "")
        )
        # Structured data is already curated — accept shorter bodies than DOM peels.
        if len(body) < 60:
            continue
        title = str(item.get("headline") or item.get("name") or meta.title or "").strip()
        author = item.get("author")
        byline = meta.byline
        if isinstance(author, dict):
            byline = str(author.get("name") or byline)
        elif isinstance(author, list) and author:
            names = [
                str(a.get("name") if isinstance(a, dict) else a).strip()
                for a in author
            ]
            byline = ", ".join(n for n in names if n) or byline
        elif isinstance(author, str):
            byline = author
        published = str(
            item.get("datePublished") or item.get("dateCreated") or meta.published or ""
        )
        cand = _pack(
            meta,
            title=title,
            text=body,
            strategy="json-ld",
            score=_score(body, "json-ld") + 25.0,
            byline=byline,
            published=published,
        )
        if best is None or cand.score > best.score:
            best = cand
    return best


def _from_microdata(
    soup: BeautifulSoup, meta: _Meta, *, base_url: str
) -> ArticleExtract | None:
    nodes = soup.find_all(attrs={"itemprop": re.compile(r"articleBody|text", re.I)})
    best: ArticleExtract | None = None
    for node in nodes:
        if not isinstance(node, Tag):
            continue
        text = _node_text(node)
        if len(text) < 80:
            continue
        cand = _pack(
            meta,
            title=meta.title or _nearest_heading(node) or "",
            text=text,
            strategy="microdata",
            score=_score(text, "microdata") + 20.0,
            outbound=_outbound_links(node, base_url, limit=8),
        )
        if best is None or cand.score > best.score:
            best = cand
    return best


def _semantic_roots(soup: BeautifulSoup) -> list[tuple[Tag, str]]:
    roots: list[tuple[Tag, str]] = []
    for selector, label in (
        ("article", "article-tag"),
        ("main", "main-tag"),
        ("[role=main]", "role-main"),
        ("#content", "id-content"),
        ("#mw-content-text", "mediawiki"),
        (".post-content", "post-content"),
        (".article-body", "article-body"),
        (".entry-content", "entry-content"),
        (".story-body", "story-body"),
        (".RichTextArticleBody", "rich-text-body"),
        ("[data-testid='article-body']", "testid-body"),
        (".article__body", "article-body-bem"),
    ):
        for node in soup.select(selector):
            if isinstance(node, Tag):
                roots.append((node, label))
    return roots


def _from_paragraph_lattice(
    soup: BeautifulSoup, meta: _Meta, *, base_url: str
) -> ArticleExtract | None:
    """Longest run of consecutive prose paragraphs under one parent.

    Many blogs never wrap content in ``<article>``; they just stack ``<p>``
    tags. Density scoring often picks a comments widget instead. Walking
    sibling paragraphs finds the actual essay.
    """
    body = soup.body
    if body is None:
        return None
    best_text = ""
    best_parent: Tag | None = None
    for parent in body.find_all(["div", "section", "article", "main", "td"]):
        if not isinstance(parent, Tag) or _looks_noisy(parent):
            continue
        # Direct-ish children paragraphs (and p wrapped in one level).
        paras: list[str] = []
        for child in parent.children:
            if not isinstance(child, Tag):
                continue
            target = child if child.name == "p" else None
            if target is None and child.name in {"div", "section"}:
                only_p = [c for c in child.children if isinstance(c, Tag)]
                if len(only_p) == 1 and only_p[0].name == "p":
                    target = only_p[0]
            if target is None or target.name != "p":
                if paras and len(" ".join(paras)) >= 200:
                    break  # lattice broken
                paras = []
                continue
            chunk = target.get_text(" ", strip=True)
            if len(chunk) < 40:
                continue
            if _BOILERPLATE_LINE.search(chunk):
                continue
            paras.append(chunk)
        text = _normalize_ws("\n\n".join(paras))
        if len(text) > len(best_text):
            best_text = text
            best_parent = parent
    if len(best_text) < 200:
        return None
    return _pack(
        meta,
        title=meta.title or (best_parent and _nearest_heading(best_parent)) or "",
        text=best_text,
        strategy="paragraph-lattice",
        score=_score(best_text, "paragraph-lattice") + 15.0,
        outbound=_outbound_links(best_parent, base_url, limit=8) if best_parent else [],
    )


def _from_density(
    soup: BeautifulSoup, meta: _Meta, *, base_url: str
) -> ArticleExtract | None:
    body = soup.body
    if body is None:
        return None
    best_node: Tag | None = None
    best_score = 0.0
    for node in body.find_all(["div", "section", "article", "main", "td"]):
        if not isinstance(node, Tag):
            continue
        if _looks_noisy(node):
            continue
        text = _node_text(node)
        if len(text) < 200:
            continue
        paras = text.count(". ") + text.count("? ") + text.count("! ")
        link_text = sum(len(a.get_text(" ", strip=True)) for a in node.find_all("a"))
        density = (len(text) - link_text * 0.8) / max(1, len(list(node.descendants)))
        score = len(text) * 0.02 + paras * 8.0 + density * 40.0
        if score > best_score:
            best_score = score
            best_node = node
    if best_node is None:
        return None
    text = _node_text(best_node)
    return _pack(
        meta,
        title=meta.title or _nearest_heading(best_node) or "",
        text=text,
        strategy="density",
        score=_score(text, "density"),
        outbound=_outbound_links(best_node, base_url, limit=8),
    )


def _from_noscript(
    soup: BeautifulSoup, meta: _Meta, *, base_url: str
) -> ArticleExtract | None:
    """Some publishers dump the real article into ``<noscript>`` for crawlers."""
    chunks: list[str] = []
    for tag in soup.find_all("noscript"):
        raw = tag.decode_contents() if hasattr(tag, "decode_contents") else str(tag)
        if "<" in raw:
            inner = BeautifulSoup(raw, "lxml")
            text = _node_text(inner)
        else:
            text = _normalize_ws(tag.get_text(" ", strip=True))
        if len(text) >= 120:
            chunks.append(text)
    if not chunks:
        return None
    text = max(chunks, key=len)
    return _pack(
        meta,
        title=meta.title,
        text=text,
        strategy="noscript",
        score=_score(text, "noscript") + 10.0,
    )


def _looks_noisy(node: Tag) -> bool:
    if not isinstance(node, Tag):
        return False
    attrs = getattr(node, "attrs", None) or {}
    classes = attrs.get("class") or []
    if isinstance(classes, str):
        classes = [classes]
    identity = " ".join(
        filter(
            None,
            [
                " ".join(str(c) for c in classes),
                str(attrs.get("id") or ""),
                str(attrs.get("role") or ""),
            ],
        )
    )
    return bool(_NOISE_ATTR.search(identity))


def _strip_noise(node: Tag) -> Tag:
    clone = BeautifulSoup(str(node), "lxml")
    root = clone.body or clone
    for tag in list(root.find_all(_NOISE_TAGS)):
        if isinstance(tag, Tag):
            tag.decompose()
    # Snapshot first — decomposing while iterating can leave half-dead tags.
    noisy = [
        tag
        for tag in root.find_all(True)
        if isinstance(tag, Tag) and _looks_noisy(tag)
    ]
    for tag in noisy:
        tag.decompose()
    return root  # type: ignore[return-value]


def _node_text(node: Tag | BeautifulSoup) -> str:
    cleaned = _strip_noise(node) if isinstance(node, Tag) else node
    parts: list[str] = []
    for child in cleaned.descendants:
        if isinstance(child, NavigableString):
            parent = child.parent
            if parent and parent.name in _NOISE_TAGS:
                continue
            chunk = str(child).strip()
            if chunk:
                parts.append(chunk)
        elif isinstance(child, Tag) and child.name in {"p", "br", "li", "h1", "h2", "h3"}:
            parts.append("\n")
    text = _normalize_ws(" ".join(parts))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _scrub_boilerplate(text.strip())


def _normalize_ws(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _scrub_boilerplate(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if _BOILERPLATE_LINE.search(stripped) and len(stripped) < 120:
            continue
        kept.append(stripped)
    # Collapse accidental blank runs.
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return out


def _nearest_heading(node: Tag) -> str:
    for tag in node.find_all(["h1", "h2"], limit=3):
        text = tag.get_text(" ", strip=True)
        if text:
            return text
    prev = node.find_previous(["h1", "h2"])
    if prev:
        return prev.get_text(" ", strip=True)
    return ""


def _outbound_links(
    node: Tag | BeautifulSoup | None, base_url: str, *, limit: int
) -> list[tuple[str, str]]:
    if node is None:
        return []
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    for link in node.find_all("a", href=True):
        href = str(link.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = parsed.netloc.lower().removeprefix("www.")
        label = link.get_text(" ", strip=True)
        if len(label) < 4 and host == base_host:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        out.append((label, absolute))
        if len(out) >= limit:
            break
    return out


def _merge_unique_paragraphs(primary: ArticleExtract, secondary: ArticleExtract) -> ArticleExtract:
    """Keep primary prose; append secondary paragraphs that add new sentences."""
    secondary_paras = [p.strip() for p in re.split(r"\n\s*\n", secondary.text) if p.strip()]
    if not secondary_paras:
        return primary
    primary_blob = primary.text.lower()
    extras: list[str] = []
    for para in secondary_paras:
        if len(para) < 80:
            continue
        # Fingerprint: first 60 chars of normalized para.
        tip = re.sub(r"\s+", " ", para.lower())[:60]
        if tip and tip in primary_blob:
            continue
        extras.append(para)
        if len(extras) >= 4:
            break
    if not extras:
        return primary
    merged_text = primary.text.rstrip() + "\n\n" + "\n\n".join(extras)
    strategy = f"{primary.strategy}+{secondary.strategy}"
    return ArticleExtract(
        title=primary.title or secondary.title,
        text=merged_text,
        byline=primary.byline or secondary.byline,
        published=primary.published or secondary.published,
        site=primary.site or secondary.site,
        description=primary.description or secondary.description,
        strategy=strategy,
        score=_score(merged_text, primary.strategy.split("+")[0]) + 8.0,
        amp_url=primary.amp_url or secondary.amp_url,
        print_url=primary.print_url or secondary.print_url,
        canonical_url=primary.canonical_url or secondary.canonical_url,
        outbound=(primary.outbound or secondary.outbound)[:8],
        word_count=len(merged_text.split()),
    )


def _truncate_at_sentence(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    window = text[:max_chars]
    # Prefer cutting after a sentence end in the last 20% of the window.
    floor = int(max_chars * 0.8)
    best = -1
    for match in re.finditer(r"[.!?][\"')\]]?\s", window):
        if match.end() >= floor:
            best = match.end()
    if best > floor:
        return window[:best].rstrip(), True
    # Fall back to last whitespace so we don't bisect a word.
    space = window.rfind(" ")
    if space > floor:
        return window[:space].rstrip() + "…", True
    return window.rstrip() + "…", True


def _score(text: str, strategy: str) -> float:
    text = text.strip()
    if not text:
        return 0.0
    words = text.split()
    sentences = max(1, text.count(". ") + text.count("? ") + text.count("! "))
    score = len(text) * 0.05 + len(words) * 0.15 + sentences * 4.0
    if strategy == "json-ld":
        score += 40.0
    elif strategy == "microdata":
        score += 35.0
    elif strategy in {
        "article-tag",
        "main-tag",
        "role-main",
        "article-body",
        "story-body",
        "mediawiki",
        "rich-text-body",
        "testid-body",
        "article-body-bem",
    }:
        score += 30.0
    elif strategy == "paragraph-lattice":
        score += 28.0
    elif strategy == "density":
        score += 20.0
    elif strategy == "noscript":
        score += 18.0
    elif strategy == "full-body":
        score -= 15.0
    # Penalize nav-ish dumps heavy on pipes / short tokens.
    short = sum(1 for w in words if len(w) <= 2)
    if words and short / len(words) > 0.35:
        score *= 0.6
    return score


def _diagnose(html: str, text: str) -> str:
    blob = f"{html[:8000]}\n{text}".lower()
    if any(m in blob for m in _CHALLENGE_MARKERS):
        return (
            "Page looks like a bot-check or cookie wall. "
            "Try another source, or open the URL in a browser yourself."
        )
    if any(m in blob for m in _PAYWALL_MARKERS):
        return (
            "Page looks paywalled or subscriber-only. "
            "The visible teaser may be all that loaded. Try AMP if offered, "
            "or a different outlet covering the same story."
        )
    if thin_readable(text):
        return (
            "Almost no readable HTML text — likely a JavaScript app shell. "
            "Scrape cannot run site JS. Prefer a different URL, an AMP/print "
            "link if available, or summarize from a source that ships real HTML."
        )
    return (
        "Extraction was weak (nav noise or short body). "
        "Try a different URL for the same story."
    )
