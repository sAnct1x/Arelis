"""Turn helpers that lived under AgentLoop. Re-exported from agent_loop."""

from __future__ import annotations

import json
import re
from typing import Any

from arelis.core.claims import (
    answer_looks_like_refusal,
    send_claim_missing_kinds,
    unsupported_exactness_reply,
    unsupported_send_claim_reply,
)
from arelis.core.evidence import EvidenceLedger
from arelis.core.tool_subset import is_deep_dive_ask
from arelis.llm.router import ModelRole

_EVIDENCE_KINDS = frozenset(
    {
        "web",
        "weather",
        "recall",
        "inbox",
        "inbound_sms",
        "doc",
        "agenda",
        "git",
        "tasks",
        "analyze",
    }
)


_PROJECT_CONTEXT_SKILLS = frozenset({"workspace", "analyze", "docs", "document", "science"})
_PROJECT_CONTEXT_TOOLS = frozenset(
    {"workspace", "analyze", "git_info", "doc_extract", "plot", "document"}
)


def _wants_project_context(
    *,
    role: str,
    skill_ids: list[str] | tuple[str, ...] | set[str],
    expected_tools: set[str],
) -> bool:
    """True when the active-project system line is relevant this turn.

    Always injecting it on conversation follow-ups is how a missing last
    turn gets replaced by a guess about the interferometer root.
    """
    if (role or "").strip().lower() == "research":
        return True
    if _PROJECT_CONTEXT_SKILLS & set(skill_ids):
        return True
    return bool(expected_tools & _PROJECT_CONTEXT_TOOLS)


def disconnected_integration_reply(
    *,
    expected: set[str],
    available: set[str],
    want_sms: bool = False,
    want_mail: bool = False,
    want_calendar: bool = False,
) -> str | None:
    """Chat line when they asked for mail/SMS/calendar that is not connected.

    Returns None when those tools are registered, or when the turn also needs
    some other registered tool. Mixed work stays with the model.
    """
    integration = {"send_sms", "inbound_sms", "send_email", "inbox", "agenda"}
    if set(expected) - integration:
        return None
    if want_sms or expected & {"send_sms", "inbound_sms"}:
        needed = set()
        if want_sms or "send_sms" in expected:
            needed.add("send_sms")
        if "inbound_sms" in expected:
            needed.add("inbound_sms")
        if needed and not (needed & available):
            return (
                "I can't text until the phone is paired. "
                "Open Settings → Notify and scan the QR."
            )
    if want_mail or expected & {"send_email", "inbox"}:
        needed = set()
        if want_mail or "send_email" in expected:
            needed.add("send_email")
        if "inbox" in expected:
            needed.add("inbox")
        if needed and not (needed & available):
            return (
                "I can't send or read mail until an account is in Settings → Mail."
            )
    if want_calendar or "agenda" in expected:
        if "agenda" not in available:
            return (
                "I can't use the calendar until Google is connected. "
                "That's in Settings."
            )
    return None


def turn_expects_tool_round(
    *,
    skill_ids: list[str] | tuple[str, ...] | set[str],
    preflight_kinds: list[str] | tuple[str, ...] | set[str],
    research_mode: bool,
    expected_tools: set[str],
    exact_need: Any,
    wants_fresh_page: bool,
    active_plan: Any | None,
) -> bool:
    """Whether this turn should hold paint and hint 'call a tool first'.

    Separate from sending schemas. The unmatched web floor must be passed as
    empty ``skill_ids`` (see ``plan_ids`` in the loop) so "who is this" is
    not treated as a scrape.
    """
    kinds = getattr(exact_need, "kinds", ()) or ()
    return bool(
        skill_ids
        or preflight_kinds
        or research_mode
        or expected_tools
        or kinds
        or wants_fresh_page
        or active_plan is not None
    )


