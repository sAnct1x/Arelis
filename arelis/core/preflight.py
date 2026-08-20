"""Deterministic intent hints — close the knowing-doing gap for clear cases.

Does **not** call tools or bypass confirm. It only injects a short system nudge
when the user's text already names who/what clearly enough that a 7B still
sometimes chats instead of calling the tool (session evidence + research on
small-model tool mismatch).
"""

from __future__ import annotations

import re
from typing import Any

from arelis.attachments import (
    attachment_kinds_from_turn,
    continue_prior_attachment_ask,
    is_short_affirmation,
    route_tool,
    split_attachments_turn,
    wants_image_edit,
    wants_image_text,
)
from arelis.core.agenda_complete import (
    agenda_preflight_nudge,
    agenda_read_action,
    complete_agenda_draft,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_close,
    looks_like_calendar_open,
    looks_like_calendar_read,
)
from arelis.core.email_complete import (
    complete_email_draft,
    email_preflight_nudge,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
)
from arelis.core.image_refs import (
    CAMERA_FRESH_S,
    latest_camera_image_file,
    latest_generated_image_path,
)
from arelis.core.intent_catalog import (
    AUTO_HINTS,
    DOC_ASK,
    GOALS,
    INBOX,
    IntentHint,
)
from arelis.core.look import classify_look, look_preflight_nudge
from arelis.core.plan_nudge import plan_system_message
from arelis.core.sms_complete import (
    complete_sms_draft,
    looks_like_browser_or_url,
    looks_like_closing_chitchat,
    looks_like_contacts_followup,
    looks_like_contacts_utterance,
    looks_like_image_gen,
    looks_like_stale_sms_skip,
    sms_preflight_nudge,
)

__all__ = [
    "IntentHint",
    "detect_intents",
    "draft_browser_args",
    "draft_rooms_create_args",
    "draft_signin_click_args",
    "looks_like_browser_click_signin",
    "looks_like_room_create",
    "plan_system_message",
    "preflight_system_message",
    "rewrite_browser_action",
    "rewrite_browser_calls",
    "signin_ref_from_snapshot",
    "user_asked_for_browser",
]

# Path-like token with a table extension, or explicit csv/xlsx/tsv (etc.).
_ANALYZE = re.compile(
    r"(?i)("
    r"[^\s\"']+\.(?:csv|xlsx|xls|tsv|tab|json)\b|"
    r"\b(?:csv|xlsx|xls|tsv|spreadsheet|dataframe|excel)\b|"
    r"\b(?:summarize|analyze|describe)\b.{0,48}\b(?:data|table|sheet)\b"
    r")"
)

# Open/drive the user's real browser (not scrape-for-me).
_BROWSER = re.compile(
    r"(?i)\b("
    r"pull\s+up|"
    r"bring\s+up|"
    r"open\s+up|"
    r"take\s+me\s+to|"
    r"navigate\s+to|"
    r"open\s+(?:in\s+)?(?:the\s+|your\s+|my\s+)?browser|"
    r"open\s+.{0,48}\s+in\s+(?:your|the|my)\s+browser|"
    r"in\s+your\s+browser|"
    r"your\s+browser|"
    r"control\s+(?:your|the)\s+browser|"
    r"drive\s+(?:your|the)\s+browser|"
    r"open\s*x\.?\s*com|"
    r"openx\.com|"
    r"open\s+(?:https?://\S+|(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b)|"
    r"open\s+(?:youtube|gmail|github|google|reddit|twitter|x\.com)|"
    r"re-?open\s+(?:https?://\S+|(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b|x\.com)|"
    r"go\s+to\s+(?:https?://\S+|youtube|gmail|github|x\.com|(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b)|"
    r"(?:in|with|using)\s+(?:chrome|edge|firefox)|"
    r"firefox\s+private|"
    r"private\s+browsing"
    r")\b"
)

# Screenshot the open page then describe via vision (two tools).
# Page/tab text asks go to _BROWSER_READ — pixels stay here.
_BROWSER_SCREENSHOT = re.compile(
    r"(?i)\b("
    r"(?:take\s+a\s+|capture\s+(?:a\s+)?)?screenshot\s+(?:of\s+)?"
    r"(?:this\s+)?(?:page|tab|site|browser|screen)|"
    r"screenshot\s+(?:and\s+)?describe|"
    r"describe\s+(?:what(?:'s|\s+is)\s+on\s+)?(?:the\s+|this\s+)?screen|"
    r"what(?:'s|\s+is)\s+on\s+(?:the\s+|my\s+)?screen"
    r")\b"
)

# Directions in her Chrome + a phone-ready Maps link (not scrape).
_BROWSER_MAPS = re.compile(
    r"(?i)\b("
    r"directions\s+to|"
    r"how\s+do\s+i\s+get\s+to|"
    r"(?:google\s+)?maps\s+to|"
    r"drive\s+to|"
    r"walk\s+to|"
    r"route\s+to|"
    r"(?:text|sms|send)\s+(?:me\s+)?(?:the\s+)?directions"
    r")\b"
)

