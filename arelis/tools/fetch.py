from __future__ import annotations

import httpx

from arelis.tools.safety import check_url_allowed

# Bounded so a redirect loop cannot spin forever inside one tool call.
_MAX_REDIRECTS = 5


class BlockedUrlError(Exception):
    """Raised when a URL, or any redirect hop leading to it, violates policy."""


def reject_non_http_url(url: str) -> str | None:
    """Return an error string when ``url`` is not a usable http(s) address.

    Small models sometimes pass a page title (or "URL: Title") into scrape /
    web_fetch after web_search. Catch that before we try to DNS a sentence.
    """
    raw = (url or "").strip()
    if raw.lower().startswith("url:"):
        raw = raw[4:].strip()
    if raw.startswith(("http://", "https://")):
        return None
    return (
        f"Not an http(s) URL: {url!r}. Copy the URL: line from a web_search "
        "result exactly — Titles are not URLs. Do not ask the user for a URL "
        "you already returned."
    )


async def guarded_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    block_private: bool = True,
) -> httpx.Response:
    """GET a URL, validating every hop before it is requested.

    httpx's own follow_redirects is deliberately not used. It would connect to
    each hop first and only hand back the final response, which means a public
    URL redirecting to http://127.0.0.1:11434 has already hit the local Ollama
    server by the time anything gets inspected. Checking the body afterwards
    hides the result from the model but does not undo the request.

    Redirects are therefore followed by hand: check, request, read Location,
    check again. Raises BlockedUrlError instead of returning a reason string so
    a blocked hop can never be mistaken for a successful fetch.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        reason = await check_url_allowed(current, block_private=block_private)
        if reason:
            raise BlockedUrlError(reason)
        response = await client.get(current, headers=headers, follow_redirects=False)
        if not response.is_redirect or response.next_request is None:
            return response
        # Resolve relative Location headers against the URL just requested.
        current = str(response.next_request.url)
    raise BlockedUrlError(f"Too many redirects (>{_MAX_REDIRECTS}) starting at {url}")