def should_offer_tools(
    *,
    chat_fast_path: bool,
    skill_ids: list[str] | tuple[str, ...] | set[str],
    preflight_kinds: list[str] | tuple[str, ...] | set[str],
    research_mode: bool,
    expected_tools: set[str],
    exact_need: Any,
    wants_fresh_page: bool,
    active_plan: Any | None,
) -> bool:
    """Whether this turn should send Ollama tool schemas.

    When ``chat_fast_path`` is on, pure social chat skips schemas. That used
    to help TTFT. After the full-prefix seed it does the opposite: the
    greeting overwrites the cache, and the next tool-bearing turn prefills
    ~18k tokens again. Shipped default is off. Any skill, preflight, plan,
    research mode, expected tool, or exactness warrant still re-arms tools
    when the flag is on.
    """
    if not chat_fast_path:
        return True
    return turn_expects_tool_round(
        skill_ids=skill_ids,
        preflight_kinds=preflight_kinds,
        research_mode=research_mode,
        expected_tools=expected_tools,
        exact_need=exact_need,
        wants_fresh_page=wants_fresh_page,
        active_plan=active_plan,
    )


_NEWS_FRESH_MARKERS = (
    "news",
    "latest",
    "headline",
    "article",
    "wsj",
    "what happened",
    "current events",
    "breaking",
)
_TODAY_NEWS = re.compile(
    r"(?i)\b(?:"
    r"(?:news|headlines?|happened|breaking|article).{0,24}today"
    r"|today.{0,24}(?:news|headlines?|happened|breaking)"
    r"|today'?s\s+(?:news|headlines?)"
    r")\b"
)


def wants_fresh_page_ask(text: str) -> bool:
    """True for a current-events ask — not every sentence that says 'today'."""
    raw = text or ""
    low = raw.lower()
    if any(marker in low for marker in _NEWS_FRESH_MARKERS):
        return True
    return bool(_TODAY_NEWS.search(raw))


def decide_mid_turn_escalate(
    *,
    role: str,
    text: str,
    round_i: int,
    expected: set[str],
    tools_used: set[str],
    already_escalated: bool,
    escalate_after_rounds: int = 2,
    enabled: bool = True,
) -> ModelRole | None:
    """Pure escalate decision (Wave 2). Returns target role or None."""
    if already_escalated or not enabled:
        return None
    if role != "fast":
        return None
    from arelis.core.agent_loop import _OUTBOUND_LOCK

    if _OUTBOUND_LOCK.search(text or ""):
        return None
    after = max(1, int(escalate_after_rounds))
    if round_i <= after:
        return None
    # IMPORTANT: never call is_research_mode("research", …) here — that forces
    # True because the role arg is hardcoded, so every turn after round 2 used
    # to escalate to 14B and pin ~10GB VRAM (agenda/calendar sessions).
    multi = bool(expected) or is_deep_dive_ask(text)
    if not multi:
        return None
    if expected & {
        "analyze",
        "weather",
        "send_sms",
        "send_email",
        "agenda",
        "image",
        "vision",
    } and "research_report" not in expected:
        return None
    if expected and (tools_used & expected):
        return None
    if not expected and tools_used:
        return None
    # Research-shaped asks win over bare "write" in FILE_ESCALATE (e.g. "write
    # a report" must escalate to research, not stay on a file-shaped miss).
    if "research_report" in expected or is_deep_dive_ask(text):
        return "research"
    if expected & {"web_search", "scrape", "web_fetch", "research_report"}:
        return "research"
    return None


