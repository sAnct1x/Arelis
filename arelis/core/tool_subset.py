"""Per-turn tool schema filtering.

Small local models choke when every tool schema rides every turn. Two layers:

- Research mode keeps a focused allowlist (deep-dive / 14B context budget).
- Everyday turns offer tools for the skill cards that matched, plus any
  preflight expected tools. Unmatched turns fail open (full registry).

SMS/email/calendar-outbound asks keep the full registry so send tools stay
callable. This module never skips Allow.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from arelis.core.intent_catalog import (
    FULL_SURFACE_KINDS,
    RESEARCH,
    must_keep_full_surface_text,
    research_extras_for_text,
)
from arelis.core.preflight import detect_intents
from arelis.core.skills import (
    select_skill_ids_detailed,
    sms_negative_hit,
)

# Core research surface. Always included when the research subset is active.
RESEARCH_TOOL_ALLOWLIST = frozenset(
    {
        "research_report",
        "web_search",
        "scrape",
        "web_fetch",
        "calculator",
        "recall",
        "weather",
        "user_location",
    }
)

# Tiny schemas that exactness still needs when a turn otherwise shrinks.
ALWAYS_ON_TOOLS = frozenset({"calculator"})

# Fail-open unmatched chat used to keep these. The 7B then replayed the last
# SMS draft (grocery to wife) on "how are you today?".
OUTBOUND_SEND_TOOLS = frozenset({"send_sms", "send_email"})

# Skill card id → tools the model should see. Broader than requires_tool so
# sibling tools (inbound_sms with sms, git_info with workspace) stay callable.
SKILL_TOOLS: dict[str, frozenset[str]] = {
    "web": frozenset({"web_search", "scrape", "web_fetch"}),
    "weather": frozenset({"weather", "user_location", "web_fetch"}),
    "location": frozenset({"user_location", "weather"}),
    "sms": frozenset({"send_sms", "inbound_sms", "contacts"}),
    "contacts": frozenset({"contacts"}),
    "email": frozenset({"inbox", "send_email"}),
    "workspace": frozenset({"workspace", "git_info"}),
    "memory": frozenset({"recall", "memory", "tasks"}),
    "goals": frozenset({"goals"}),
    "attention": frozenset({"tasks", "goals", "agenda"}),
    "analyze": frozenset({"analyze", "workspace"}),
    "docs": frozenset({"doc_extract"}),
    "attachments": frozenset(
        {"vision", "ocr", "doc_extract", "analyze", "workspace"}
    ),
    "calculator": frozenset({"calculator"}),
    "clipboard": frozenset({"clipboard"}),
    "ocr": frozenset({"ocr"}),
    "agenda": frozenset({"agenda"}),
    "schedule": frozenset({"schedule"}),
    "image": frozenset({"image"}),
    "vision": frozenset({"vision", "camera", "ocr"}),
    "browser": frozenset({"browser"}),
    "research": frozenset(
        {"research_report", "web_search", "scrape", "web_fetch", "calculator"}
    ),
    "deadline": frozenset({"tasks", "agenda"}),
}


def is_deep_dive_ask(text: str) -> bool:
    return RESEARCH.matches(text)


def is_research_mode(role: str, text: str) -> bool:
    """True for research role or deep-dive language."""
    if (role or "").strip().lower() == "research":
        return True
    return is_deep_dive_ask(text)


def _extras_for_text(text: str) -> set[str]:
    return research_extras_for_text(text)


def _must_keep_full_surface(
    text: str,
    history: list[Any] | None = None,
) -> bool:
    """True when hiding tools could drop a send/calendar mutate."""
    kinds = {h.kind for h in detect_intents(text, history=history)}
    if sms_negative_hit(text or ""):
        kinds -= {"sms_send", "inbound_sms", "sms"}
    if kinds & FULL_SURFACE_KINDS:
        return True
    return must_keep_full_surface_text(text)


def should_apply_research_subset(
    role: str,
    text: str,
    *,
    history: list[Any] | None = None,
) -> bool:
    """Whether this turn should shrink the tool schemas for research mode."""
    if not is_research_mode(role, text):
        return False
    if _must_keep_full_surface(text, history):
        return False
    return True


def tools_for_skill_ids(skill_ids: Iterable[str]) -> set[str]:
    """Union of tools offered for the selected skill cards."""
    out: set[str] = set()
    for skill_id in skill_ids:
        out |= SKILL_TOOLS.get(skill_id, frozenset())
    return out


def _skill_subset(
    available: set[str],
    text: str,
    *,
    history: list[Any] | None = None,
    skill_ids: Iterable[str] | None = None,
) -> set[str]:
    """Shrink to skill + preflight tools, or return *available* when unsure."""
    expected: set[str] = set()
    veto_sms = sms_negative_hit(text or "")
    for hint in detect_intents(text, history=history):
        if veto_sms and hint.kind in {"sms_send", "inbound_sms", "sms"}:
            continue
        expected.update(hint.expected_tools)
    if skill_ids is not None:
        ids = list(skill_ids)
        fallback_only = False
    else:
        ids, fallback_only = select_skill_ids_detailed(
            text, available_tools=available
        )
    if not ids and not expected:
        return _without_unauthorized_sends(set(available), text, expected)
    # The web fallback is a floor on the prompt, not a menu. Treating it as one
    # left local asks with {calculator, scrape, web_fetch, web_search}, so a
    # repo question had no git_info to call and a file path went to web_fetch.
    if fallback_only and not expected:
        return _without_unauthorized_sends(set(available), text, expected)
    allow = set(ALWAYS_ON_TOOLS)
    allow |= tools_for_skill_ids(ids)
    allow |= expected
    allow |= _extras_for_text(text)
    visible = {n for n in available if n in allow}
    # Empty intersection means the mapping lagged a new tool — fail open
    # for reads, never for outbound sends.
    if not visible:
        visible = set(available)
    return _without_unauthorized_sends(visible, text, expected)


def _without_unauthorized_sends(
    visible: set[str], text: str, expected: set[str]
) -> set[str]:
    """Outbound send tools require this utterance (or preflight) to ask."""
    from arelis.core.sms_complete import sms_intent_this_turn

    out = set(visible)
    if "send_sms" in out and "send_sms" not in expected and not sms_intent_this_turn(
        text
    ):
        out.discard("send_sms")
    if "send_email" in out and "send_email" not in expected:
        kinds = {h.kind for h in detect_intents(text)}
        if not (kinds & {"email_send", "inbox", "email"}):
            out.discard("send_email")
    return out


def filter_tool_names(
    available: set[str],
    *,
    role: str,
    text: str,
    enabled: bool = True,
    skill_subset: bool = True,
    history: list[Any] | None = None,
    skill_ids: Iterable[str] | None = None,
) -> set[str]:
    """Return the tool names the model may see this turn.

    ``enabled`` is the research-mode allowlist. ``skill_subset`` is the
    everyday skill-card menu. Outbound SMS/email keeps the full registry.
    Unmatched everyday turns fail open. Research-mode shrinking, when it
    applies, is unchanged from the original allowlist.
    """
    names = set(available)
    if not enabled and not skill_subset:
        return names
    if _must_keep_full_surface(text, history):
        expected = {
            t
            for hint in detect_intents(text, history=history)
            for t in hint.expected_tools
        }
        return _without_unauthorized_sends(names, text, expected)
    if enabled and should_apply_research_subset(role, text, history=history):
        allow = set(RESEARCH_TOOL_ALLOWLIST) | _extras_for_text(text)
        return {n for n in names if n in allow}
    if not skill_subset:
        return names
    return _skill_subset(
        names, text, history=history, skill_ids=skill_ids
    )