_BROWSER_MAPS_SEND = re.compile(
    r"(?i)\b(?:text|sms|send)\s+(?:me\s+)?(?:the\s+)?directions\b"
)

# Search / cart in her Chrome (not scrape-the-web).
_BROWSER_SEARCH = re.compile(
    r"(?i)\b("
    r"search\s+(?:on\s+|for\s+)?(?:youtube|yt)|"
    r"(?:youtube|yt)\s+search|"
    r"search\s+youtube|"
    r"look\s+(?:up|for)\s+.{0,48}\s+on\s+youtube|"
    r"find\s+.{0,48}\s+on\s+youtube|"
    r"search\s+google\s+for|"
    r"google\s+this\s+in\s+(?:the\s+)?(?:browser|chrome)|"
    r"search\s+for\s+.{0,80}\bvideos?\b|"
    r"search\s+(?:on\s+)?amazon|"
    r"look\s+(?:up|for)\s+.{0,48}\s+on\s+amazon"
    r")\b"
)

_BROWSER_CART = re.compile(
    r"(?i)\b("
    r"add\s+(?:it\s+|that\s+|this\s+|them\s+)?to\s+(?:(?:the|my)\s+)?(?:cart|bag)|"
    r"put\s+(?:it\s+|that\s+|this\s+)?in\s+(?:(?:the|my)\s+)?(?:cart|bag)"
    r")\b"
)

# Click Sign in / Log in / login on the tab she is already on — not a fake
# action, not a guessed accounts.google.com URL.
_LOGIN_NOUN = r"(?:sign[\s-]?in|log[\s-]?in|login)"
_BROWSER_CLICK_SIGNIN = re.compile(
    r"(?i)\b("
    r"(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?" + _LOGIN_NOUN + r"|"
    r"(?:go|navigate|take\s+me|bring\s+me)\s+to\s+(?:the\s+)?" + _LOGIN_NOUN + r"|"
    r"open\s+(?:the\s+)?" + _LOGIN_NOUN + r"|"
    r"proceed\s+with\s+(?:sign(?:ing)?|log(?:ging)?)[\s-]?in|"
    r"sign\s+me\s+in|"
    r"log\s+me\s+in"
    r")\b"
)
_HOWTO_SIGNIN = re.compile(
    r"(?i)\bhow\s+(?:do\s+i|to)\s+(?:sign|log)\s*in\b"
)
_BARE_SIGNIN = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:sign|log)\s*in\s*[.!?]*$"
)
# Invented 7B actions that must become snapshot (then click Sign in by ref).
_INVENTED_SIGNIN_ACTIONS = frozenset(
    {
        "goto_sign_in",
        "go_to_sign_in",
        "goto_signin",
        "sign_in",
        "signin",
        "log_in",
        "login",
        "goto_login",
        "goto_log_in",
        "click_sign_in",
        "click_signin",
        "navigate_sign_in",
    }
)
_BROWSER_REAL_ACTIONS = frozenset(
    {
        "open",
        "navigate",
        "snapshot",
        "read",
        "maps",
        "search",
        "reserve",
        "click",
        "type",
        "tabs",
        "relaunch",
        "screenshot",
        "scroll",
        "press",
        "select",
        "wait",
    }
)

# Table / venue reservation in her Chrome (not agenda calendar).
_BROWSER_RESERVE = re.compile(
    r"(?i)\b("
    r"reserve\s+a\s+table|"
    r"book\s+a\s+table|"
    r"book\s+us\s+a\s+table|"
    r"get\s+(?:us\s+)?a\s+table|"
    r"make\s+(?:a\s+|us\s+a\s+)?reservation|"
    r"reservation\s+(?:at|for)|"
    r"table\s+for\s+\d|"
    r"opentable|"
    r"\bresy\b"
    r")\b"
)

# Compact text of the tab she is already on (not scrape-the-web).
_BROWSER_READ = re.compile(
    r"(?i)\b("
    r"read\s+(?:this|the|my)\s+(?:tab|page)|"
    r"what(?:'s|\s+is|s)\s+on\s+(?:this|the|my)\s+(?:tab|page)|"
    r"what\s+does\s+(?:this|the)\s+(?:tab|page)\s+say|"
    r"tell\s+me\s+what(?:'s|\s+is)\s+on\s+(?:this|the)\s+(?:tab|page)|"
    r"describe\s+(?:what(?:'s|\s+is)\s+on\s+)?(?:the\s+|this\s+)?(?:page|tab)"
    r")\b"
)

