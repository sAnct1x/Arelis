"""Poll the tab for a URL / heading / visible text. No CSS, no networkidle."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

WAIT_CAP_S = 8.0
WAIT_POLL_S = 0.25
WAIT_SLEEP_DEFAULT_S = 1.0
WAIT_NEEDLE_DEFAULT_S = 8.0
NAV_LOGIN_POLL_S = 4.0
WATCH_POLL_S = 1.0


def clamp_wait_seconds(seconds: float, *, has_needle: bool) -> float:
    raw = float(seconds)
    if has_needle:
        if raw <= 0:
            raw = WAIT_NEEDLE_DEFAULT_S
    else:
        if raw <= 0:
            raw = WAIT_SLEEP_DEFAULT_S
    return max(0.2, min(raw, WAIT_CAP_S))


def has_wait_needle(*, url: str = "", text: str = "", heading: str = "") -> bool:
    return bool(
        str(url or "").strip()
        or str(text or "").strip()
        or str(heading or "").strip()
    )


def url_needle_hit(landed: str, needle: str) -> bool:
    """Substring / path match. `/home` hits `https://x.com/home`."""
    got = str(landed or "").strip()
    want = str(needle or "").strip()
    if not got or not want:
        return False
    got_l = got.casefold()
    want_l = want.casefold()
    if want_l in got_l or got_l in want_l:
        return True
    got_path = (urlparse(got).path or "/").rstrip("/") or "/"
    want_path = want_l
    if "://" in want_l:
        want_path = (urlparse(want).path or "/").rstrip("/") or "/"
    elif want_l.startswith("/"):
        want_path = want_l.rstrip("/") or "/"
    else:
        return False
    got_l = got_path.casefold()
    want_l = want_path.casefold()
    return got_l == want_l or want_l in got_l


def page_needles_hit(
    *,
    landed_url: str = "",
    title: str = "",
    heading: str = "",
    page_text: str = "",
    want_url: str = "",
    want_text: str = "",
    want_heading: str = "",
) -> bool:
    """True when every provided needle is visible. Sleep-only is not a hit."""
    if not has_wait_needle(url=want_url, text=want_text, heading=want_heading):
        return False
    if str(want_url or "").strip() and not url_needle_hit(landed_url, want_url):
        return False
    if str(want_heading or "").strip():
        blob = f"{heading} {title}".casefold()
        if str(want_heading).strip().casefold() not in blob:
            return False
    if str(want_text or "").strip():
        blob = f"{page_text} {title} {heading}".casefold()
        if str(want_text).strip().casefold() not in blob:
            return False
    return True


def wait_output(
    *,
    hit: bool,
    seconds: float,
    landed_url: str = "",
    want_url: str = "",
    want_text: str = "",
    want_heading: str = "",
) -> tuple[str, dict[str, Any]]:
    needles = []
    if str(want_url or "").strip():
        needles.append(f"url={want_url.strip()}")
    if str(want_heading or "").strip():
        needles.append(f"heading={want_heading.strip()}")
    if str(want_text or "").strip():
        needles.append(f"text={want_text.strip()}")
    data: dict[str, Any] = {
        "waited_s": round(float(seconds), 2),
        "hit": bool(hit),
        "url": landed_url,
    }
    if not needles:
        return f"Waited {seconds:.1f}s.", data
    wanted = ", ".join(needles)
    if hit:
        line = f"Wait hit ({wanted})"
        if landed_url:
            line += f" — {landed_url}"
        return line + ".", data
    line = f"Wait timeout ({wanted}, {seconds:.1f}s)"
    if landed_url:
        line += f" — still {landed_url}"
    return line + ".", data
