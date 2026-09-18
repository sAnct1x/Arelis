from __future__ import annotations

import asyncio
from typing import Any

import httpx

from arelis.core.evidence import classify_fetch_failure
from arelis.tools.base import ToolResult
from arelis.tools.fetch import (
    BlockedUrlError,
    HeaderError,
    guarded_request,
    reject_non_http_url,
    sanitize_headers,
)
from arelis.tools.html_text import (
    content_type_main,
    extract_text,
    looks_like_css,
    looks_like_html,
    thin_readable,
)
from arelis.tools.safety import redact_secrets

_METHODS: tuple[str, ...] = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")

# Bounded so a model cannot paste a megabyte of generated JSON into a request.
_MAX_BODY_CHARS = 100_000


def _fail_output(message: str) -> str:
    tag = classify_fetch_failure(message)
    return f"[{tag}] {message}"


def _as_headers(raw: Any) -> dict[str, str] | None:
    """Accept the dict the schema asks for, and the JSON string models send.

    Small models emit object parameters as a string often enough that refusing
    one is a wasted round. Anything else is an error rather than a silent drop,
    for the same reason sanitize_headers raises.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, str):
        import json

        try:
            parsed = json.loads(raw)
        except ValueError as exc:
            raise HeaderError(f"headers is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HeaderError("headers must be an object of name to value")
        return {str(k): str(v) for k, v in parsed.items()}
    raise HeaderError("headers must be an object of name to value")


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Call an http(s) URL and return the response text (truncated). "
        "Use for APIs, JSON, and plain text. Prefer scrape for HTML pages. "
        "Pass a real URL (from web_search's URL: line), never a page title. "
        "For weather, prefer the weather tool over hand-built Open-Meteo URLs. "
        "method=POST|PUT|PATCH|DELETE with headers= and body= for a real API; "
        "anything other than GET changes something and asks first."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP(S) URL to fetch"},
            "method": {
                "type": "string",
                "enum": list(_METHODS),
                "description": "HTTP method (default GET)",
            },
            "headers": {
                "type": "object",
                "description": (
                    "Request headers, e.g. "
                    '{"Authorization": "Bearer …", "Content-Type": "application/json"}'
                ),
                "additionalProperties": {"type": "string"},
            },
            "body": {
                "type": "string",
                "description": "Request body for POST/PUT/PATCH. Send JSON as a string.",
            },
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
        method = str(kwargs.get("method") or "GET").strip().upper()
        if method not in _METHODS:
            return ToolResult(
                ok=False,
                output=_fail_output(
                    f"Unknown method {method!r}. Use one of: {', '.join(_METHODS)}"
                ),
            )
        body = kwargs.get("body")
        content = None if body in (None, "") else str(body)
        if content is not None and len(content) > _MAX_BODY_CHARS:
            return ToolResult(
                ok=False,
                output=_fail_output(
                    f"Body is {len(content)} characters, over the "
                    f"{_MAX_BODY_CHARS} limit. Send a file reference, not the file."
                ),
            )
        if content is not None and method in {"GET", "HEAD"}:
            # Not a hard rule in HTTP, but a GET with a body is almost always a
            # model meaning POST, and servers quietly ignore it — which looks
            # like the API silently doing nothing.
            return ToolResult(
                ok=False,
                output=_fail_output(
                    "A body was given with GET. Set method=POST (or PUT/PATCH) "
                    "if you meant to send it."
                ),
            )
        headers = {"User-Agent": self.user_agent}
        try:
            headers.update(sanitize_headers(_as_headers(kwargs.get("headers"))) or {})
        except HeaderError as exc:
            return ToolResult(ok=False, output=_fail_output(str(exc)))
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await guarded_request(
                    client,
                    method,
                    str(url).strip(),
                    headers=headers,
                    content=content,
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
            return ToolResult(ok=False, output=_fail_output(f"web_fetch failed: {exc}"))

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
