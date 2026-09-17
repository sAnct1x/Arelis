from __future__ import annotations

import asyncio
from typing import Any

import httpx

from arelis.core.evidence import classify_fetch_failure
from arelis.tools.base import ToolResult
from arelis.tools.fetch import BlockedUrlError, guarded_get, reject_non_http_url
from arelis.tools.html_text import (
    content_type_main,
    extract_text,
    looks_like_css,
    looks_like_html,
    thin_readable,
)
from arelis.tools.safety import redact_secrets


def _fail_output(message: str) -> str:
    tag = classify_fetch_failure(message)
    return f"[{tag}] {message}"


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Fetch an http(s) URL and return response text (truncated). "
        "Use for APIs, JSON, and plain text. Prefer scrape for HTML pages. "
        "Pass a real URL (from web_search's URL: line), never a page title. "
        "For weather, prefer the weather tool over hand-built Open-Meteo URLs."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) URL to fetch"},
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (default 50000)",
            },
        },
        "required": ["url"],
    }

    def __init__(
        self,
        user_agent: str,
        timeout_s: float = 30,
        *,
        block_private_urls: bool = True,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.block_private_urls = block_private_urls

    async def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        if not url:
            return ToolResult(ok=False, output=_fail_output("Missing url"))
        bad = reject_non_http_url(str(url))
        if bad:
            return ToolResult(ok=False, output=_fail_output(bad))
        max_chars = int(kwargs.get("max_chars", 50000))
        headers = {"User-Agent": self.user_agent}
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await guarded_get(
                    client,
                    str(url).strip(),
                    headers=headers,
                    block_private=self.block_private_urls,
                )
                response.raise_for_status()
                body = response.text
                final = str(response.url)
                status = response.status_code
                ctype = content_type_main(response.headers)
        except BlockedUrlError as exc:
            return ToolResult(ok=False, output=_fail_output(str(exc)))
        except Exception as exc:
            return ToolResult(
                ok=False, output=_fail_output(f"web_fetch failed: {exc}")
            )

        meta = {"status": status, "url": final, "content_type": ctype}

        if looks_like_css(body, ctype):
            return ToolResult(
                ok=False,
                output=_fail_output(
                    "web_fetch received a CSS stylesheet, not page content. "
                    "Use scrape for HTML pages, or fetch a different URL."
                ),
                data={**meta, "fail_class": "fail:non_html"},
            )

        if looks_like_html(body, ctype):
            try:
                title, text = await asyncio.to_thread(extract_text, body)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    output=_fail_output(f"web_fetch failed to parse HTML: {exc}"),
                    data=meta,
                )
            if thin_readable(text):
                # Say what little was there rather than binning it. This
                # branch used to drop the extraction on the floor, so a page
                # that was simply *short* — a price, a status line, a
                # one-sentence answer — came back indistinguishable from an
                # empty JavaScript shell, and she either gave up or filled the
                # gap from her own head. Note the asymmetry it was creating:
                # a five-character text/plain body falls through to the bottom
                # of this method and is returned verbatim with ok=True.
                #
                # Still ok=False, because thin usually does mean a shell and
                # the model must not treat this as the whole page. Redacted
                # for the same reason the successful path is: short does not
                # mean harmless, and a token is shorter than a sentence.
                found = redact_secrets(" ".join(text.split()))
                body_msg = (
                    "web_fetch found little readable text in the HTML; "
                    "the page may require JavaScript. Prefer scrape, or try "
                    "a different URL."
                )
                if found:
                    body_msg += f' All that was readable: "{found}"'
                return ToolResult(
                    ok=False,
                    output=_fail_output(body_msg),
                    data={
                        **meta,
                        "title": title,
                        "text": found,
                        "fail_class": classify_fetch_failure(body_msg),
                    },
                )
            text = redact_secrets(text)
            truncated = text[:max_chars]
            header = f"# {title}\n\n" if title else ""
            note = "" if len(text) <= max_chars else f"\n\n[truncated to {max_chars} chars]"
            return ToolResult(
                ok=True,
                output=header + truncated + note,
                data={**meta, "title": title},
            )

        text = redact_secrets(body)
        truncated = text[:max_chars]
        note = "" if len(text) <= max_chars else f"\n\n[truncated to {max_chars} chars]"
        return ToolResult(
            ok=True,
            output=truncated + note,
            data=meta,
        )