_WORKSPACE_WRITE = re.compile(
    r"(?i)\b("
    r"(?:write|create|save|make)\s+(?:a\s+|an\s+|the\s+|me\s+a\s+)?"
    r"(?:temp\s+|temporary\s+|text\s+|new\s+)?"
    r"(?:file|folder|directory|readme|note|document)"
    r"|"
    r"(?:write|save)\s+(?:this\s+|it\s+)?(?:to|into)\s+\S+"
    r")\b"
)

_EMAIL_SEND_VERB = re.compile(
    r"(?i)^\s*(?:e-?mail|send\s+(?:an?\s+)?(?:e-?mail|mail)|"
    r"compose\s+(?:an?\s+)?(?:e-?mail|mail)|"
    r"send\s+(?:the\s+)?(?:e-?mail|mail|it))\b"
)

_EXPLICIT_SMS_VERB = re.compile(
    r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b"
)

# See one local image (VL) — not Comfy generate.
# "analyze" is in here because it is the word the user actually says for this —
# "analyze the picture I sent you" — and it used to route nowhere. It is also the
# name of the table tool, so an image ask reached a pandas reader that answers
# "Unsupported file type: .png". The verb only counts next to an image noun, which
# leaves "analyze sales.csv" with the table tool where it belongs.
_VISION = re.compile(
    r"(?i)\b("
    r"(?:what(?:'s|\s+is)\s+in|describe|look\s+at|analys?[ez]e?|analyz)\s+"
    r"(?:(?:this|the|that|your|my)\s+)?"
    r"(?:image|screenshot|screen\s+shot|photo|photograph|diagram|picture|pic)|"
    r"(?:describe|look\s+at)\s+(?:(?:this|the|that)\s+)?"
    r"(?:image|picture|photo|puppy).{0,40}"
    r"(?:you\s+)?(?:just\s+)?(?:generated|made|created|drew|saved)|"
    r"outputs[/\\]images[/\\]\S+\.(?:png|jpe?g|webp|gif)"
    r")\b"
)


_URL_TOKEN = re.compile(
    r"(?i)\b("
    r"(?:https?://|www\.)\S+|"
    r"(?:[a-z0-9\-]+\.)+(?:com|org|net|io|dev|app|co)\b|"
    r"x\.com"
    r")\b"
)

_BROWSER_ALIASES = (
    ("youtube", "https://www.youtube.com"),
    ("gmail", "https://mail.google.com"),
    ("github", "https://github.com"),
    ("reddit", "https://www.reddit.com"),
    ("twitter", "https://x.com"),
    ("x.com", "https://x.com"),
)


def looks_like_room_create(text: str) -> bool:
    """True for 'make me a room for X' — not living rooms or 'make room'."""
    raw = text or ""
    if re.search(
        r"(?i)\b(?:living|dining|bed|hotel|guest)\s+room\b|"
        r"room\s+temperature|"
        r"\bmake\s+room\b",
        raw,
    ):
        return False
    return bool(
        re.search(
            r"(?i)\b(?:make|create|set\s+up)\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?room\b",
            raw,
        )
    )


def draft_rooms_create_args(text: str) -> dict[str, str]:
    """rooms(action=create) args from 'make me a room for astrophysics'."""
    raw = (text or "").strip()
    name = ""
    match = re.search(r"(?i)\broom\s+for\s+(?P<name>.+)$", raw)
    if match:
        name = (match.group("name") or "").strip().rstrip(".!")
    if not name:
        match = re.search(r"(?i)\broom\s+(?:called|named)\s+(?P<name>.+)$", raw)
        if match:
            name = (match.group("name") or "").strip().rstrip(".!")
    name = name.split(",")[0].strip() or "new"
    return {
        "action": "create",
        "name": name,
        "purpose": f"Work on {name}.",
    }


def looks_like_browser_click_signin(text: str) -> bool:
    """True for 'go to sign in' / 'click Sign in' — not 'how do I sign in'."""
    raw = text or ""
    if _HOWTO_SIGNIN.search(raw):
        return False
    return bool(_BROWSER_CLICK_SIGNIN.search(raw) or _BARE_SIGNIN.match(raw))


def user_asked_for_browser(text: str) -> bool:
    """True when this utterance is already a grant to drive her window.

    Bare URLs in a scrape/summarize ask are not a grant — those still pause
    if she offers the window after a JS shell.
    """
    raw = text or ""
    if looks_like_browser_click_signin(raw):
        return True
    return bool(
        _BROWSER.search(raw)
        or _BROWSER_SEARCH.search(raw)
        or _BROWSER_MAPS.search(raw)
        or _BROWSER_CART.search(raw)
        or _BROWSER_SCREENSHOT.search(raw)
        or _BROWSER_READ.search(raw)
    )


