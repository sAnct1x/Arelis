"""Per-turn state that used to be ~45 locals inside AgentLoop._run.

Those locals were the reason _run could not be split: prepare, each round,
verify and finish all closed over the same names, so extracting a method
meant a 20-argument signature that immediately grew. One object is the
split. Nothing here survives the turn — AgentLoop still owns the timer,
the look grant and the expected-tool set, because other methods already
read those.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arelis.core.claims import ExactnessNeed
from arelis.core.evidence import EvidenceLedger
from arelis.llm.router import ModelRole


@dataclass
class TurnContext:
    """Everything one user turn mutates, besides the loop's own fields."""

    text: str
    role: ModelRole
    speak: bool = False
    research_mode: bool = False
    agent_cfg: dict[str, Any] = field(default_factory=dict)

    available_all: set[str] = field(default_factory=set)
    available: set[str] = field(default_factory=set)
    visible: set[str] = field(default_factory=set)
    tool_names: set[str] = field(default_factory=set)

    messages: list[dict[str, Any]] = field(default_factory=list)
    skill_ids: tuple[str, ...] = ()
    preflight_kinds: list[str] = field(default_factory=list)

    sources: list[tuple[str, str]] = field(default_factory=list)
    ledger: EvidenceLedger = field(default_factory=EvidenceLedger)
    exact_need: ExactnessNeed = field(
        default_factory=lambda: ExactnessNeed(
            False, False, False, False
        )
    )

    numeric_gate: bool = True
    evidence_gate: bool = True
    research_dual: bool = True
    research_min_sources: int = 2
    wants_fresh_page: bool = False
    offer_tools: bool = True
    ollama_tools: list[dict[str, Any]] = field(default_factory=list)
    fallback_mode: bool = False
    allow_writes_this_turn: bool = False
    nudges: int = 0

    sms_draft: Any = None
    email_draft: Any = None
    agenda_draft: Any = None
    skip_sms_draft: bool = False
    active_room: Any = None
    sms_preinject: dict[str, Any] | None = None
    active_plan: Any = None

    scrape_nudge_used: bool = False
    js_shell_nudge_used: bool = False
    js_shell_url: str = ""
    plan_progress_used: bool = False
    sms_nudge_used: int = 0
    email_nudge_used: int = 0
    image_nudge_used: int = 0
    vision_nudge_used: int = 0
    agenda_nudge_used: int = 0
    math_nudge_used: bool = False
    cas_nudge_used: bool = False
    units_nudge_used: bool = False
    plot_nudge_used: bool = False
    catalog_nudge_used: bool = False
    document_nudge_used: bool = False
    diagnostics_nudge_used: bool = False
    weather_nudge_used: int = 0
    weather_ok_places: set[str] = field(default_factory=set)
    weather_days_retried: set[str] = field(default_factory=set)
    schedule_managed_ok: bool = False
    image_attempted: bool = False
    memory_nudge_used: int = 0
    last_ok_tool_out: str = ""
    last_ok_tool_name: str = ""
    inbox_mutated_ok: bool = False
    inbox_empty_ok: bool = False
    last_browser_snapshot: str = ""
    browser_clicked: bool = False
    skip_finish_text: str = ""
    agenda_create_ok: bool = False
    evidence_nudge_used: bool = False
    quote_nudge_used: bool = False
    dual_hit_nudge_used: bool = False
    file_answer_nudge_used: bool = False
    browser_relaunch_nudge_used: bool = False
    sms_sent: set[str] = field(default_factory=set)
    sms_failed: bool = False
    email_sent_ok: bool = False
    agenda_created: set[str] = field(default_factory=set)
    fail_counts: dict[str, int] = field(default_factory=dict)
    skip_counts: dict[str, int] = field(default_factory=dict)
    web_search_ok: set[str] = field(default_factory=set)
    page_ok: set[str] = field(default_factory=set)

    def is_send_path(self, expected_tools: set[str]) -> bool:
        """True when finishing on a compose/send turn must not die on web warrants."""
        return bool(
            (self.sms_draft is not None and self.sms_draft.complete)
            or (self.email_draft is not None and self.email_draft.complete)
            or "send_sms" in expected_tools
            or "send_email" in expected_tools
        )
