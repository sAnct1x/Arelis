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
