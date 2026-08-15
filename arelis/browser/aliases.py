"""Resolve short site names to https URLs."""

from __future__ import annotations

from urllib.parse import urlparse

# Built-in shortcuts. Config aliases merge on top (override by key).
DEFAULT_ALIASES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "yt": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "calendar": "https://calendar.google.com",
    "maps": "https://www.google.com/maps",
    "gmaps": "https://www.google.com/maps",
    "opentable": "https://www.opentable.com",
    "resy": "https://resy.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
}


def resolve_target(
    target: str,
    *,
    aliases: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Return (url, error). Accepts https URL or alias key."""
    raw = (target or "").strip()
    if not raw:
        return None, "Need a URL or site alias (e.g. youtube, gmail)."
    merged = {**DEFAULT_ALIASES, **(aliases or {})}
    key = raw.lower().rstrip("/")
    if key in merged:
        return merged[key], None
    # Allow "youtube.com" style without scheme when it matches an alias host.
    if "://" not in raw:
        bare = key.removeprefix("www.")
        for alias_url in merged.values():
            host = urlparse(alias_url).netloc.lower().removeprefix("www.")
            if bare == host or bare == host.split(".")[0]:
                return alias_url, None
        if "." in raw and " " not in raw:
            return f"https://{raw}", None
        return None, (
            f"Unknown site {raw!r}. Use an https URL or an alias like "
            f"{', '.join(sorted(merged)[:8])}."
        )
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return None, f"Only http(s) URLs are allowed, not {parsed.scheme!r}."
    if not parsed.netloc:
        return None, f"That does not look like a URL: {raw!r}"
    return raw, None