def _exactness_finish_refuse(
    content: str,
    *,
    exact_need: Any,
    ledger: EvidenceLedger,
    numeric_gate: bool,
    evidence_gate: bool,
    send_path: bool = False,
) -> str | None:
    """Return a refusal when finishing would ship an unsupported exact claim."""
    # Side-effect honesty runs before refusal escape so hedge-then-claim
    # ("I don't know, but I sent…") cannot ship a fake send.
    if evidence_gate:
        send_missing = send_claim_missing_kinds(
            content,
            has_send_sms=ledger.has_ok("send_sms"),
            has_send_email=ledger.has_ok("send_email"),
        )
        if send_missing:
            return unsupported_send_claim_reply()
    if answer_looks_like_refusal(content):
        return None
    # Compose/send turns must not die on "no retrieved page warrant" (R4 / S10).
    if send_path:
        return None
    kinds = tuple(exact_need.kinds or ())
    if not kinds:
        return None
    missing = ledger.missing_kinds(kinds)
    if not numeric_gate:
        missing = [
            k
            for k in missing
            if k not in {"math", "symbolic", "units", "plot", "catalog", "document"}
        ]
    if not evidence_gate:
        missing = [k for k in missing if k not in _EVIDENCE_KINDS]
    if not missing:
        return None
    if "math" in missing:
        calc_fail = next(
            (w for w in ledger.items if w.kind == "calc" and not w.ok),
            None,
        )
        if calc_fail is not None:
            return unsupported_exactness_reply(
                missing, calc_failed=True, calc_detail=calc_fail.span
            )
    if "symbolic" in missing:
        cas_fail = next(
            (w for w in ledger.items if w.kind == "cas" and not w.ok),
            None,
        )
        if cas_fail is not None:
            return unsupported_exactness_reply(
                missing, cas_failed=True, cas_detail=cas_fail.span
            )
    if "units" in missing:
        units_fail = next(
            (w for w in ledger.items if w.kind == "units" and not w.ok),
            None,
        )
        if units_fail is not None:
            return unsupported_exactness_reply(
                missing, units_failed=True, units_detail=units_fail.span
            )
    if "plot" in missing:
        plot_fail = next(
            (w for w in ledger.items if w.kind == "plot" and not w.ok),
            None,
        )
        if plot_fail is not None:
            return unsupported_exactness_reply(
                missing, plot_failed=True, plot_detail=plot_fail.span
            )
    if "catalog" in missing:
        catalog_fail = next(
            (w for w in ledger.items if w.kind == "catalog" and not w.ok),
            None,
        )
        if catalog_fail is not None:
            return unsupported_exactness_reply(
                missing, catalog_failed=True, catalog_detail=catalog_fail.span
            )
    if "document" in missing:
        document_fail = next(
            (w for w in ledger.items if w.kind == "document" and not w.ok),
            None,
        )
        if document_fail is not None:
            return unsupported_exactness_reply(
                missing, document_failed=True, document_detail=document_fail.span
            )
    return unsupported_exactness_reply(missing)


def _answer_has_quote_span(text: str) -> bool:
    """True when the answer includes a non-empty quoted span (ASCII or curly)."""
    return bool(re.search(r'"[^"\n]{3,}"|“[^”\n]{3,}”', text or ""))


_EMPTY_REPLY_NOTICE = (
    "The model returned an empty reply. That usually means the context was "
    "exhausted or the model was unloaded mid-turn. Try a narrower ask, or check "
    "that Ollama is still running."
)

_ROUND_LIMIT_NOTICE = "I hit the tool-step limit before finishing. Try a narrower ask."

# Sent when a model announces a call in prose rather than making one. Observed
# from qwen2.5:7b: "Let's start by reading the file:" then a fenced JSON object,
# then "Once I've read it I'll summarize". Nothing runs, and the JSON is what
# the user ends up reading.
#
# The wording is load-bearing and was arrived at by measurement. An earlier
# version offered "or answer directly from what you already know", and the model
# took that option and invented a summary of a file it had never opened, which
# is a worse failure than the one being corrected. Another phrasing left it
# asking which repository the README belonged to. So the notice now quotes the
# exact call back, gives no alternative, and names invention as the thing not to
# do.
_MALFORMED_CALL_NOTICE = (
    "You printed a tool call as text, so nothing ran and you have no result to "
    "work from. The call you meant was `{tool}` with arguments {args}. Make that "
    "exact call through the tool interface now. Do not print JSON, do not restate "
    "the plan, and do not answer from memory: you have not seen that content yet, "
    "so any summary of it would be invented."
)

# What the model is told when the user declines a call. The wording matters more
# than it looks. A bare "user skipped tool X" reads as "you lack permission", and
# models respond by apologizing, refusing to use tools for the rest of the
# session, and suggesting the user run a shell command instead. This says what
# actually happened and what is still allowed.
_SKIP_NOTICE = (
    "The user declined this specific `{tool}` call. This is not a permissions "
    "error and the tool is still available. Either propose a different call, or "
    "ask what they would prefer. Do not tell the user to run commands themselves, "
    "and do not claim the change was made."
)