_SNAP_EL = re.compile(r"^\[(?P<ref>e\d+)\]\s+(?P<rest>.+)$", re.I | re.M)
_SIGNIN_EXACT = re.compile(r"(?i)^(?:sign[\s-]?in|log[\s-]?in|login)$")
_SIGNIN_LOOSE = re.compile(r"(?i)\b(?:sign[\s-]?in|log[\s-]?in|login)\b")


def signin_ref_from_snapshot(output: str) -> str | None:
    """First snapshot ref whose label is Sign in / Log in, not the sidebar pitch."""
    exact: list[str] = []
    loose: list[str] = []
    for match in _SNAP_EL.finditer(output or ""):
        ref = match.group("ref")
        rest = match.group("rest") or ""
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", rest)
        label = " ".join((quoted[0] if quoted else rest).split())
        if _SIGNIN_EXACT.match(label):
            exact.append(ref)
        elif _SIGNIN_LOOSE.search(label) and len(label) < 24:
            loose.append(ref)
    if exact:
        return exact[0]
    if loose:
        return loose[0]
    return None


def draft_signin_click_args(snapshot: str) -> dict[str, str] | None:
    """click(ref=…) for Sign in after a snapshot, or None if none found."""
    ref = signin_ref_from_snapshot(snapshot)
    if not ref:
        return None
    return {"action": "click", "ref": ref}


def rewrite_browser_action(action: str) -> str | None:
    """Map invented actions (goto_sign_in, sign_in, goto_*) to snapshot."""
    raw = str(action or "").strip().lower().replace("-", "_")
    if not raw or raw in _BROWSER_REAL_ACTIONS:
        return None
    if raw in _INVENTED_SIGNIN_ACTIONS or raw.startswith("goto_"):
        return "snapshot"
    return None


