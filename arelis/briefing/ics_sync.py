"""Download a private ICS feed into the local calendar path (option S).

No Google OAuth. URL comes from ``calendar.ics_url`` in ``data/secrets.yaml``.
Writes the configured ``tools.briefing.calendar_path`` after Allow.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from arelis.briefing.calendar import resolve_calendar_path
from arelis.calendar.secrets import load_ics_url
from arelis.tools.fetch import BlockedUrlError, guarded_get, reject_non_http_url

log = logging.getLogger(__name__)

_MAX_BYTES = 2_000_000
_USER_AGENT = "Arelis/1.0 (+local; ics-sync)"


async def sync_ics_from_url(
    config: dict[str, Any] | None = None,
    *,
    secrets_path: Path | None = None,
    url: str | None = None,
    dest: Path | None = None,
    timeout_s: float = 30.0,
    block_private_urls: bool = True,
) -> dict[str, Any]:
    """Fetch ICS text and atomically replace the local calendar file.

    Returns a small status dict for tool/data. Never raises for missing
    secret — callers get ``missing_secret`` / ``ok=False`` instead.
    """
    feed = (url or load_ics_url(secrets_path) or "").strip()
    if not feed:
        return {
            "ok": False,
            "missing_secret": True,
            "error": (
                "ICS URL not configured. Set calendar.ics_url in "
                "data/secrets.yaml (see secrets.example.yaml)."
            ),
        }
    bad = reject_non_http_url(feed)
    if bad:
        return {"ok": False, "error": bad, "url": feed}
    path = dest or resolve_calendar_path(config)
    headers = {"User-Agent": _USER_AGENT, "Accept": "text/calendar, text/plain, */*"}
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await guarded_get(
                client,
                feed,
                headers=headers,
                block_private=block_private_urls,
            )
    except BlockedUrlError as exc:
        return {"ok": False, "error": str(exc), "url": feed}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"ICS download failed: {exc}", "url": feed}

    if response.status_code >= 400:
        return {
            "ok": False,
            "error": f"ICS download HTTP {response.status_code}",
            "url": feed,
            "status_code": response.status_code,
        }
    raw = response.content
    if len(raw) > _MAX_BYTES:
        return {
            "ok": False,
            "error": f"ICS feed larger than {_MAX_BYTES} bytes; refused.",
            "url": feed,
        }
    try:
        text = raw.decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text.upper():
        return {
            "ok": False,
            "error": "Downloaded body is not an ICS calendar (missing BEGIN:VCALENDAR).",
            "url": feed,
        }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
    except OSError as exc:
        log.info("ICS write failed (%s): %s", path, exc)
        return {"ok": False, "error": f"Could not write {path}: {exc}", "url": feed}
    return {
        "ok": True,
        "path": str(path),
        "bytes": len(raw),
        "url": feed,
    }