def _format_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role") or "?")
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _parse_summary_response(text: str) -> tuple[str, list[str]]:
    """Pull SUMMARY and FACTS out of the model reply.

    Tolerates missing labels and a bare paragraph: a failed parse must still
    yield something injectable rather than discarding the whole compression.
    Proposed facts are filtered hard: 7B compress passes otherwise dump the
    whole transcript into the History review queue.
    """
    cleaned = text.strip()
    if not cleaned:
        return "", []

    summary = ""
    facts: list[str] = []
    section: str | None = None
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("SUMMARY:"):
            section = "summary"
            summary = line.split(":", 1)[1].strip()
            continue
        if upper.startswith("FACTS:"):
            section = "facts"
            remainder = line.split(":", 1)[1].strip()
            if remainder:
                _append_fact(facts, remainder)
            continue
        if section == "summary":
            summary = f"{summary} {line}".strip() if summary else line
        elif section == "facts":
            _append_fact(facts, line.lstrip("- ").strip())
        elif section is None:
            # Model ignored the form and wrote a paragraph. Use it as the summary.
            summary = f"{summary} {line}".strip() if summary else line

    from arelis.core.agent_loop import _MAX_PROPOSED_FACTS, _MAX_SUMMARY_CHARS

    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return summary, facts[:_MAX_PROPOSED_FACTS]


def _append_fact(facts: list[str], raw: str) -> None:
    text = raw.strip().lstrip("- ").strip()
    if not text or text.upper() == "NONE":
        return
    if not _looks_like_durable_fact(text):
        return
    if text not in facts:
        facts.append(text)


_TRANSIENT_FACT_MARKERS = (
    "asked",
    "discussed",
    "talked about",
    "mentioned that",
    "wants me to",
    "wants you to",
    "this turn",
    "this chat",
    "this conversation",
    "just said",
    "is working on",
    "is trying to",
    "looking at",
    "opened ",
    "wrote ",
    "read ",
    "searched ",
    "tool ",
    "confirm",
    # Draft / send / exactness refuse crumbs (U8).
    "email draft",
    "draft email",
    "draft reply",
    "subject:",
    "send_email",
    "send_sms",
    "text my ",
    "sms to",
    "don't know",
    "do not know",
    "no retrieved",
    "without a warrant",
    "exactness",
    "i don't have",
    "refuse",
)


def _tool_fail_fingerprint(name: str, args: dict[str, Any] | None) -> str:
    """Stable key for identical tool+args failures within a turn (K2)."""
    try:
        payload = json.dumps(args or {}, sort_keys=True, default=str)
    except TypeError:
        payload = repr(args)
    return f"{name}|{payload}"


def _looks_like_durable_fact(text: str) -> bool:
    """Reject transcript crumbs that 7B models label as FACTS."""
    cleaned = " ".join(text.split())
    if len(cleaned) < 8 or len(cleaned) > 200:
        return False
    lower = cleaned.lower()
    if lower in {"none", "n/a", "na", "nothing", "no facts"}:
        return False
    if cleaned.endswith("?"):
        return False
    if lower.startswith(("user:", "assistant:", "system:", "tool:")):
        return False
    if any(marker in lower for marker in _TRANSIENT_FACT_MARKERS):
        return False
    # Prefer statements about the person / standing projects, not chat meta.
    durable_hints = (
        "user ",
        "prefers",
        "prefer ",
        "works ",
        "is a ",
        "lives ",
        "studies",
        "climbs",
        "builds ",
        "owns ",
        "uses ",
        "always ",
        "never ",
        "allergic",
        "timezone",
        "located",
    )
    # Require a durable cue. Chatty compress models otherwise invent a fact
    # for every turn; History is a review queue, not a transcript dump.
    return any(hint in lower for hint in durable_hints)


def _append_sources(answer: str, sources: list[tuple[str, str]]) -> str:
    """Guarantee a Sources list whenever the web was actually used.

    The persona and tool policy both promise citations, but a prompt cannot
    enforce one. These entries come from tool results, so the list can only ever
    contain pages that really loaded at their post-redirect URL. If the model
    already wrote its own Sources section, leave it alone. Only http(s) URLs
    are kept so STATUS / notify copy can never appear as a citation (R6).
    """
    if not sources:
        return answer
    if "sources:" in answer.lower():
        return answer
    if answer_looks_like_refusal(answer):
        return answer
    clean: list[tuple[str, str]] = []
    for title, url in sources:
        u = (url or "").strip()
        t = (title or "").strip()
        if t.lower().startswith("inbound notify") or u.lower().startswith("inbound notify"):
            continue
        if not (u.startswith("http://") or u.startswith("https://")):
            continue
        clean.append((t, u))
    if not clean:
        return answer
    lines = ["", "**Sources:**"]
    for i, (title, url) in enumerate(clean, start=1):
        lines.append(f"{i}. {title} ({url})" if title else f"{i}. {url}")
    return answer + "\n" + "\n".join(lines)
