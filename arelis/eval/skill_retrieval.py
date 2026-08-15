"""Paraphrase scoreboard for skill-card retrieval (pure function, no model).

Canonical foundation scenarios already use the phrases the hints were written
for. This table catches misses and false positives that hide tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arelis.core.skills import select_skill_ids
from arelis.core.tool_subset import RESEARCH_TOOL_ALLOWLIST, filter_tool_names

EVERYDAY_TOOLS: frozenset[str] = frozenset(RESEARCH_TOOL_ALLOWLIST) | {
    "send_sms",
    "inbound_sms",
    "contacts",
    "inbox",
    "send_email",
    "image",
    "vision",
    "camera",
    "ocr",
    "browser",
    "workspace",
    "git_info",
    "analyze",
    "doc_extract",
    "agenda",
    "memory",
    "tasks",
    "goals",
    "schedule",
    "clipboard",
}


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    user: str
    must_include: tuple[str, ...] = ()
    must_exclude: tuple[str, ...] = ()
    must_offer_tools: tuple[str, ...] = ()
    must_hide_tools: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class RetrievalCaseResult:
    case_id: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    precision: float = 0.0
    recall: float = 0.0


RETRIEVAL_CASES: tuple[RetrievalCase, ...] = (
    RetrievalCase(
        id="deadline_she_owe",
        user="what's she owe",
        must_include=("deadline",),
        must_offer_tools=("tasks", "agenda"),
        must_hide_tools=("send_sms",),
        notes="Paraphrase of 'what do i owe'; must not fail-open-only.",
    ),
    RetrievalCase(
        id="ocr_screenshot_text_not_sms",
        user="read the text in this screenshot",
        must_include=("ocr",),
        must_exclude=("sms",),
        must_offer_tools=("ocr",),
        must_hide_tools=("send_sms",),
        notes="Bare 'text' must not pull SMS or keep the send surface.",
    ),
    RetrievalCase(
        id="look_read_to_me_not_sms",
        user="look at the camera and read this to me",
        must_include=("ocr",),
        must_exclude=("sms",),
        must_offer_tools=("ocr",),
        must_hide_tools=("send_sms",),
        notes="Point-and-Ask Read must not keep the send surface.",
    ),
    RetrievalCase(
        id="look_freshness_not_sms",
        user="look at the webcam — is this still good?",
        must_include=("vision",),
        must_exclude=("sms",),
        must_offer_tools=("vision", "camera"),
        must_hide_tools=("send_sms",),
        notes="Freshness look selects vision; must not fail-open to SMS.",
    ),
    RetrievalCase(
        id="sms_later_not_schedule",
        user="I'll text Brian later",
        must_include=("sms",),
        must_exclude=("schedule",),
        must_offer_tools=("send_sms",),
        notes="Send keep-full-surface is OK; 'later' must not select schedule.",
    ),
    RetrievalCase(
        id="multi_intent_four_cards",
        user="search the news, text Brian, recall what I said, analyze sales.csv table",
        must_include=("web", "sms", "memory", "analyze"),
        notes="max_cards=4 must keep all four needed cards.",
    ),
    RetrievalCase(
        id="weather_canonical",
        user="What's the weather today?",
        must_include=("weather",),
        must_offer_tools=("weather",),
        must_hide_tools=("send_sms", "image", "browser"),
    ),
    RetrievalCase(
        id="sms_canonical",
        user="Text Brian: I'm late",
        must_include=("sms",),
        must_offer_tools=("send_sms",),
    ),
    RetrievalCase(
        id="inbox_canonical",
        user="What's in my inbox from Alice?",
        must_include=("email",),
        must_offer_tools=("inbox", "send_email"),
        must_hide_tools=("image", "browser"),
    ),
    RetrievalCase(
        id="git_canonical",
        user="What's the git status of this project?",
        must_include=("workspace",),
        must_offer_tools=("git_info", "workspace"),
        must_hide_tools=("send_sms", "image"),
    ),
    RetrievalCase(
        id="text_file_not_sms",
        user="write a text file called notes.txt",
        must_include=("workspace",),
        must_exclude=("sms",),
        must_offer_tools=("workspace",),
        must_hide_tools=("send_sms",),
    ),
)


def _precision_recall(selected: list[str], relevant: tuple[str, ...]) -> tuple[float, float]:
    retrieved = set(selected)
    need = set(relevant)
    if not need:
        return 1.0, 1.0
    hit = need & retrieved
    precision = len(hit) / len(retrieved) if retrieved else 0.0
    recall = len(hit) / len(need)
    return precision, recall


def evaluate_retrieval_case(
    case: RetrievalCase,
    *,
    available_tools: set[str] | None = None,
) -> RetrievalCaseResult:
    tools = set(available_tools) if available_tools is not None else set(EVERYDAY_TOOLS)
    ids = select_skill_ids(case.user, available_tools=tools)
    reasons: list[str] = []
    for sid in case.must_include:
        if sid not in ids:
            reasons.append(f"missing skill {sid!r} (got {ids})")
    for sid in case.must_exclude:
        if sid in ids:
            reasons.append(f"unexpected skill {sid!r} (got {ids})")
    if case.must_offer_tools or case.must_hide_tools:
        visible = filter_tool_names(
            tools,
            role="fast",
            text=case.user,
            enabled=True,
            skill_subset=True,
        )
        for name in case.must_offer_tools:
            if name not in visible:
                reasons.append(f"missing tool {name!r}")
        for name in case.must_hide_tools:
            if name in visible:
                reasons.append(f"tool not hidden {name!r}")
    precision, recall = _precision_recall(ids, case.must_include)
    return RetrievalCaseResult(
        case_id=case.id,
        ok=not reasons,
        reasons=reasons,
        skill_ids=ids,
        precision=precision,
        recall=recall,
    )


def run_retrieval_board(
    cases: tuple[RetrievalCase, ...] = RETRIEVAL_CASES,
) -> dict[str, Any]:
    """Evaluate every case; return a JSON-ready scorecard block."""
    results = [evaluate_retrieval_case(c) for c in cases]
    passed = sum(1 for r in results if r.ok)
    precisions = [r.precision for r in results]
    recalls = [r.recall for r in results]
    fp = 0
    fp_denom = 0
    for case, result in zip(cases, results, strict=True):
        for sid in case.must_exclude:
            fp_denom += 1
            if sid in result.skill_ids:
                fp += 1
    macro_p = sum(precisions) / len(precisions) if precisions else 0.0
    macro_r = sum(recalls) / len(recalls) if recalls else 0.0
    return {
        "passed": passed,
        "total": len(results),
        "macro_precision": round(macro_p, 3),
        "macro_recall": round(macro_r, 3),
        "false_positive_rate": round(fp / fp_denom, 3) if fp_denom else 0.0,
        "cases": [
            {
                "id": r.case_id,
                "ok": r.ok,
                "skill_ids": r.skill_ids,
                "precision": round(r.precision, 3),
                "recall": round(r.recall, 3),
                "reasons": r.reasons,
            }
            for r in results
        ],
    }
