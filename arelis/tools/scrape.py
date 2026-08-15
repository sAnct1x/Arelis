"""Fetch a page and extract the article — not the whole chrome of the site."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.core.evidence import classify_fetch_failure
from arelis.tools.article import (
    ArticleExtract,
    extract_article,
    format_article,
    scrape_headers,
    sibling_urls,
)
from arelis.tools.base import ToolResult
from arelis.tools.fetch import BlockedUrlError, guarded_get, reject_non_http_url
from arelis.tools.html_text import content_type_main
from arelis.tools.safety import redact_secrets


def _fail_output(message: str) -> str:
    """Prefix scrape failures with a stable taxonomy tag for the ledger."""
    tag = classify_fetch_failure(message)
    if message.startswith("["):
        return message
    return f"[{tag}] {message}"


class ScrapeTool:
    name = "scrape"
    description = (
        "Open an http(s) URL and extract the main article text (not the nav, "
        "ads, or cookie banner). Uses JSON-LD, microdata, <article>/<main>, "
        "paragraph lattice, density scoring, and noscript rescue; retries "
        "AMP/print twins when the main page is a JS shell. Pass a real URL "
        "from web_search (the URL: line), never a title. Do not use this for "
        "weather — call the weather tool instead. For raw JSON/APIs use web_fetch."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) page URL"},
            "max_chars": {
                "type": "integer",
                "description": "Max characters of extracted article text",
            },
        },
        "required": ["url"],
    }

    def __init__(
        self,
        user_agent: str,
        timeout_s: float = 30,
        max_chars: int = 120000,
        *,
        block_private_urls: bool = True,
        follow_siblings: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.max_chars = max_chars
        self.block_private_urls = block_private_urls
        self.follow_siblings = follow_siblings

    async def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        if not url:
            return ToolResult(ok=False, output=_fail_output("Missing url"))
        bad = reject_non_http_url(str(url))
        if bad:
            return ToolResult(ok=False, output=_fail_output(bad))
        max_chars = int(kwargs.get("max_chars", self.max_chars))
        page_url = str(url).strip()

        extract = ArticleExtract()
        final = page_url
        tried: list[str] = []
        download_error: str | None = None

        try:
            html, final, ctype = await self._download(page_url)
            tried.append(final)
            non_html = self._reject_non_html(ctype, html, final)
            if non_html is not None:
                return non_html
            # Bare text/plain responses — no DOM to peel; treat as the article.
            main = content_type_main({"content-type": ctype})
            if main.startswith("text/plain") and "<html" not in html[:200].lower():
                body = redact_secrets(html.strip())
                if len(body) < 40:
                    return ToolResult(
                        ok=False,
                        output=_fail_output(
                            "Plain-text response was too short to use as an article."
                        ),
                        data={"url": final, "content_type": main},
                    )
                extract = ArticleExtract(
                    title=final.rsplit("/", 1)[-1] or final,
                    text=body,
                    strategy="plain-text",
                    score=80.0,
                    word_count=len(body.split()),
                )
            else:
                extract = await asyncio.to_thread(
                    extract_article, html, base_url=final
                )
        except BlockedUrlError as exc:
            return ToolResult(ok=False, output=_fail_output(str(exc)))
        except Exception as exc:
            download_error = str(exc)
            # Still try AMP/print path guesses — primary host may 403 HTML but
            # serve /amp fine.
            extract = ArticleExtract(
                diagnosis=f"Primary fetch failed: {download_error}",
            )

        if self.follow_siblings and not extract.ok:
            # Seed sibling list even when HTML never arrived (path heuristics).
            alts = sibling_urls(extract, page_url=final or page_url)
            for alt in alts:
                if alt in tried:
                    continue
                tried.append(alt)
                try:
                    alt_html, alt_final, alt_ctype = await self._download(alt)
                except Exception:
                    continue
                if content_type_main({"content-type": alt_ctype}) not in {
                    "",
                    "text/html",
                    "application/xhtml+xml",
                } and "<html" not in alt_html[:500].lower():
                    continue
                alt_extract = await asyncio.to_thread(
                    extract_article, alt_html, base_url=alt_final
                )
                if alt_extract.score > extract.score:
                    extract = alt_extract
                    final = alt_final
                if extract.ok:
                    break

        if not extract.ok:
            hint = extract.diagnosis or "Could not extract a readable article."
            extras: list[str] = [hint]
            if download_error and hint and download_error not in hint:
                extras.insert(0, f"Fetch note: {download_error}")
            if extract.amp_url:
                extras.append(f"AMP candidate: {extract.amp_url}")
            if extract.print_url:
                extras.append(f"Print candidate: {extract.print_url}")
            if extract.canonical_url and extract.canonical_url.rstrip("/") != (
                final or page_url
            ).rstrip("/"):
                extras.append(f"Canonical: {extract.canonical_url}")
            if len(tried) > 1:
                extras.append("Tried: " + ", ".join(tried))
            extras.append(
                "Tip: pick another search hit that ships real HTML, or use "
                "web_fetch if you need raw JSON/API bytes."
            )
            body = "\n".join(extras)
            return ToolResult(
                ok=False,
                output=_fail_output(body),
                data={
                    "url": final,
                    "title": extract.title,
                    "strategy": extract.strategy,
                    "diagnosis": extract.diagnosis,
                    "tried": tried,
                    "fail_class": classify_fetch_failure(body),
                },
            )

        extract.text = redact_secrets(extract.text)
        extract.title = redact_secrets(extract.title)
        output = format_article(extract, max_chars=max_chars)
        return ToolResult(
            ok=True,
            output=output,
            data={
                "url": final,
                "title": extract.title,
                "strategy": extract.strategy,
                "byline": extract.byline,
                "published": extract.published,
                "site": extract.site,
                "score": extract.score,
                "word_count": extract.word_count or len(extract.text.split()),
                "canonical_url": extract.canonical_url,
                "tried": tried,
            },
        )

    def _reject_non_html(
        self, ctype: str, body: str, url: str
    ) -> ToolResult | None:
        main = content_type_main({"content-type": ctype})
        sample = body.lstrip()[:300].lower()
        looks_html = (
            main in {"text/html", "application/xhtml+xml"}
            or sample.startswith("<!doctype html")
            or sample.startswith("<html")
            or "<body" in sample
        )
        if looks_html:
            return None
        if main in {"application/json", "text/json"} or sample.startswith(("{", "[")):
            return ToolResult(
                ok=False,
                output=_fail_output(
                    f"{url} looks like JSON, not an article page. "
                    "Use web_fetch for APIs and JSON endpoints."
                ),
                data={"url": url, "content_type": main or "json", "fail_class": "fail:non_html"},
            )
        if main.startswith("text/plain") and "<" not in sample:
            # Plain text can still be useful — wrap as a trivial extract.
            return None
        if main and not main.startswith("text/") and "html" not in main:
            return ToolResult(
                ok=False,
                output=_fail_output(
                    f"{url} returned {main or 'non-HTML'} — scrape needs an "
                    "HTML article. Use web_fetch for binary/API responses."
                ),
                data={"url": url, "content_type": main, "fail_class": "fail:non_html"},
            )
        return None

    async def _download(self, url: str) -> tuple[str, str, str]:
        headers = scrape_headers(self.user_agent)
        # Referer from same host softens a few hotlink / bot gates.
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await guarded_get(
                client,
                url,
                headers=headers,
                block_private=self.block_private_urls,
            )
            response.raise_for_status()
            ctype = response.headers.get("content-type", "")
            return response.text, str(response.url), ctype
