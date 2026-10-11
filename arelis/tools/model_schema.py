"""Parameters the model is shown, as one fixed trim.

The source ``parameters_schema`` stays the contract. Tools still accept every
argument, and the strict argument check still reads the full source schema, so
a hidden argument the model does send is honoured. Only the tools array
shrinks. ``MODEL_HIDDEN_PARAMS`` is a module constant: no per-turn filtering,
so the startup warmup schema stays byte-identical to every turn.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

# Aliases the tool already reads, paging and size knobs, single-value enums,
# and expert knobs no routing text or skill card names. Anything a hint, skill
# card, or preflight nudge tells the model to pass stays visible, and so does
# every required argument.
MODEL_HIDDEN_PARAMS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "notes": frozenset({"content", "body", "limit"}),
        "python": frozenset({"source", "script"}),
        "sql": frozenset({"query"}),
        "remind": frozenset({"text", "seconds", "hours", "when"}),
        "cas": frozenset({"symbol"}),
        # memory text and limit stay visible. Hiding them made the 9B bench
        # item S18 call action=prefer and sit until the 300s timeout.
        "recall": frozenset({"offset", "page", "limit"}),
        "tasks": frozenset({"limit"}),
        "goals": frozenset({"limit"}),
        "inbox": frozenset({"limit"}),
        "inbound_sms": frozenset({"limit"}),
        "workspace": frozenset({"max_chars", "max_results"}),
        "web_fetch": frozenset({"max_chars"}),
        "scrape": frozenset({"max_chars"}),
        "web_search": frozenset({"max_results"}),
        "research_report": frozenset({"max_sources"}),
        "doc_extract": frozenset({"max_chars"}),
        "transcribe": frozenset({"max_chars", "action"}),
        "git_info": frozenset({"max_chars"}),
        "clipboard": frozenset({"max_chars"}),
        "run_script": frozenset({"timeout_s"}),
        "run_task": frozenset({"timeout_s"}),
        "diagnostics": frozenset({"suite"}),
        "browser": frozenset(
            {"heading", "focus", "full_page", "x", "y", "to_x", "to_y"}
        ),
        "desktop": frozenset({"x", "y"}),
        "image": frozenset({"seed", "steps", "cfg", "n", "denoise", "mask_box"}),
        "image_edit": frozenset({"crop_box", "scale", "pad", "sharpness", "invert"}),
        "solar": frozenset({"dvx", "dvy", "dvz", "tracers", "refresh", "epoch_gyr"}),
        "agenda": frozenset({"work_start", "work_end", "keep", "calendar_id"}),
        "contacts": frozenset({"work_phone", "replace_aliases"}),
        "plot": frozenset({"samples", "var"}),
    }
)


def model_parameters(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Return ``params`` minus the hidden properties. Never mutates input."""
    hidden = MODEL_HIDDEN_PARAMS.get(tool_name)
    if not hidden or not isinstance(params, dict):
        return params
    required = params.get("required")
    if isinstance(required, list):
        overlap = set(required) & hidden
        if overlap:
            raise ValueError(
                f"{tool_name} hides required parameters: {sorted(overlap)}"
            )
    props = params.get("properties")
    if not isinstance(props, dict) or not any(name in hidden for name in props):
        return params
    out = copy.deepcopy(params)
    copied = out.get("properties")
    if isinstance(copied, dict):
        out["properties"] = {
            name: spec for name, spec in copied.items() if name not in hidden
        }
    return out
