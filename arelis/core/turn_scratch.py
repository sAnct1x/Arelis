"""The state one model/tool round rebinds, as one object.

``run_round`` fills a ``RoundScratch`` from the ``TurnContext``, then
``apply_no_call_path`` and ``dispatch_calls`` coordinate on it while the
step tables in ``no_call_steps`` / ``no_call_finish`` / ``call_redirects``
read and write fields on it by name.

It exists because those fields are *rebound*, not just mutated: a nudge
that takes the tool schemas away assigns a new ``ollama_tools`` list, and
a redirect assigns a narrowed ``available`` set. Plain locals meant every
coordinator had to unpack ~40 names on entry and copy them back in a
``finally`` so an early return or a raised ``_StoppedError`` still handed
them to the next stage. Writing through one object is that contract.

``slots=True`` is load-bearing rather than a size tweak. The scratch was a
``SimpleNamespace``, so ``r.ollama_tolls = []`` was a new attribute and a
silently dropped write — on this object it raises.

This is a separate module because ``turn_round`` imports ``turn_dispatch``,
so the shared type cannot live in either one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from arelis.core.claims import ExactnessNeed
from arelis.core.evidence import EvidenceLedger
from arelis.core.turn_context import TurnContext


@dataclass(slots=True, kw_only=True)
class RoundScratch:
    """One round's rebindable state. Mutable on purpose.

    ``role`` and ``model`` are deliberately absent. The SimpleNamespace
    carried both and no step ever read either: they were unpacked and
    copied back 39 lines later and that was their whole life. ``run_round``
    keeps them as locals, which is where they are actually used.
    """

    text: str
    agent_cfg: dict[str, Any]

    # The tool surface. ``tool_names`` is the same object as
    # ``ctx.tool_names`` — callers clear/update it in place — while
    # ``available`` / ``visible`` get replaced outright by a redirect.
    available_all: set[str]
    available: set[str]
    visible: set[str]
    tool_names: set[str]
    offer_tools: bool
    ollama_tools: list[dict[str, Any]]

    # Warrants and the gates that read them.
    sources: list[tuple[str, str]]
    ledger: EvidenceLedger
    exact_need: ExactnessNeed
    numeric_gate: bool
    evidence_gate: bool
    research_dual: bool
    research_min_sources: int
    research_mode: bool

    # Per-turn budgets and duplicate-call keys.
    fail_counts: dict[str, int]
    skip_counts: dict[str, int]
    web_search_ok: set[str]
    page_ok: set[str]
    sms_sent: set[str]
    agenda_created: set[str]
    weather_ok_places: set[str]
    weather_days_retried: set[str]

    # Intent carried in from preflight.
    messages: list[dict[str, Any]]
    preflight_kinds: list[str]
    wants_fresh_page: bool
    active_room: Any
    sms_preinject: dict[str, Any] | None
    sms_draft: Any
    email_draft: Any
    agenda_draft: Any

    # What this round produced.
    content: str
    streamed: str
    calls: list[tuple[str, dict[str, Any]]]
    tool_calls: list[dict[str, Any]]
    round_ms: int
    # Same one-shot as sms_preinject. Defaulted so a scratch built by a
    # caller that lists fields by name still constructs; run_round passes it.
    weather_preinject: dict[str, Any] | None = None
    agenda_preinject: dict[str, Any] | None = None
    # Open or a today/tomorrow/list read returned ok this turn. Create,
    # delete, and close do not set it. Defaulted like the one-shots above.
    agenda_open_read_ok: bool = False
    # Same one-shot as the drafts above. A successful calculator call sets
    # calculator_ok. Units and the CAS do not.
    calculator_preinject: dict[str, Any] | None = None
    calculator_ok: bool = False
    # Same one-shot. A successful units call sets units_ok.
    units_preinject: dict[str, Any] | None = None
    units_ok: bool = False
    # Same one-shot as sms_preinject. Defaulted so a scratch built by a
    # caller that lists fields by name still constructs; run_round passes it.
    email_preinject: dict[str, Any] | None = None
    # Same one-shot. A successful browser call sets browser_ok. A sign-in
    # line that has not clicked yet does not: try_browser_signin still
    # needs a later round.
    browser_preinject: dict[str, Any] | None = None
    browser_ok: bool = False
    # Same one-shot. A successful tile call sets tile_ok. Calendar stays
    # on agenda when that tool is registered, so this stays unset.
    tile_preinject: dict[str, Any] | None = None
    tile_ok: bool = False
    # Same one-shot. A successful workspace read sets inspect_ok.
    # A write or an edit does not.
    workspace_preinject: dict[str, Any] | None = None
    inspect_ok: bool = False
    # Same one-shot. A successful run_script call sets run_script_ok.
    # A match with no named .py stays unset.
    run_script_preinject: dict[str, Any] | None = None
    run_script_ok: bool = False


FIELD_NAMES: tuple[str, ...] = tuple(RoundScratch.__dataclass_fields__)


def strip_tool_schemas(ctx: TurnContext, r: RoundScratch) -> None:
    """Take the tool array away for the rest of the turn.

    Every caller is a "you already ran the tool, now write the chat line"
    nudge. Both copies have to move: the round still reads ``r`` for this
    pass, and the next round rebuilds from ``ctx``. Leaving either one
    populated is how a 7B re-emits the same call until the round cap.
    """
    r.offer_tools = False
    r.ollama_tools = []
    ctx.offer_tools = False
    ctx.ollama_tools = []
    ctx.tool_names.clear()
    r.tool_names = ctx.tool_names


# A tool the user asks for by verb rather than by name. "remember that result as my
# weekly distance" never says "memory".
_OWED_TOOL_VERBS: dict[str, re.Pattern[str]] = {
    "memory": re.compile(r"\bremember\s+(?:that|this|it|the|my)\b"),
}


def named_tools_owed(loop: Any, ctx: TurnContext) -> list[str]:
    """Tools the user named in the ask that have not run yet this turn.

    ``exact_need.kinds`` only knows the exactness tools (units, calculator,
    weather, ...). "convert with units, then calculator, then remember it" owes
    ``memory`` and ``document`` chains that no kind covers, so the first success
    stripped the tool array and the rest of the chain never ran. A tool is owed
    when its name is a whole word in the text, it is on this turn's menu, and it
    has not succeeded. ``max_rounds`` still bounds a model that will not call it.
    """
    text = (ctx.text or "").lower()
    owed: list[str] = []
    for name in sorted(ctx.available_all):
        if name in loop.tools_used:
            continue
        spoken = name.replace("_", " ")
        pattern = _OWED_TOOL_VERBS.get(name)
        if (
            re.search(rf"\b{re.escape(spoken)}\b", text)
            or ("_" in name and re.search(rf"\b{re.escape(name)}\b", text))
            or (pattern is not None and pattern.search(text))
        ):
            owed.append(name)
    return owed


def named_tools_owed_runnable(
    loop: Any, ctx: TurnContext, fail_counts: dict[str, int]
) -> list[str]:
    """``named_tools_owed`` minus tools that already failed twice this turn.

    Same fingerprint rule as confirm/execute: after two identical failures the
    tool is not runnable again, so it must not block finishing the turn.
    """
    out: list[str] = []
    for name in named_tools_owed(loop, ctx):
        prefix = f"{name}|"
        if any(count >= 2 and fp.startswith(prefix) for fp, count in fail_counts.items()):
            continue
        out.append(name)
    return out
