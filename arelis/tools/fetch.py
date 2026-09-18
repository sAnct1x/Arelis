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


# Headers the caller may not set. Two groups, for two different reasons.
#
# `Host` is the dangerous one: every guard in this file validates the host in
# the *URL*, and a `Host:` header that disagrees with it is how a request that
# passed the check arrives somewhere else entirely — the classic route into a
# vhost or a cloud metadata service.
#
# The rest are hop-by-hop or framing headers. httpx computes them from the
# request it is actually sending, and letting a model override `Content-Length`
# or `Transfer-Encoding` is request smuggling by another name.
_FORBIDDEN_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "upgrade",
        "te",
        "trailer",
        "expect",
        "proxy-authorization",
        "proxy-connection",
    }
)


class HeaderError(ValueError):
    """A header the caller may not set, or one that is not a header at all."""


def sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Validate caller-supplied headers, raising rather than dropping.

    Silently dropping a header would be worse than refusing it: the request
    would go out looking like it succeeded and fail somewhere far away, and a
    dropped `Authorization` reads as "the API rejected us" rather than "we
    never sent the key".

    CR and LF are rejected in both names and values. httpx blocks header
    injection itself, but this path takes its input from a language model, and
    that is not a place to rely on someone else's check.
    """
    clean: dict[str, str] = {}
    for raw_name, raw_value in (headers or {}).items():
        name = str(raw_name).strip()
        value = str(raw_value)
        if not name:
            raise HeaderError("a header with no name")
        if any(ch in name or ch in value for ch in "\r\n\x00"):
            raise HeaderError(f"illegal characters in header {name!r}")
        if name.lower() in _FORBIDDEN_HEADERS:
            raise HeaderError(
                f"{name} cannot be set here. It decides where the request goes "
                "or how it is framed, which is the one thing the URL check "
                "cannot survive."
            )
        clean[name] = value
    return clean


async def guarded_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: str | bytes | None = None,
    block_private: bool = True,
) -> httpx.Response:
    """`guarded_get` for the methods that change something on the far end.

    Redirects are not followed at all here, and that is the point. On a GET the
    loop below re-checks each hop and carries on; on a POST it cannot, because
    a 307 replays the method, the body *and* the headers against whatever host
    the Location names. An `Authorization:` header meant for one API would be
    handed to another, chosen by the server rather than by the user. There is
    no check that makes that acceptable, so the hop is reported instead and the
    model can fetch the new URL deliberately if it wants to.
    """
    verb = (method or "GET").strip().upper()
    if verb in {"GET", "HEAD"}:
        return await guarded_get(client, url, headers=headers, block_private=block_private)
    reason = await check_url_allowed(url, block_private=block_private)
    if reason:
        raise BlockedUrlError(reason)
    response = await client.request(
        verb, url, headers=headers, content=content, follow_redirects=False
    )
    if response.is_redirect:
        location = response.headers.get("location", "?")
        raise BlockedUrlError(
            f"{verb} {url} redirected to {location}. Redirects are not followed "
            f"for {verb}, because that would resend the body and any "
            "credentials to a host the server chose. Fetch the new URL directly "
            "if it is the one you meant."
        )
    return response


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
