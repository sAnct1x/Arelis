"""Your-turn walls: captcha, login, pay. Detect and freeze — never solve."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

YOUR_TURN = "YOUR_TURN"

_CAPTCHA_HOST = re.compile(
    r"(?i)(recaptcha|hcaptcha|challenges\.cloudflare|geetest)"
)
_LOGIN_HOST = re.compile(
    r"(?i)(accounts\.google\.com|login\.microsoftonline|login\.live\.com|"
    r"appleid\.apple\.com|auth0\.com|okta\.com)"
)
_LOGIN_PATH = re.compile(
    r"(?i)/("
    r"sign[-_]?in|log[-_]?in|oauth|authorize|"
    r"i/flow/(?:login|signup)|"
    r"i/jf/onboarding"
    r")(/|$|\?|#)"
)
_LOGIN_QUERY = re.compile(r"(?i)(?:^|&)mode=login(?:&|$)")
_LOGIN_FRAGMENT = re.compile(r"(?i)(sign[-_]?in|log[-_]?in|signup)")
_X_HOST = frozenset(
    {
        "x.com",
        "www.x.com",
        "mobile.x.com",
        "twitter.com",
        "www.twitter.com",
        "mobile.twitter.com",
    }
)
_PAY_PATH = re.compile(
    r"(?i)/(checkout|payment|payments|place-?order|billing)(/|$|\?)"
)
_PAY_HOST = re.compile(r"(?i)(checkout\.stripe|paypal\.com)")
_LOGIN_COPY = re.compile(
    r"(?i)\b(sign in|log in|login|enter (your )?password|verify it.?s you)\b"
)
_CHALLENGE_COPY = re.compile(
    r"(?i)(i['\u2019]m not a robot|verify you are (a )?human|"
    r"complete the security check|select all (the )?images)"
)
_PAY_CTA = re.compile(
    r"(?i)^\s*(book( now)?|pay( now)?|order( now)?|buy now|"
    r"place order|complete purchase|submit payment|confirm and pay|"
    r"reserve( now)?|confirm reservation|complete reservation|"
    r"complete booking|confirm booking|"
    r"checkout|proceed to checkout|continue to checkout|"
    r"go to checkout)\s*$"
)


@dataclass(frozen=True)
class Wall:
    kind: str  # captcha | login | pay | stuck
    reason: str
    message: str


_MESSAGES = {
    "captcha": (
        "Your turn — captcha. Tap it in her Chrome; I will continue when it is gone."
    ),
    "login": (
        "Your turn — sign in. I do not type passwords. Hit Go when you are in."
    ),
    "pay": (
        "Your turn — you click Book / Pay / Order. I stop on this screen."
    ),
    "stuck": (
        "Your turn — I cannot find the next control. The page stays."
    ),
    "hands": (
        "Your turn — you have the mouse. I will not click over you. "
        "Hit Go when you want me to drive again."
    ),
}


def wall_message(kind: str) -> str:
    return _MESSAGES.get(kind, "Your turn — the page stays.")


def your_turn_status(kind: str) -> str:
    labels = {
        "captcha": "your turn — captcha",
        "login": "your turn — sign in",
        "pay": "your turn — you click Pay",
        "stuck": "your turn — I am stuck",
        "hands": "your turn — you have the mouse",
    }
    return labels.get(kind, "your turn — page stays")


def checkout_receipt(
    *,
    url: str = "",
    title: str = "",
    heading: str = "",
    body: str = "",
) -> str:
    """Short chat line after a pay wall. She does not click Pay."""
    lines = ["Checkout is up — your turn to click Pay."]
    head = (heading or title or "").strip()
    if head:
        lines.append(head[:80])
    if url:
        lines.append(str(url).strip())
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line or line.lower().startswith(("title:", "url:", "heading:")):
            continue
        if line.casefold() == head.casefold():
            continue
        lines.append(line[:100])
        break
    return "\n".join(lines)


def pay_cta_label(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if _PAY_CTA.match(raw):
        return raw
    return None


def is_login_url(url: str) -> bool:
    """True when the URL itself is a sign-in / OAuth / X flow path."""
    raw = str(url or "").strip()
    if not raw:
        return False
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    return bool(
        _LOGIN_HOST.search(host)
        or _LOGIN_PATH.search(path)
        or _LOGIN_QUERY.search(parsed.query or "")
        or (host in _X_HOST and _LOGIN_FRAGMENT.search(parsed.fragment or ""))
    )


def site_login_url(url: str) -> str | None:
    """Canonical login URL for a host we know, else None."""
    host = (urlparse(str(url or "")).hostname or "").lower()
    if host in _X_HOST:
        return "https://x.com/login"
    return None


def login_redirected_signed_in(requested: str, landed: str) -> bool:
    """True when a login URL bounced to a non-login page (already in)."""
    want = str(requested or "").strip()
    got = str(landed or "").strip()
    if not want or not got:
        return False
    if not is_login_url(want) or is_login_url(got):
        return False
    scheme = (urlparse(got).scheme or "").lower()
    return scheme in {"http", "https"}


def nav_landed_note(requested: str, landed: str) -> str:
    """Extra lines when the tab is not the URL we asked for."""
    want = str(requested or "").strip()
    got = str(landed or "").strip()
    if not want or not got:
        return ""
    if want.split("#", 1)[0].rstrip("/") == got.split("#", 1)[0].rstrip("/"):
        return ""
    bits = [f"Requested {want}."]
    if login_redirected_signed_in(want, got):
        bits.append("Already signed in — that login URL redirected here. Stop.")
    return "\n".join(bits)


def detect_wall(
    *,
    url: str = "",
    title: str = "",
    heading: str = "",
    signals: dict[str, Any] | None = None,
    click_label: str = "",
) -> Wall | None:
    """Heuristic only. Prefer a miss over a false freeze on a normal page."""
    signals = signals or {}
    url = str(url or signals.get("url") or "")
    title = str(title or signals.get("title") or "")
    heading = str(heading or signals.get("heading") or "")
    host = (urlparse(url).hostname or "").lower()
    path = urlparse(url).path or ""
    copy = f"{title} {heading}"

    if (
        signals.get("recaptcha")
        or signals.get("hcaptcha")
        or signals.get("turnstile")
        or _CAPTCHA_HOST.search(url)
        or _CHALLENGE_COPY.search(str(signals.get("text") or ""))
        or _CHALLENGE_COPY.search(copy)
    ):
        return Wall("captcha", "challenge", wall_message("captcha"))

    if pay_cta_label(click_label):
        return Wall("pay", "cta", wall_message("pay"))
    if signals.get("card") or _PAY_HOST.search(host) or _PAY_PATH.search(path):
        return Wall("pay", "checkout", wall_message("pay"))

    login_url = is_login_url(url)
    login_copy = bool(_LOGIN_COPY.search(copy))
    if login_url or (
        (signals.get("password") or signals.get("otp")) and (login_url or login_copy)
    ):
        return Wall("login", "signin", wall_message("login"))
    return None


def attach_wall(result: Any, wall: Wall, *, ok: bool | None = None) -> Any:
    """Stamp YOUR_TURN onto an ActionResult. Leaves ok alone unless overridden."""
    from arelis.browser.actions import ActionResult
    from arelis.browser.hold import set_paused

    if not isinstance(result, ActionResult):
        return result
    set_paused(True)
    data = dict(result.data or {})
    data["code"] = YOUR_TURN
    data["wall"] = wall.kind
    data["wall_reason"] = wall.reason
    note = wall.message
    output = result.output.rstrip()
    if note not in output:
        output = f"{output}\n\n{note}" if output else note
    keep_ok = result.ok if ok is None else ok
    return ActionResult(ok=keep_ok, output=output, data=data)
