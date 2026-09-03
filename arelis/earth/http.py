"""Pinned, fail-soft HTTP for Earth catalog fetchers.

A timeout, a 500, or an unpinned redirect is None — never a raise into
Live. Retry is off by default so a dying host is not hit twice. Pass
``retries=1`` only where a second try was already the local contract.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import httpx


def host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


def get_json(
    url: str,
    pin: str,
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    retries: int = 0,
    backoff_s: float = 0.2,
) -> Any | None:
    """GET JSON. None on pin miss, timeout, HTTP error, or bad body."""
    return _get(
        url,
        pin,
        timeout=timeout,
        headers=headers,
        params=params,
        retries=retries,
        backoff_s=backoff_s,
        as_text=False,
    )


def get_text(
    url: str,
    pin: str,
    *,
    timeout: float = 10.0,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    retries: int = 0,
    backoff_s: float = 0.2,
) -> str | None:
    """GET text. None on pin miss, timeout, or HTTP error."""
    got = _get(
        url,
        pin,
        timeout=timeout,
        headers=headers,
        params=params,
        retries=retries,
        backoff_s=backoff_s,
        as_text=True,
    )
    return got if isinstance(got, str) else None


def _get(
    url: str,
    pin: str,
    *,
    timeout: float,
    headers: dict[str, str] | None,
    params: dict[str, str] | None,
    retries: int,
    backoff_s: float,
    as_text: bool,
) -> Any | None:
    if not host_pinned(urlparse(url).hostname, pin):
        return None
    attempts = max(int(retries), 0) + 1
    for i in range(attempts):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                if not host_pinned(urlparse(str(resp.url)).hostname, pin):
                    return None
                return resp.text if as_text else resp.json()
        except Exception:
            if i + 1 >= attempts:
                return None
            if backoff_s > 0:
                time.sleep(backoff_s)
    return None
