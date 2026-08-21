"""Deterministic micro-plan nudges for deep-dive / multi-tool turns.

Injects a short ``Plan: 1) … 2) …`` system block, and can emit a one-shot
mid-turn progress nudge when earlier steps ran but later tools were skipped.
Does **not** call tools or bypass Allow.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from arelis.attachments import attachment_kinds_from_turn, wants_image_text
from arelis.core.intent_catalog import (
    BARE_SIGNIN,
    BROWSER_CART,
    BROWSER_CLICK_SIGNIN,
    BROWSER_MAPS,
    BROWSER_READ,
    BROWSER_RESERVE,
    BROWSER_SEARCH,
    DEADLINE,
    HOWTO_SIGNIN,
    RESEARCH,
    corrects_a_path,
    mentions_tabular_data,
)

# Align with preflight deep-dive shapes.
_INBOX = re.compile(
    r"(?i)\b("
    r"inbox|"
    r"unread\s+mail|"
    r"summarize\s+(?:my\s+)?(?:mail|email|inbox)|"
    r"what(?:'s|\s+is)\s+in\s+my\s+(?:inbox|mail)|"
    r"check\s+(?:my\s+)?(?:email|mail|inbox)"
    r")\b"
)

_MULTI_WEB = re.compile(
    r"(?i)\b("
    r"look\s+up|search\s+for|google|"
    r"find\s+(?:out|pages?|articles?)|"
    r"latest\s+on|what\s+happened|"
    r"scrape|read\s+(?:this|the)\s+(?:page|article|url)"
    r")\b"
)

_DOC = re.compile(
    r"(?i)\b("
    r"what\s+does\s+(?:this|the)\s+(?:pdf|document|doc)\s+say|"
    r"extract\s+text\s+from|"
    r"read\s+(?:this|the)\s+pdf"
    r")\b"
)

_DOCUMENT = re.compile(
    r"(?i)\b("
    r"(?:create|make|write|generate|export|draft)\s+"
    r"(?:(?:me\s+)?(?:a\s+|an\s+|the\s+)?)?"
    r"(?:pdf|docx|xlsx|csv|spreadsheet|"
    r"word\s+doc(?:ument)?|markdown(?:\s+file)?|text\s+file)|"
    r"(?:save|export)\s+(?:(?:it|this|that)\s+)?(?:as|to)\s+(?:a\s+)?"
    r"(?:pdf|docx|xlsx|csv|excel|word|markdown)"
    r")\b"
)

_GIT = re.compile(
    r"(?i)\b("
    r"git\s+status|"
    r"what(?:'s|\s+is)\s+(?:on\s+)?(?:my\s+)?branch|"
    r"uncommitted|"
    r"working\s+tree|"
    r"git\s+diff|"
    r"recent\s+commits?"
    r")\b"
)

_AGENDA = re.compile(
    r"(?i)\b("
    r"on\s+my\s+calendar|"
    r"what(?:'s|\s+is)\s+on\s+(?:my\s+)?(?:calendar|agenda)|"
    r"meetings?\s+today|"
    r"meetings?\s+tomorrow|"
    r"calendar\s+today|"
    r"calendar\s+event|"
    r"create\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)|"
    r"add\s+(?:to\s+)?(?:my\s+)?calendar|"
    r"add\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)"
    r")\b"
)

_AGENDA_CREATE = re.compile(
    r"(?i)\b("
    r"create\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)|"
    r"add\s+(?:to\s+)?(?:my\s+)?calendar|"
    r"add\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)|"
    r"calendar\s+event\s+for|"
    r"set\s+(?:an?\s+)?(?:calendar\s+)?reminder|"
    r"put\s+(?:this\s+)?on\s+(?:my\s+)?calendar|"
    r"at\s+an?\s+event\s+for"
    r")\b"
)

_BROWSER_SEE = re.compile(
    r"(?i)\b("
    r"open\s+(?:the\s+)?(?:page|site|url|browser)|"
    r"screenshot\s+(?:and\s+)?describe|"
    r"what(?:'s|\s+is)\s+on\s+(?:the\s+)?screen|"
    r"look\s+at\s+(?:this|the)\s+page"
    r")\b"
)

_CLIPBOARD = re.compile(
    r"(?i)\b("
    r"clipboard|"
    r"what\s+did\s+i\s+copy|"
    r"what(?:'s|\s+is)\s+on\s+(?:my\s+)?clipboard|"
    r"paste\s+from\s+clipboard|"
    r"read\s+(?:the\s+)?clipboard"
    r")\b"
)

_OCR = re.compile(
    r"(?i)\b("
    r"\bocr\b|"
    r"extract\s+text\s+from\s+(?:this\s+)?(?:image|screenshot|png)|"
    r"what(?:'s|\s+is)\s+written\s+on|"
    r"read\s+(?:the\s+)?text\s+in\s+(?:this\s+)?(?:image|screenshot)"
    r")\b"
)

_GOALS = re.compile(
    r"(?i)\b("
    r"my\s+goals?|"
    r"list\s+(?:my\s+)?goals?|"
    r"what\s+am\s+i\s+working\s+toward"
    r")\b"
)


@dataclass(frozen=True)
class PlanSpec:
    """Named multi-step plan: message for the model + ordered tool steps."""

    id: str
    message: str
    steps: tuple[str, ...]
    # When True, agent_loop's scrape_after_search already covers step 2.
    skip_progress: bool = False


_PLAN_RESEARCH = PlanSpec(
    id="research",
    message=(
        "Plan: 1) Call research_report with the user's question as query "
        "(recency=day/week for news). 2) Answer from the report and its Sources; "
        "do not invent citations."
    ),
    steps=("research_report",),
)

_PLAN_WEATHER = PlanSpec(
    id="weather",
    message=(
        "Plan: 1) Call the weather tool for the user's place. "
        "2) Answer only from the tool result."
    ),
    steps=("weather",),
    skip_progress=True,  # weather_force_call owns nudge/inject
)

_PLAN_RECALL = PlanSpec(
    id="recall",
    message=(
        "Plan: 1) Call recall before answering from memory. "
        "2) Ground the reply in recall hits, or say you do not know."
    ),
    steps=("recall",),
)

_PLAN_INBOX = PlanSpec(
    id="inbox",
    message=(
        "Plan: 1) Call inbox(action='summarize') for triage. "
        "2) If they asked to reply or send, call send_email with the draft "
        "(Allow still required — never skip the confirm card)."
    ),
    steps=("inbox",),
)

_PLAN_COMPOSE_EMAIL = PlanSpec(
    id="compose_email",
    message=(
        "Plan: 1) Call send_email with to/subject/body (and attach=path when "
        "they named a file). Use the literal address they gave — do not "
        "web_search for contacts. "
        "2) Allow still required — never skip the confirm card."
    ),
    steps=("send_email",),
    skip_progress=True,  # email_force_call owns nudge/inject
)

_PLAN_MULTI = PlanSpec(
    id="multi_web",
    message=(
        "Plan: 1) web_search for the question. "
        "2) scrape the best URL from the results. "
        "3) Answer with a short Sources list."
    ),
    steps=("web_search", "scrape"),
    skip_progress=True,  # scrape_after_search gate owns step 2
)

_PLAN_DEADLINE = PlanSpec(
    id="deadline",
    message=(
        "Plan: 1) Call tasks with action=list for open items. "
        "2) Call agenda with action=list or range for upcoming events. "
        "3) Summarize conflicts and stale open tasks; Allow still required "
        "for any mutate (add/done/create/update/delete)."
    ),
    steps=("tasks", "agenda"),
)

_PLAN_ANALYZE = PlanSpec(
    id="analyze",
    message=(
        "Plan: 1) Call analyze on the named table/CSV path. "
        "2) Answer with computed stats from the tool only — do not invent rows."
    ),
    steps=("analyze",),
)

_PLAN_DOCUMENT = PlanSpec(
    id="document",
    message=(
        "Plan: 1) Call document with format (pdf, docx, xlsx, csv, md, or txt), "
        "title, and the full body (rows for a spreadsheet). "
        "2) Tell them the path (the room's documents folder when a room is "
        "open, otherwise outputs/documents/). "
        "Set replace=true when they asked to fix, update, or export that file. "
        "Use from_path for an existing markdown draft. "
        "Do not paste the file into chat. Do not call doc_extract. Allow still applies."
    ),
    steps=("document",),
)

_PLAN_DOC = PlanSpec(
    id="docs",
    message=(
        "Plan: 1) Call doc_extract on the PDF/document path. "
        "2) Quote or paraphrase only from the extracted text."
    ),
    steps=("doc_extract",),
)

_PLAN_ATTACH_VISION = PlanSpec(
    id="attach_vision",
    message=(
        "Plan: 1) Call vision on each attached image path (Allow). "
        "2) Answer from the vision result only. "
        "Never call doc_extract on images — that tool is PDF-only."
    ),
    steps=("vision",),
)

_PLAN_GIT = PlanSpec(
    id="git",
    message=(
        "Plan: 1) Call git_info (status/diff/log as asked). "
        "2) Report branch state from the tool — do not invent commits."
    ),
    steps=("git_info",),
)

_PLAN_AGENDA_OPEN = PlanSpec(
    id="agenda_open",
    message=(
        "Plan: 1) Call agenda with action=open. That opens the Arelis "
        "calendar tile. Do not open calendar.google.com in the browser "
        "unless they asked for the website."
    ),
    steps=("agenda",),
)

_PLAN_AGENDA_CLOSE = PlanSpec(
    id="agenda_close",
    message=(
        "Plan: 1) Call agenda with action=close. That hides the Arelis "
        "calendar tile. Do not delete events."
    ),
    steps=("agenda",),
)

_PLAN_TILE = PlanSpec(
    id="tile",
    message=(
        "Plan: 1) Call tile with action=open or close and the tile name "
        "(thinking, workspace, history, notifications, camera, contacts, "
        "calendar). That is the View menu. Do not use the browser."
    ),
    steps=("tile",),
)

_PLAN_AGENDA = PlanSpec(
    id="agenda",
    message=(
        "Plan: 1) Call agenda with action=today, tomorrow, list, or range. "
        "2) Summarize the tool output (time, title, place, one-line notes). "
        "Never invent meetings. Never quote Google event ids."
    ),
    steps=("agenda",),
)

_PLAN_AGENDA_DELETE = PlanSpec(
    id="agenda_delete",
    message=(
        "Plan: 1) Call agenda with action=delete, keep=0, and the event "
        "title/time. keep=0 removes every matching copy. The tool resolves "
        "the id — do not ask the user to paste a Google id. Do not list "
        "instead of deleting."
    ),
    steps=("agenda",),
    skip_progress=True,  # agenda_force delete owns nudge/inject
)

_PLAN_AGENDA_CREATE = PlanSpec(
    id="agenda_create",
    message=(
        "Plan: 1) Call agenda with action=create, provider=google "
        "(or outlook if asked), summary and start from the user's wording. "
        "2) A calendar reminder to text someone later is the event title/"
        "description — do not call send_sms unless they asked to text now. "
        "Allow required; do not give manual calendar-app steps only."
    ),
    steps=("agenda",),
    skip_progress=True,  # agenda_force_call owns nudge/inject
)

_PLAN_BROWSER_SEE = PlanSpec(
    id="browser_see",
    message=(
        "Plan: 1) browser(action=screenshot) on the open tab (Allow). "
        "2) vision(path=…) on that PNG to describe it. "
        "Do not invent what the page shows."
    ),
    steps=("browser", "vision"),
)

_PLAN_BROWSER_MAPS = PlanSpec(
    id="browser_maps",
    message=(
        "Plan: 1) browser(action=maps, destination=the place) — opens Maps "
        "in her window and returns a phone link. Do not scrape. "
        "2) If they asked to text it, send_sms to me/myself with that link "
        "(Allow). Do not invent a maps URL."
    ),
    steps=("browser",),
)

_PLAN_BROWSER_SEARCH = PlanSpec(
    id="browser_search",
    message=(
        "Plan: 1) browser(action=search, query=…, site=youtube|google|amazon) "
        "in her window. Do not scrape. "
        "2) Snapshot and click a result if they asked. Add to cart is fine. "
        "Stop before Checkout / Pay / Buy now."
    ),
    steps=("browser",),
)

_PLAN_BROWSER_RESERVE = PlanSpec(
    id="browser_reserve",
    message=(
        "Plan: 1) browser(action=reserve, place=the restaurant, date=YYYY-MM-DD, "
        "time=7pm, party=2) — opens OpenTable with those bits in the URL. "
        "2) Snapshot and type remaining non-secret fields. "
        "Never click Book / Reserve / Confirm — that is their turn."
    ),
    steps=("browser",),
)

_PLAN_BROWSER_READ = PlanSpec(
    id="browser_read",
    message=(
        "Plan: 1) browser(action=read) on the tab she is on (Allow). "
        "That is compact text of the open page, not scrape. "
        "2) Answer from that text as it is now. Do not recap a previous "
        "search list unless the read still shows those titles. "
        "Use screenshot+vision only if they asked to see pixels."
    ),
    steps=("browser",),
)

_PLAN_BROWSER_CLICK = PlanSpec(
    id="browser_click",
    message=(
        "Plan: 1) browser(action=snapshot) on the tab she is on (Allow). "
        "2) browser(action=click, ref=…) on Sign in / Log in. "
        "There is no goto_sign_in action. Do not invent a URL or a receipt. "
        "Username they give can go in a non-secret field. Never type a "
        "password or OTP — that is their turn."
    ),
    steps=("browser",),
)

_PLAN_CLIPBOARD = PlanSpec(
    id="clipboard",
    message=(
        "Plan: 1) Call clipboard (Allow — may hold secrets). "
        "2) Use only the returned text; never invent clipboard contents."
    ),
    steps=("clipboard",),
)

_PLAN_OCR = PlanSpec(
    id="ocr",
    message=(
        "Plan: 1) Call ocr (action=text with path, or action=screen). Allow required. "
        "2) Answer from OCR text; use vision only if they want a description."
    ),
    steps=("ocr",),
)

_PLAN_GOALS = PlanSpec(
    id="goals",
    message=(
        "Plan: 1) Call goals with action=list. "
        "2) Summarize active goals from the tool — do not invent titles."
    ),
    steps=("goals",),
)


def select_plan(
    text: str,
    preflight_kinds: Sequence[str] | None = None,
    skill_ids: Sequence[str] | None = None,
) -> PlanSpec | None:
    """Pick the highest-priority PlanSpec for this turn, or None."""
    kinds = _norm_set(preflight_kinds)
    skills = _norm_set(skill_ids)
    raw = (text or "").strip()
    if not raw and not kinds and not skills:
        return None
    from arelis.core.intent_catalog import looks_like_local_clock_ask
    from arelis.core.sms_complete import looks_like_closing_chitchat

    if raw and looks_like_closing_chitchat(raw):
        return None
    # now_line already has the time. The unmatched web fallback used to pass
    # skill_ids=["web"] and inject a scrape plan for "what time is it".
    if raw and looks_like_local_clock_ask(raw):
        return None

    if "document" in kinds or "document" in skills or (raw and _DOCUMENT.search(raw)):
        return _PLAN_DOCUMENT

    if "research" in kinds or "research" in skills or RESEARCH.matches(raw):
        return _PLAN_RESEARCH

    if "deadline_pack" in kinds or "deadline" in skills or DEADLINE.matches(raw):
        return _PLAN_DEADLINE

    if "weather" in kinds or "weather" in skills:
        return _PLAN_WEATHER

    # Chat attachments: kind already classified — do not let "document" / extract
    # wording send a PNG to doc_extract. Emailing an attached table wins over analyze.
    from arelis.core.email_complete import looks_like_compose_email

    if "compose_email" in kinds or (raw and looks_like_compose_email(raw)):
        return _PLAN_COMPOSE_EMAIL

    att_kinds = attachment_kinds_from_turn(raw)
    if "image" in att_kinds:
        if wants_image_text(raw) or (raw and _OCR.search(raw)) or "ocr" in skills:
            return _PLAN_OCR
        return _PLAN_ATTACH_VISION
    if "pdf" in att_kinds:
        return _PLAN_DOC
    if "data" in att_kinds:
        return _PLAN_ANALYZE

    if "ocr" in skills or (raw and _OCR.search(raw)):
        return _PLAN_OCR

    if "clipboard" in skills or (raw and _CLIPBOARD.search(raw)):
        return _PLAN_CLIPBOARD

    if "analyze" in kinds or "analyze" in skills or mentions_tabular_data(raw):
        if not corrects_a_path(raw):
            return _PLAN_ANALYZE

    if "docs" in skills or (raw and _DOC.search(raw)):
        return _PLAN_DOC

    if "git" in skills or (raw and _GIT.search(raw)):
        return _PLAN_GIT

    from arelis.core.agenda_complete import (
        looks_like_calendar_close,
        looks_like_calendar_open,
    )

    if "agenda_close" in kinds or (raw and looks_like_calendar_close(raw)):
        return _PLAN_AGENDA_CLOSE

    if "agenda_open" in kinds or (raw and looks_like_calendar_open(raw)):
        return _PLAN_AGENDA_OPEN

    if "tile_open" in kinds or "tile_close" in kinds:
        return _PLAN_TILE

    if raw:
        from arelis.core.tile_complete import match_tile_intent

        if match_tile_intent(raw):
            return _PLAN_TILE

    if raw and BROWSER_MAPS.search(raw):
        return _PLAN_BROWSER_MAPS

    if raw and BROWSER_RESERVE.search(raw):
        return _PLAN_BROWSER_RESERVE

    # Cart is a separate matcher in the catalog, but the plan for both is the
    # same one: drive Chrome rather than scrape. Checked here so the split does
    # not quietly drop "add it to my cart", which this module used to fold into
    # its own copy of the search matcher.
    if raw and (BROWSER_SEARCH.search(raw) or BROWSER_CART.search(raw)):
        return _PLAN_BROWSER_SEARCH

    if raw and BROWSER_READ.search(raw) and "screenshot" not in raw.lower():
        return _PLAN_BROWSER_READ

    if raw and (
        (BROWSER_CLICK_SIGNIN.search(raw) or BARE_SIGNIN.match(raw))
        and not HOWTO_SIGNIN.search(raw)
    ):
        return _PLAN_BROWSER_CLICK

    if (
        "browser" in skills
        or "vision" in skills
        or (raw and _BROWSER_SEE.search(raw))
    ):
        return _PLAN_BROWSER_SEE

    if (
        "agenda_create" in kinds
        or (raw and _AGENDA_CREATE.search(raw))
    ):
        return _PLAN_AGENDA_CREATE

    if "agenda_delete" in kinds or (
        raw
        and re.search(
            r"(?i)\b(?:delete|remove|cancel)\b.{0,40}\b(?:event|meeting|appointment|reminder)\b",
            raw,
        )
    ):
        return _PLAN_AGENDA_DELETE

    if (
        "agenda_read" in kinds
        or "agenda" in skills
        or (raw and _AGENDA.search(raw))
    ):
        return _PLAN_AGENDA

    if "goals" in skills or (raw and _GOALS.search(raw)):
        return _PLAN_GOALS

    if "recall" in kinds or (
        "memory" in skills
        and raw
        and re.search(r"(?i)\b(recall|did i|you told)\b", raw)
        and not re.search(r"(?i)\b(?:remember|forget)\s+that\b", raw)
    ):
        return _PLAN_RECALL

    if "compose_email" in kinds:
        return _PLAN_COMPOSE_EMAIL

    if "email" in skills or (raw and _INBOX.search(raw)):
        return _PLAN_INBOX

    if (
        "web" in skills
        or len(kinds) >= 2
        or (raw and _MULTI_WEB.search(raw))
    ):
        return _PLAN_MULTI

    return None


def plan_system_message(
    text: str,
    preflight_kinds: Sequence[str] | None = None,
    skill_ids: Sequence[str] | None = None,
) -> str | None:
    """Return a short Plan block for matching intents, or None."""
    plan = select_plan(text, preflight_kinds, skill_ids)
    return plan.message if plan else None


def plan_progress_notice(
    plan: PlanSpec,
    tools_used: set[str] | Iterable[str],
    *,
    available_tools: set[str] | Iterable[str] | None = None,
) -> str | None:
    """One-shot nudge for the next unfinished plan step, or None.

    Skipped when ``plan.skip_progress`` (owned by another gate) or when no
    remaining step is both available and unused.
    """
    if plan.skip_progress:
        return None
    used = {str(t).strip().lower() for t in tools_used if str(t).strip()}
    available = (
        {str(t).strip().lower() for t in available_tools if str(t).strip()}
        if available_tools is not None
        else None
    )
    # At least one earlier step should have run before we nag about later ones.
    # For single-step plans, nudge when the only tool was never called.
    if len(plan.steps) > 1 and not (used & set(plan.steps)):
        return None
    for step in plan.steps:
        tool = step.lower()
        if available is not None and tool not in available:
            continue
        if tool in used:
            continue
        return (
            f"Plan progress: next call {tool} "
            f"(plan={plan.id}). Do not invent results; Allow still applies."
        )
    return None


def _norm_set(values: Iterable[str] | None) -> set[str]:
    if not values:
        return set()
    return {str(v).strip().lower() for v in values if str(v).strip()}
