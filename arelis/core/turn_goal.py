"""One-line turn goal that can unlock a wrong regex lock.

Preflight, complete-draft inject, and empty-after-tool used to treat a
local match as the job. This module derives what success still is, then
strips contradictory expected tools, refuses to inject a body the
recipient should not read, and refuses to finish on a receipt that does
not serve the ask.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arelis.browser.walls import login_redirected_signed_in
from arelis.core.email_complete import looks_like_compose_email
from arelis.core.intent_catalog import exactness_match
from arelis.core.preflight import (
    looks_like_browser_click_signin,
    looks_like_browser_open_ask,
    signin_ref_from_snapshot,
)
from arelis.core.sms_complete import sms_intent_this_turn
from arelis.core.tool_subset import is_deep_dive_ask, is_research_mode

_BOT_WALL = re.compile(
    r"(?i)\b("
    r"are you a robot|"
    r"captcha|"
    r"access denied|"
    r"sign in to continue|"
    r"password-protected|"
    r"verify you are human"
    r")\b"
)
_REPORTED_AFFECT = re.compile(
    r"(?i)^(?:that\s+)?(?:i|we)\s+(?:just\s+)?"
    r"(?:love|miss|need|adore)\s+(?:her|him|them)\s*[.!?]*$"
)
_YOUR_TURN = re.compile(r"(?i)\byour turn\b")


@dataclass(frozen=True)
class TurnGoal:
    """What this turn still owes after the regex layer has guessed."""

    kind: str
    line: str
    need: frozenset[str] = frozenset()
    forbid: frozenset[str] = frozenset()
    done_tools: frozenset[str] = frozenset()


NONE = TurnGoal(kind="none", line="")

_LINES = {
    "research": (
        "A sourced write-up. Not a forecast, not a login wall, "
        "not the same URL again."
    ),
    "weather": "A weather-tool forecast for the place they named.",
    "sms": "Send the recipient a message they should read, then stop.",
    "email": "Send the email they asked for, then stop.",
    "browser": (
        "Open the page they asked for. If they asked to check "
        "login: stop when they are already in, or open login once "
        "and hand the mouse over. Do not type a password."
    ),
}


def derive_turn_goal(
    text: str,
    role: str = "",
    *,
    kinds: list[str] | tuple[str, ...] | None = None,
    sms_draft: Any = None,
    email_draft: Any = None,
    research_mode: bool | None = None,
) -> TurnGoal:
    """Pick one goal. Research beats a temperature-word weather false lock."""
    raw = text or ""
    kinds = tuple(kinds or ())
    research = (
        (research_mode if research_mode is not None else is_research_mode(role, raw))
        or "research" in kinds
        or is_deep_dive_ask(raw)
    )
    exact_wx = exactness_match("weather", raw)
    sms = (
        (sms_draft is not None and bool(getattr(sms_draft, "complete", False)))
        or "sms_send" in kinds
        or sms_intent_this_turn(raw)
    )
    email = (
        (email_draft is not None and bool(getattr(email_draft, "complete", False)))
        or "compose_email" in kinds
        or looks_like_compose_email(raw)
    )
    if sms:
        return TurnGoal(
            kind="sms",
            line=_LINES["sms"],
            need=frozenset({"send_sms"}),
            forbid=frozenset(
                {"weather", "research_report", "web_search", "browser"}
            ),
            done_tools=frozenset({"send_sms"}),
        )
    if email:
        return TurnGoal(
            kind="email",
            line=_LINES["email"],
            need=frozenset({"send_email"}),
            forbid=frozenset({"weather", "research_report", "web_search"}),
            done_tools=frozenset({"send_email"}),
        )
    if research and (is_deep_dive_ask(raw) or not exact_wx):
        return TurnGoal(
            kind="research",
            line=_LINES["research"],
            need=frozenset({"research_report"}),
            forbid=frozenset({"weather"}),
            done_tools=frozenset({"research_report", "scrape", "web_fetch"}),
        )
    if exact_wx or ("weather" in kinds and not research):
        return TurnGoal(
            kind="weather",
            line=_LINES["weather"],
            need=frozenset({"weather"}),
            forbid=frozenset(
                {
                    "web_search",
                    "scrape",
                    "web_fetch",
                    "research_report",
                    "browser",
                }
            ),
            done_tools=frozenset({"weather"}),
        )
    if "browser" in kinds:
        return TurnGoal(
            kind="browser",
            line=_LINES["browser"],
            need=frozenset({"browser"}),
            forbid=frozenset({"weather", "research_report"}),
            done_tools=frozenset({"browser"}),
        )
    return NONE


def apply_goal_to_expected(
    expected: set[str], goal: TurnGoal
) -> tuple[set[str], tuple[str, ...]]:
    """Drop tools that contradict the goal; add the tool that can finish it."""
    out = set(expected)
    dropped = tuple(sorted(out & goal.forbid))
    out -= goal.forbid
    if goal.need and goal.kind != "none":
        out |= set(goal.need)
    return out, dropped


def sms_body_serves_goal(body: str) -> bool:
    """False when the body is still third-person reported speech."""
    text = (body or "").strip()
    if not text:
        return False
    return not _REPORTED_AFFECT.match(text)


def receipt_serves_goal(
    goal: TurnGoal,
    tool: str,
    output: str,
    *,
    data: dict[str, Any] | None = None,
) -> bool:
    """True when this successful tool result can stand as the finish."""
    name = (tool or "").strip()
    out = output or ""
    data = data or {}
    if goal.kind == "none":
        return not _BOT_WALL.search(out)
    if name in goal.forbid:
        return False
    if _BOT_WALL.search(out) and goal.kind != "browser":
        return False
    if goal.kind == "research":
        if name == "research_report":
            return True
        if name in {"scrape", "web_fetch"}:
            return (not _BOT_WALL.search(out)) and len(out) >= 200
        return False
    if goal.kind == "weather":
        return name == "weather"
    if goal.kind == "sms":
        return name == "send_sms"
    if goal.kind == "email":
        return name == "send_email"
    if goal.kind == "browser":
        if name != "browser":
            return False
        if _BOT_WALL.search(out) and not _YOUR_TURN.search(out):
            return False
        wall = str(data.get("wall") or data.get("code") or "").lower()
        if wall in {"login", "hands", "captcha", "your_turn", "pay"}:
            return True
        return not _BOT_WALL.search(out)
    return name in goal.done_tools


DRIVE = "drive"
SIGNED_IN = "signed_in"
LOGIN_READY = "login_ready"
NEED_LOGIN = "need_login"
OPEN = "open"

LOGIN_READY_REPLY = (
    "Login is up. Sign in in the window — I don't type passwords."
)


@dataclass(frozen=True)
class BrowserErrand:
    """What a login-check / open ask still owes after one browser receipt."""

    status: str
    reply: str = ""

    @property
    def done(self) -> bool:
        return self.status in {SIGNED_IN, LOGIN_READY, OPEN}


def browser_open_done_reply(text: str, *, signed_in: bool = False) -> str:
    """Chat line when the tab already finishes an open / login-if-needed ask."""
    if signed_in or looks_like_browser_click_signin(text):
        return "You're already signed in. The tab is open."
    return "The page is open."


def browser_errand_done(
    text: str,
    *,
    action: str,
    requested_url: str = "",
    landed_url: str = "",
    wall: str = "",
    snapshot: str = "",
    signed_in: bool = False,
) -> BrowserErrand:
    """Whether the open / login-check ask is finished, needs a hop, or drives on."""
    act = (action or "").strip().lower()
    if act not in {"open", "navigate", "snapshot", "click"}:
        return BrowserErrand(DRIVE)
    kind = (wall or "").strip().lower()
    login_check = looks_like_browser_click_signin(text)
    open_ask = looks_like_browser_open_ask(text)
    if kind in {"login", "your_turn"} and (login_check or open_ask):
        return BrowserErrand(LOGIN_READY, LOGIN_READY_REPLY)
    if kind in {"captcha", "hands", "stuck", "pay"}:
        return BrowserErrand(DRIVE)
    bounced = signed_in or login_redirected_signed_in(requested_url, landed_url)
    if bounced:
        return BrowserErrand(
            SIGNED_IN, browser_open_done_reply(text, signed_in=True)
        )
    if not open_ask:
        return BrowserErrand(DRIVE)
    snap = snapshot or ""
    if login_check and signin_ref_from_snapshot(snap):
        return BrowserErrand(NEED_LOGIN)
    if login_check and act == "open" and not snap:
        return BrowserErrand(NEED_LOGIN)
    if signin_ref_from_snapshot(snap) and not login_check:
        return BrowserErrand(DRIVE)
    if not (landed_url or requested_url or snap):
        return BrowserErrand(DRIVE)
    return BrowserErrand(
        SIGNED_IN if login_check else OPEN,
        browser_open_done_reply(text, signed_in=login_check),
    )


def goal_unlock_notice(goal: TurnGoal) -> str:
    """User-role nudge when the last receipt does not finish the ask."""
    line = goal.line or "the user's actual ask"
    return (
        f"Goal unlock: the last tool result does not finish this turn. "
        f"{line} Do not treat that receipt as the answer. "
        "Call a tool that serves the goal, or say you do not have it yet."
    )


def goal_miss_reply(goal: TurnGoal) -> str:
    """Chat line when we refuse to ship a receipt that fails the goal."""
    if goal.kind == "research":
        return (
            "That last page was not a usable source, so I do not have "
            "the report yet. Ask again and I will search, not reuse "
            "that tab."
        )
    if goal.kind == "sms":
        return (
            "I stopped before sending a message the recipient should "
            "not read. Say what to text them."
        )
    if goal.kind == "browser":
        return (
            "That page did not finish the errand (login wall or a bot "
            "check). The window is still there."
        )
    return (
        "The last tool result does not finish what you asked. "
        "Say it again and I will take another pass."
    )
