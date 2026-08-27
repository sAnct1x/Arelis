"""Which tools the model may see this turn.

Two jobs live here, and only one of them is still worth doing.

**Authorization** hides ``send_sms`` and ``send_email`` unless this utterance (or
preflight) actually asks to send. That is not an optimisation and does not care
how large the window is: fail-open chat once let the model replay the previous
SMS draft in answer to "how are you today?". ``_without_unauthorized_sends`` runs
on every path, including the full-surface one.

**Context economy** shrank the schema array to whichever tools the matched skill
cards implied. It was measured and it does not work. Ollama renders the tools
array near the front of the prompt, so an array that changes shape from turn to
turn changes the prefix, and a changed prefix cannot be reused — the persona, the
policy and the whole conversation behind it are prefilled again. On the reference
card (see scripts/measure_tool_surface_prefill.py):

    constant full surface, 34 tools    19,455 tokens   42.7s cold, then 3.2s
    subset changing each turn, 6 tools  ~9,700 tokens   16.9s, 17.3s, 17.3s

Half the tokens, five times the steady-state cost, because every turn pays a
fresh prefill. The saving was real when it was counted in tokens and imaginary
once the cache was involved.

So the default is now the whole registry. ``skill_tool_subset`` still exists for
anyone running a model that genuinely cannot choose among 34 tools, and the
research allowlist still exists for the deep-dive loop, but neither is on by
default and neither is load-bearing.

The one-off cost of a large constant prefix — around 40s of prefill on a cold
start — is paid at startup instead, by seed_prefix_cache in arelis/llm/startup.

This module never skips Allow.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from arelis.core.intent_catalog import (
    DIAGNOSTICS,
    FULL_SURFACE_KINDS,
    RESEARCH,
    is_tiny_prompt_ask,
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
        "python",
        "cas",
        "units",
        "recall",
        "weather",
        "user_location",
        "catalog",
    }
)

# Tiny schemas that exactness still needs when a turn otherwise shrinks.
ALWAYS_ON_TOOLS = frozenset({"calculator", "python", "cas", "units"})

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
    "document": frozenset({"document"}),
    "attachments": frozenset(
        {"vision", "ocr", "image_edit", "doc_extract", "analyze", "workspace"}
    ),
    "calculator": frozenset({"calculator", "python"}),
    "diagnostics": frozenset({"diagnostics"}),
    "science": frozenset(
        {"cas", "units", "calculator", "python", "plot", "analyze", "catalog", "solar"}
    ),
    "clipboard": frozenset({"clipboard"}),
    "ocr": frozenset({"ocr"}),
    "agenda": frozenset({"agenda"}),
    "schedule": frozenset({"schedule"}),
    "rooms": frozenset({"rooms", "workspace"}),
    "image": frozenset({"image"}),
    "image_edit": frozenset({"image_edit", "vision"}),
    "vision": frozenset({"vision", "camera", "ocr"}),
    "browser": frozenset({"browser"}),
    "research": frozenset(
        {
            "research_report",
            "web_search",
            "scrape",
            "web_fetch",
            "calculator",
            "python",
            "cas",
            "units",
            "plot",
            "catalog",
            "solar",
        }
    ),
    "deadline": frozenset({"tasks", "agenda"}),
    "tile": frozenset({"tile"}),
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
    from arelis.core.email_complete import looks_like_email_send_followup

    kinds = {h.kind for h in detect_intents(text, history=history)}
    if sms_negative_hit(text or ""):
        kinds -= {"sms_send", "inbound_sms", "sms"}
    if kinds & FULL_SURFACE_KINDS:
        return True
    if looks_like_email_send_followup(text, history):
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
    extra_skill_ids: Iterable[str] | None = None,
) -> set[str]:
    """Shrink to skill + preflight tools, or return *available* when unsure."""
    expected: set[str] = set()
    veto_sms = sms_negative_hit(text or "")
    for hint in detect_intents(text, history=history):
        if veto_sms and hint.kind in {"sms_send", "inbound_sms", "sms"}:
            continue
        expected.update(hint.expected_tools)
    extra = [sid for sid in (extra_skill_ids or ()) if sid]
    if skill_ids is not None:
        ids = list(skill_ids)
        fallback_only = False
    else:
        ids, fallback_only = select_skill_ids_detailed(
            text, available_tools=available, extra_ids=()
        )
    # now_line / hello / thanks already have the answer. Fail-open here is
    # how "what time is it" paid ~11k prompt tokens.
    if is_tiny_prompt_ask(text) and not expected:
        allow = set(ALWAYS_ON_TOOLS)
        allow |= tools_for_skill_ids(ids)
        allow |= tools_for_skill_ids(extra)
        visible = {n for n in available if n in allow}
        return _without_unauthorized_sends(visible, text, expected, history=history)
    if not ids and not expected:
        return _without_unauthorized_sends(set(available), text, expected, history=history)
    # The web fallback is a floor on the prompt, not a menu. Treating it as one
    # left local asks with {calculator, scrape, web_fetch, web_search}, so a
    # repo question had no git_info to call and a file path went to web_fetch.
    if fallback_only and not expected:
        return _without_unauthorized_sends(set(available), text, expected, history=history)
    allow = set(ALWAYS_ON_TOOLS)
    allow |= tools_for_skill_ids(ids)
    allow |= tools_for_skill_ids(extra)
    allow |= expected
    allow |= _extras_for_text(text)
    visible = {n for n in available if n in allow}
    # Empty intersection means the mapping lagged a new tool — fail open
    # for reads, never for outbound sends.
    if not visible:
        visible = set(available)
    return _without_unauthorized_sends(visible, text, expected, history=history)


def _without_unauthorized_sends(
    visible: set[str],
    text: str,
    expected: set[str],
    history: list[Any] | None = None,
) -> set[str]:
    """Outbound send tools require this utterance (or preflight) to ask."""
    from arelis.core.email_complete import (
        looks_like_email_send_followup,
        looks_like_mailbox_mutate,
    )
    from arelis.core.sms_complete import sms_intent_this_turn

    out = set(visible)
    if "send_sms" in out and "send_sms" not in expected and not sms_intent_this_turn(
        text
    ):
        out.discard("send_sms")
    if "send_email" in out and "send_email" not in expected:
        if looks_like_mailbox_mutate(text):
            out.discard("send_email")
        elif looks_like_email_send_followup(text, history):
            pass
        else:
            kinds = {h.kind for h in detect_intents(text, history=history)}
            if not (kinds & {"compose_email", "inbox", "email"}):
                out.discard("send_email")
    if "diagnostics" in out and not DIAGNOSTICS.matches(text):
        out.discard("diagnostics")
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
    extra_skill_ids: Iterable[str] | None = None,
) -> set[str]:
    """Return the tool names the model may see this turn.

    ``enabled`` is the research-mode allowlist and ``skill_subset`` the everyday
    skill-card menu; both default to off in the shipped config, so the normal
    answer is the whole registry minus any send the turn has not asked for.
    Shrinking either way still never removes a send the turn *did* ask for, and
    never skips Allow.
    """
    names = set(available)
    extra = set(tools_for_skill_ids(extra_skill_ids or ()))
    if not enabled and not skill_subset:
        # The full surface still owes the authorization filter. Skipping it here
        # is what let a stale SMS draft ride an unrelated turn.
        expected = {
            t
            for hint in detect_intents(text, history=history)
            for t in hint.expected_tools
        }
        return _without_unauthorized_sends(names, text, expected, history=history)
    if _must_keep_full_surface(text, history):
        expected = {
            t
            for hint in detect_intents(text, history=history)
            for t in hint.expected_tools
        }
        return _without_unauthorized_sends(names, text, expected, history=history)
    if enabled and should_apply_research_subset(role, text, history=history):
        allow = set(RESEARCH_TOOL_ALLOWLIST) | _extras_for_text(text) | extra
        return {n for n in names if n in allow}
    if not skill_subset:
        if "diagnostics" in names and not DIAGNOSTICS.matches(text):
            names.discard("diagnostics")
        return names
    return _skill_subset(
        names,
        text,
        history=history,
        skill_ids=skill_ids,
        extra_skill_ids=extra_skill_ids,
    )