def rewrite_browser_calls(
    calls: list[tuple[str, dict[str, Any]]],
    *,
    text: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    """Replace invented / guessed sign-in drives with snapshot before Allow."""
    signin = looks_like_browser_click_signin(text)
    keep = {"snapshot", "click", "type", "wait"}
    out: list[tuple[str, dict[str, Any]]] = []
    for name, args in calls:
        if name != "browser":
            out.append((name, args))
            continue
        action = str((args or {}).get("action") or "")
        rewritten = rewrite_browser_action(action)
        if rewritten is None and signin:
            raw = action.strip().lower().replace("-", "_")
            if raw and raw not in keep:
                rewritten = "snapshot"
        if rewritten is None:
            out.append((name, args))
            continue
        merged = dict(args or {})
        merged["action"] = rewritten
        if rewritten == "snapshot":
            merged.pop("url", None)
            merged.pop("target", None)
        out.append(("browser", merged))
    return out


def draft_browser_args(text: str) -> dict[str, str]:
    """Open/read args when the 7B never called browser."""
    raw = text or ""
    if looks_like_browser_click_signin(raw):
        return {"action": "snapshot"}
    if _BROWSER_READ.search(raw):
        return {"action": "read"}
    if _BROWSER_SEARCH.search(raw) and not re.search(
        r"(?i)\bsearch\s+the\s+web\b", raw
    ):
        query = raw
        q_m = re.search(
            r"(?i)\bsearch\s+(?:on\s+(?:youtube|google|amazon)\s+)?(?:for\s+)?(.+)$",
            raw,
        )
        if q_m:
            query = (q_m.group(1) or "").strip().rstrip(".!?")
        query = re.sub(
            r"(?i)\s+(?:and\s+)?(?:then\s+)?tell\s+me\s+(?:the\s+)?"
            r"(?:top\s+)?(?:\d+|two|three|four|five|ten)\s+results?\s*$",
            "",
            query,
        )
        query = re.sub(
            r"(?i)\s+in\s+(?:your|the|my)\s+browser\s*$",
            "",
            query,
        )
        query = query.strip().rstrip(".!?")
        site = "youtube" if re.search(r"(?i)youtube|\bvideos?\b", raw) else "google"
        return {"action": "search", "query": query[:200], "site": site}
    match = _URL_TOKEN.search(raw)
    url = (match.group(1) if match else "").rstrip(".,)!?")
    if not url:
        lowered = raw.lower()
        for alias, href in _BROWSER_ALIASES:
            if alias in lowered:
                url = href
                break
    if url:
        return {"action": "open", "url": url}
    return {"action": "read"}


def _turn_ask(raw: str) -> str:
    """User ask with the attachments boilerplate stripped, when present."""
    _block, ask = split_attachments_turn(raw or "")
    return (ask or raw or "").strip() or (raw or "")


def detect_intents(
    text: str,
    *,
    history: list[Any] | None = None,
) -> list[IntentHint]:
    """Return zero or more high-confidence intent hints for this user turn."""
    raw = (text or "").strip()
    if not raw:
        return []
    hints: list[IntentHint] = []

    for item in AUTO_HINTS:
        if item.matches(raw):
            hints.append(item.to_hint())

    if _ANALYZE.search(raw):
        from arelis.core.email_complete import looks_like_compose_email

        path_correction = bool(
            re.search(
                r"(?i)\b("
                r"(?:file|path|document)\s+(?:is\s+)?(?:located\s+)?at|"
                r"here(?:'s|\s+is)\s+the\s+(?:file|path)|"
                r"use\s+this\s+(?:file|path)|"
                r"correct\s+path"
                r")\b",
                raw,
            )
        )
        if not looks_like_compose_email(raw) and not path_correction:
            hints.append(
                IntentHint(
                    kind="analyze",
                    expected_tools=("analyze",),
                    nudge=(
                        "Intent preflight: this message refers to a local table "
                        "(csv/xlsx/tsv or a path-like file). Call the analyze tool "
                        "with the path (action=summary unless they asked for head "
                        "or describe). Do not invent row counts or column stats, "
                        "and do not ask permission in chat."
                    ),
                )
            )

    # Only the narrow ask pattern forces doc_extract. The DOCS spec also matches a
    # bare mention of "pdf", which turns up in "email me the pdf" and "save it as
    # a pdf" — neither is a request to read one, so that half stays a hint to the
    # subset rather than an expected call.
    if DOC_ASK.search(raw):
        hints.append(
            IntentHint(
                kind="docs",
                expected_tools=("doc_extract",),
                # The closing clause is not boilerplate. Written without it, this
                # nudge routed correctly and the 7B still answered in prose three
                # times out of three — it hedged about needing access instead of
                # calling. Every sibling nudge in this file ends the same way.
                nudge=(
                    "Intent preflight: this message asks about the contents of a "
                    "document. Call doc_extract now with the path. Do not call "
                    "analyze — that reads spreadsheets only — and do not quote the "
                    "document before the tool returns. Allow still applies — do "
                    "not ask permission in chat."
                ),
            )
        )

    if _BROWSER_SCREENSHOT.search(raw):
        hints.append(
            IntentHint(
                kind="browser_vision",
                expected_tools=("browser", "vision"),
                nudge=(
                    "Intent preflight: this message asks to see what is on the "
                    "open browser page. Call browser(action=screenshot) first, "
                    "then vision with the Saved path from that result. Do not "
                    "invent pixel contents. Allow still applies — do not ask "
                    "permission in chat."
                ),
            )
        )
    elif _BROWSER_MAPS.search(raw):
        send = bool(_BROWSER_MAPS_SEND.search(raw))
        hints.append(
            IntentHint(
                kind="browser_maps",
                expected_tools=("browser", "send_sms") if send else ("browser",),
                nudge=(
                    "Intent preflight: this message asks for directions. Call "
                    "browser(action=maps, destination=the place). That opens "
                    "Google Maps in her window and returns a phone link. "
                    + (
                        "They asked to text it — then send_sms to me/myself "
                        "with that phone link. "
                        if send
                        else "Only call send_sms if they asked to text the link. "
                    )
                    + "Do not scrape. Allow still applies — do not ask "
                    "permission in chat."
                ),
            )
        )
    elif _BROWSER_RESERVE.search(raw):
        hints.append(
            IntentHint(
                kind="browser_reserve",
                expected_tools=("browser",),
                nudge=(
                    "Intent preflight: this message asks to book a table. Call "
                    "browser(action=reserve, place=the restaurant, date=YYYY-MM-DD, "
                    "time=7pm, party=2, site=opentable). That opens the search "
                    "with party/date/time in the URL. Do not scrape. Type remaining "
                    "non-secret fields after they pick a time. Never click Book / "
                    "Reserve / Confirm — that is their turn. Allow still applies "
                    "— do not ask permission in chat."
                ),
            )
        )
    elif _BROWSER_SEARCH.search(raw) and not re.search(
        r"(?i)\bsearch\s+the\s+web\b", raw
    ):
        hints.append(
            IntentHint(
                kind="browser_search",
                expected_tools=("browser",),
                nudge=(
                    "Intent preflight: this message asks to search in her "
                    "browser. Call browser(action=search, query=…, site="
                    "youtube|google|amazon). That opens results in her window. "
                    "Do not scrape or web_search instead. Then snapshot/click "
                    "a result if they asked. Allow still applies — do not ask "
                    "permission in chat."
                ),
            )
        )
    elif _BROWSER_CART.search(raw):
        hints.append(
            IntentHint(
                kind="browser_cart",
                expected_tools=("browser",),
                nudge=(
                    "Intent preflight: this message asks to add something to "
                    "a cart. Snapshot, then click Add to cart / Add to bag. "
                    "Do not click Checkout / Pay / Buy now — that is their "
                    "turn. Allow still applies — do not ask permission in chat."
                ),
            )
        )
    elif looks_like_browser_click_signin(raw):
        hints.append(
            IntentHint(
                kind="browser_click",
                expected_tools=("browser",),
                nudge=(
                    "Intent preflight: this message asks to open Sign in on "
                    "the tab she is already on. Call browser(action=snapshot), "
                    "then browser(action=click, ref=…) on the Sign in / Log in "
                    "control. Do not stop after snapshot to list refs. Prefer "
                    "the header Sign in, not the sidebar pitch. There is no "
                    "goto_sign_in or sign_in action — do not invent a URL or a "
                    "receipt. If they give a username or email, type it into a "
                    "non-secret field after snapshot. "
                    "Never type a password or OTP — that is their turn. Allow "
                    "still applies — do not ask permission in chat."
                ),
            )
        )
    elif _BROWSER_READ.search(raw):
        hints.append(
            IntentHint(
                kind="browser_read",
                expected_tools=("browser",),
                nudge=(
                    "Intent preflight: this message asks what is on the open "
                    "tab. Call browser(action=read) for compact text of that "
                    "page as it is now. Answer from that text — describe the "
                    "tab (title, Sign in, ads, sidebar); do not recap a previous "
                    "search list unless the read still shows those titles. Do "
                    "not scrape or web_fetch instead. Use screenshot + vision "
                    "only if they asked to see pixels. Allow still applies — "
                    "do not ask permission in chat."
                ),
            )
        )
    elif _BROWSER.search(raw) and not looks_like_calendar_open(raw):
        hints.append(
            IntentHint(
                kind="browser",
                expected_tools=("browser",),
                nudge=(
                    "Intent preflight: this message asks to open a site in the "
                    "user's desktop browser. Call browser(action=open, url or "
                    "alias like youtube) — that only opens the URL (no Chrome "
                    "restart). Use browser=firefox and private=true only if they "
                    "asked for Firefox private; otherwise leave browser=default. "
                    "Do not scrape instead of opening. Do not call relaunch "
                    "unless they need click/screenshot control. Allow still "
                    "applies — do not ask permission in chat."
                ),
            )
        )

    cam = latest_camera_image_file(max_age_s=CAMERA_FRESH_S)
    look = classify_look(raw, fresh_path=cam)
    if look:
        if look.path or cam:
            expected = (
                ("ocr", "vision")
                if look.act in {"read", "translate"}
                else ("vision",)
            )
        else:
            expected = (
                ("camera", "ocr", "vision")
                if look.act in {"read", "translate"}
                else ("camera", "vision")
            )
        hints.append(
            IntentHint(
                kind="vision",
                expected_tools=expected,
                nudge=look_preflight_nudge(look),
            )
        )
    elif _VISION.search(raw) and not _BROWSER_SCREENSHOT.search(raw):
        last_path = latest_generated_image_path(history)
        path_hint = (
            f" Use path={last_path}."
            if last_path
            else " Use the path from the prior image tool result or outputs/images/."
        )
        hints.append(
            IntentHint(
                kind="vision",
                expected_tools=("vision",),
                nudge=(
                    "Intent preflight: this message asks what is in a local "
                    "image/screenshot/diagram. Call vision with the path (and "
                    "optional question). Do not invent pixel contents."
                    f"{path_hint} Use image only to generate via ComfyUI. "
                    "Allow still applies — do not ask permission in chat."
                ),
            )
        )

    ask_text = _turn_ask(raw)
    image_attached = "image" in attachment_kinds_from_turn(raw)
    image_route = route_tool("image", ask_text) if image_attached else ""
    if image_attached and image_route == "vision" and not any(
        h.kind == "vision" for h in hints
    ):
        hints.append(
            IntentHint(
                kind="vision",
                expected_tools=("vision",),
                nudge=(
                    "Intent preflight: an image is attached and they asked "
                    "what is in it. Call vision with the staged path. Do not "
                    "send_sms. Do not invent pixel contents. Allow still "
                    "applies — do not ask permission in chat."
                ),
            )
        )

    if (
        wants_image_edit(ask_text)
        or image_route == "image_edit"
    ) and not wants_image_text(ask_text):
        hints.append(
            IntentHint(
                kind="image_edit",
                expected_tools=("image_edit",),
                nudge=(
                    "Intent preflight: this message asks to change an existing "
                    "picture (size, crop, or strength). Call image_edit with "
                    "the staged path. Do not call image — that generates a new "
                    "picture from a prompt. Do not call vision. Allow still "
                    "applies — do not ask permission in chat."
                ),
            )
        )
    elif looks_like_image_gen(ask_text) and not _VISION.search(ask_text):
        hints.append(
            IntentHint(
                kind="image_gen",
                expected_tools=("image",),
                nudge=(
                    "Intent preflight: this message asks to generate or redraw "
                    "an image via ComfyUI. Call the image tool with a clear "
                    "prompt (include happier / less sad / cute if they asked). "
                    "Do not web_search for stock photos. Do not claim you cannot "
                    "generate images. Do not invent a file path. Allow still "
                    "applies — do not ask permission in chat."
                ),
            )
        )

    if _WORKSPACE_WRITE.search(raw) and not _EXPLICIT_SMS_VERB.match(raw):
        hints.append(
            IntentHint(
                kind="workspace_write",
                expected_tools=("workspace",),
                nudge=(
                    "Intent preflight: this message asks to create or edit a "
                    "file under the workspace. Call workspace with "
                    "action=write or action=edit (path + content/old/new). "
                    "Do not use send_sms or contacts. Allow still applies — "
                    "do not ask permission in chat."
                ),
            )
        )

    if INBOX.matches(raw) and not _EMAIL_SEND_VERB.match(raw):
        hints.append(INBOX.to_hint())

    # Affirmation after an attachment turn — keep the model on the prior file ask.
    # Orchestrator may already have expanded "yea" into a Continue… block; match both.
    attachment_continue = (
        "Continue the prior request about these attachments" in raw
        or (
            is_short_affirmation(raw)
            and continue_prior_attachment_ask(raw, history=history) is not None
        )
    )
    if attachment_continue:
        hints.append(
            IntentHint(
                kind="attachment_continue",
                # Tool varies by kind (workspace/vision/doc_extract/analyze).
                expected_tools=(),
                nudge=(
                    "Intent preflight: the user affirmed a prior attachment "
                    "offer. Call the tool after → on each listed path and "
                    "complete that prior ask. Do not reset into a generic "
                    "greeting or ask what they meant."
                ),
            )
        )

    # Calendar create/reminder wins over nested "text my wife" SMS parses.
    if looks_like_calendar_create(raw):
        agenda_draft = complete_agenda_draft(raw, history=history)
        hints.append(
            IntentHint(
                kind="agenda_create",
                expected_tools=("agenda",),
                nudge=agenda_preflight_nudge(agenda_draft),
            )
        )
    elif looks_like_calendar_delete(raw):
        hints.append(
            IntentHint(
                kind="agenda_delete",
                expected_tools=("agenda",),
                nudge=(
                    "Intent preflight: delete/cancel a calendar event now. "
                    "Call agenda with action=delete and the event title "
                    "(and time if known). The tool resolves the id — do not "
                    "ask the user to paste a Google event id. To remove the "
                    "named event, pass keep=0. Only pass keep=1 when they "
                    "asked to delete extra copies of the same title+time. "
                    "Do not web_search. The confirm card is the Allow step."
                ),
            )
        )
        if looks_like_calendar_close(raw):
            hints.append(
                IntentHint(
                    kind="agenda_close",
                    expected_tools=("agenda",),
                    nudge=(
                        "Intent preflight: after deleting, hide the Arelis "
                        "calendar tile. Call agenda with action=close. Do not "
                        "call browser."
                    ),
                )
            )
    elif looks_like_calendar_close(raw):
        hints.append(
            IntentHint(
                kind="agenda_close",
                expected_tools=("agenda",),
                nudge=(
                    "Intent preflight: this message asks to hide the Arelis "
                    "calendar tile. Call agenda now with action=close. Do not "
                    "delete events. Do not call browser."
                ),
            )
        )
    elif looks_like_calendar_open(raw):
        hints.append(
            IntentHint(
                kind="agenda_open",
                expected_tools=("agenda",),
                nudge=(
                    "Intent preflight: this message asks to open the Arelis "
                    "calendar tile. Call agenda now with action=open. Do not "
                    "call browser with the calendar alias unless they asked "
                    "for calendar.google.com or to open it in Chrome/the "
                    "browser."
                ),
            )
        )
    elif looks_like_calendar_read(raw):
        action = agenda_read_action(raw)
        hints.append(
            IntentHint(
                kind="agenda_read",
                expected_tools=("agenda",),
                nudge=(
                    "Intent preflight: this message asks what is on the "
                    f"calendar. Call agenda now with action={action}. "
                    "Summarize the tool output (time, title, place, one-line "
                    "notes). Never invent meetings. Never ask for a Google "
                    "event id. Do not web_search."
                ),
            )
        )

    if looks_like_room_create(raw):
        name = draft_rooms_create_args(raw).get("name") or "new"
        hints.append(
            IntentHint(
                kind="rooms",
                expected_tools=("rooms",),
                nudge=(
                    "Intent preflight: this message asks to create an Arelis "
                    f"room named {name}. Call rooms(action=create) with that "
                    "name and a short purpose from the topic. Do not enter the "
                    "room yourself — tell them to say let's work on "
                    f"{name} or type /room {name}. Do not design furniture. "
                    "Allow still applies — do not ask permission in chat."
                ),
            )
        )

    if looks_like_scheduled_send(raw):
        hints.append(
            IntentHint(
                kind="schedule",
                expected_tools=("schedule",),
                    nudge=(
                        "Intent preflight: this message asks to run something later "
                        "or on a timer. Call schedule now: create_briefing for the "
                        "canned morning digest, or create with a stand-alone prompt "
                        "for any other recurring job. Do not send_email, send_sms, "
                        "or weather this turn — those run when the job fires. "
                        "Allow still applies — do not ask permission in chat."
                    ),
            )
        )

    # Goals / file-write / image-gen / calendar / browser / look turns win over
    # a stale pending SMS draft (and over "text …" buried inside a calendar reminder).
    skip_sms = (
        (
            looks_like_stale_sms_skip(raw, history)
            or bool(GOALS.matches(raw))
            or bool(_WORKSPACE_WRITE.search(raw))
            or looks_like_image_gen(raw)
            or wants_image_edit(ask_text)
            or looks_like_calendar_create(raw)
            or looks_like_calendar_delete(raw)
            or looks_like_calendar_close(raw)
            or looks_like_calendar_open(raw)
            or looks_like_calendar_read(raw)
            or looks_like_browser_or_url(raw)
            or looks_like_browser_click_signin(raw)
            or looks_like_scheduled_send(raw)
            or looks_like_schedule_manage(raw)
            or any(
                h.kind in {"analyze", "vision", "image_edit", "rooms", "browser_click"}
                for h in hints
            )
            or (image_attached and not _EXPLICIT_SMS_VERB.match(raw))
        )
        and not _EXPLICIT_SMS_VERB.match(raw)
    )
    draft = None if skip_sms else complete_sms_draft(raw, history=history)
    if draft is not None:
        hints.append(
            IntentHint(
                kind="sms_send",
                expected_tools=("send_sms",),
                nudge=sms_preflight_nudge(draft),
            )
        )

    # Inbox / analyze / vision / calendar / image / schedule must not revive a compose.
    skip_email = looks_like_scheduled_send(raw) or looks_like_schedule_manage(raw) or (
        (
            bool(INBOX.matches(raw))
            or any(
                h.kind in {"analyze", "vision", "image_edit", "schedule", "rooms"}
                for h in hints
            )
            or looks_like_image_gen(raw)
            or looks_like_calendar_create(raw)
            or looks_like_calendar_delete(raw)
            or looks_like_calendar_close(raw)
            or looks_like_calendar_open(raw)
            or looks_like_calendar_read(raw)
            or looks_like_browser_or_url(raw)
            or looks_like_browser_click_signin(raw)
            or looks_like_closing_chitchat(raw)
        )
        and not _EMAIL_SEND_VERB.search(raw)
    )
    email_draft = None if skip_email else complete_email_draft(raw, history=history)
    if email_draft is not None:
        hints.append(
            IntentHint(
                kind="compose_email",
                expected_tools=("send_email",),
                nudge=email_preflight_nudge(email_draft),
            )
        )

    if looks_like_scheduled_send(raw):
        hints = [
            h
            for h in hints
            if h.kind not in {"weather", "compose_email", "sms_send"}
        ]
        if not any(h.kind == "schedule" for h in hints):
            hints.append(
                IntentHint(
                    kind="schedule",
                    expected_tools=("schedule",),
                    nudge=(
                        "Intent preflight: this message asks to run something "
                        "later or on a timer. Call schedule now. Do not "
                        "send_email, send_sms, or weather this turn."
                    ),
                )
            )

    if looks_like_schedule_manage(raw):
        hints = [
            h
            for h in hints
            if h.kind not in {"weather", "compose_email", "sms_send"}
        ]
        if not any(h.kind == "schedule" for h in hints):
            hints.append(
                IntentHint(
                    kind="schedule",
                    expected_tools=("schedule",),
                    nudge=(
                        "Intent preflight: this message asks to list or change "
                        "a saved job. Call schedule (list or delete). Do not "
                        "weather, send_email, or send_sms this turn — a word "
                        "in a job name is not the ask."
                    ),
                )
            )

    if looks_like_contacts_utterance(raw) or looks_like_contacts_followup(
        raw, history
    ):
        hints.append(
            IntentHint(
                kind="contacts",
                expected_tools=("contacts",),
                nudge=(
                    "Intent preflight: look up the person in the contacts "
                    "book now. Call contacts with action=get and who= the "
                    "alias (wife, mom, …). Read the SMS phone line from the "
                    "tool. Do not invent a number or reuse another contact's "
                    "email. Do not offer to send a message unless they asked."
                ),
            )
        )

    return hints


def preflight_system_message(
    text: str,
    *,
    history: list[Any] | None = None,
) -> str | None:
    """Single system block combining all nudges, or None if nothing matched."""
    hints = detect_intents(text, history=history)
    if not hints:
        return None
    return "\n".join(h.nudge for h in hints)
