"""A ratchet on what the model is told about its own tools.

Today this pins the status quo. It is not an aspiration — every number here is
measured, and the only permitted edits are the ones that make the surface more
informative. If a change makes any of these worse, that is the failing test
doing its job.

The number that matters is the last one. **Every** parameter description is
written and sitting in the source schemas, and
`compact_prompt.skinny_parameters` deletes all of them before the array reaches
Ollama. That was a deliberate trade for prefix-cache stability, priced against
a tools array that changed shape per turn (`tool_subset.py:11-31`). The array
does not change shape any more. When that gets re-priced, the assertion below
flips from "none get through" to "all of them do", and this file is where the
change is recorded.

The counts here are the ones seen under pytest, where conftest points
ARELIS_DATA_DIR at a throwaway root and the four credential-gated tools
(send_sms, send_email, inbox, inbound_sms) plus schedule do not register. A
shell run against a real profile reports 43 tools and 280 parameters. Both are
deterministic; this file pins the isolated one so CI and a laptop agree.
"""

from __future__ import annotations

import inspect
import json
import re

from scripts.measure_tool_schema import (
    authored_parameter_docs,
    measure,
    schema_token_estimate,
    tool_specs,
)

# Measured under conftest's isolated data root.
# Raise the floors, never lower them. The ceiling moved when Phase 5
# registered notes/remind/transcribe/sql/pdf (38 → 43), then again when
# run_task registered beside run_script (43 → 44). Re-measured, not
# guessed: skinny schema ≈ 5821 tokens. Tier A hides 64 parameters from
# the model-facing schema on this profile (66 names in the constant;
# memory text and limit stay visible) and retargets the ceiling: 5,400
# on the old chars/4 scale, which is 6,536 Qwen tokens at the calibrated
# ratio.
EXPECTED_TOOLS = 45
MAX_SCHEMA_TOKENS = schema_token_estimate(5_400 * 4)
MIN_DESCRIPTION_CHARS = 12
MIN_MEDIAN_DESCRIPTION = 41

# Registry order on the isolated profile. The prefix cache keys on this
# sequence. Do not sort it.
SESSION_TOOL_ORDER = (
    "recall",
    "memory",
    "tasks",
    "goals",
    "contacts",
    "rooms",
    "web_fetch",
    "scrape",
    "web_search",
    "research_report",
    "agenda",
    "clipboard",
    "ocr",
    "calculator",
    "python",
    "diagnostics",
    "watch",
    "cas",
    "units",
    "catalog",
    "solar",
    "earth",
    "plot",
    "data_cell",
    "document",
    "pdf",
    "workspace",
    "notes",
    "remind",
    "transcribe",
    "git_info",
    "run_script",
    "run_task",
    "analyze",
    "sql",
    "doc_extract",
    "user_location",
    "weather",
    "image",
    "image_edit",
    "vision",
    "camera",
    "browser",
    "desktop",
    "tile",
)


def test_the_tool_count_is_deliberate() -> None:
    """Tools arrive by decision, not by accident. Update the number knowingly."""
    stats = measure(tool_specs())
    assert stats["tools"] == EXPECTED_TOOLS, (
        f"tool count moved to {stats['tools']}. If that was intended, update "
        "EXPECTED_TOOLS and check measure_tool_surface_prefill.py — every tool "
        "is in the constant prefix of every single turn."
    )


def test_the_schema_stays_inside_its_budget() -> None:
    stats = measure(tool_specs())
    assert stats["schema_tokens_approx"] <= MAX_SCHEMA_TOKENS, (
        f"tool schema grew to ~{stats['schema_tokens_approx']} tokens. "
        "That is prefilled on every turn; re-measure before raising the cap."
    )


def test_no_tool_ships_without_a_description() -> None:
    """An unnamed tool is a coin flip for the model."""
    thin = [
        (f.get("name"), len(f.get("description") or ""))
        for spec in tool_specs()
        for f in [spec.get("function", spec)]
        if len(f.get("description") or "") < MIN_DESCRIPTION_CHARS
    ]
    assert not thin, f"tools described in under {MIN_DESCRIPTION_CHARS} chars: {thin}"


def test_descriptions_do_not_get_terser() -> None:
    stats = measure(tool_specs())
    assert stats["description_median"] >= MIN_MEDIAN_DESCRIPTION, (
        f"median tool description fell to {stats['description_median']} chars. "
        "The compensation layer exists because these are already terse."
    )


def test_an_action_parameter_always_lists_its_verbs() -> None:
    """Without an enum the model invents the verb, and the call is rejected."""
    stats = measure(tool_specs())
    assert not stats["action_without_enum"], (
        "tools whose action= has no enum: "
        f"{stats['action_without_enum']}. The model has to guess the verb."
    )


def test_the_authored_descriptions_are_still_written() -> None:
    """Guards the asset, separately from whether it is used.

    If someone deletes the source descriptions because "nothing reads them",
    the Phase 2 experiment stops being a one-function change.
    """
    documented, total = authored_parameter_docs()
    assert documented == total, (
        f"only {documented}/{total} parameter descriptions remain in the source "
        "schemas. These are the material for the schema experiment — do not "
        "delete them on the grounds that the model never sees them."
    )
    assert total >= 253, f"parameter count fell to {total}; a tool lost its schema"


def test_records_that_none_of_them_reach_the_model() -> None:
    """The headline finding, pinned so it cannot change silently.

    This asserts the *current* behaviour, not the desired one. When
    skinny_parameters stops stripping, this test fails — and the right response
    is to invert it, not to restore the stripping.
    """
    stats = measure(tool_specs())
    documented, _total = authored_parameter_docs()
    assert stats["documented_params"] == 0, (
        "parameter descriptions are now reaching the model. That is the Phase 2 "
        "goal, so invert this assertion and record the prefill cost from "
        "scripts/measure_tool_surface_prefill.py alongside it."
    )
    thrown_away = documented - stats["documented_params"]
    assert thrown_away == documented, (
        f"{thrown_away} of {documented} authored descriptions are stripped. "
        "A partial strip is the worst of both: the cost of the text without "
        "the benefit."
    )


def test_schema_token_estimate_is_the_qwen_ratio() -> None:
    """5,400 chars/4-tokens is the tier A ceiling, restated in Qwen tokens."""
    assert schema_token_estimate(23_570) == 7_132
    assert MAX_SCHEMA_TOKENS == 6_536
    assert MAX_SCHEMA_TOKENS == schema_token_estimate(5_400 * 4)


def test_session_tool_order_is_pinned() -> None:
    from arelis.config import load_config
    from arelis.core.tool_surface import session_tool_schemas
    from scripts.measure_tool_schema import _registry

    config = load_config()
    names = [
        spec["function"]["name"]
        for spec in session_tool_schemas(_registry(), config.get("agent"))
    ]
    assert names == [spec.get("function", spec)["name"] for spec in tool_specs()]
    assert names == list(SESSION_TOOL_ORDER)


def test_warmup_schema_bytes_match_the_turn_schema() -> None:
    """Startup warmup and every turn share one schema array."""
    from arelis.config import load_config
    from arelis.core.tool_surface import session_tool_schemas
    from arelis.llm.startup import prefix_warmup_for
    from scripts.measure_tool_schema import _registry

    config = load_config()
    registry = _registry()
    agent = config.get("agent")
    first = session_tool_schemas(registry, agent)
    second = session_tool_schemas(registry, agent)
    warm = prefix_warmup_for(config, registry)
    assert warm is not None
    blob = json.dumps(first)
    assert blob == json.dumps(second) == json.dumps(warm.tools)


def test_the_hide_list_is_a_fixed_constant() -> None:
    import arelis.tools.model_schema as model_schema
    from arelis.tools.model_schema import MODEL_HIDDEN_PARAMS, model_parameters

    assert model_schema.MODEL_HIDDEN_PARAMS is MODEL_HIDDEN_PARAMS
    assert type(MODEL_HIDDEN_PARAMS).__name__ == "mappingproxy"
    assert all(isinstance(names, frozenset) for names in MODEL_HIDDEN_PARAMS.values())
    assert list(inspect.signature(model_parameters).parameters) == ["tool_name", "params"]
    assert "environ" not in model_parameters.__code__.co_names
    assert "memory" not in MODEL_HIDDEN_PARAMS
    assert sum(len(names) for names in MODEL_HIDDEN_PARAMS.values()) == 66


def test_hidden_params_leave_the_model_schema_and_stay_accepted() -> None:
    from arelis.core.tool_args import cross_tool_arg_error, schema_keys
    from arelis.tools.inbound_sms import InboundSmsTool
    from arelis.tools.inbox import InboxTool
    from arelis.tools.model_schema import MODEL_HIDDEN_PARAMS, model_parameters
    from scripts.measure_tool_schema import _registry

    registry = _registry()
    visible = {
        spec["function"]["name"]: spec["function"]["parameters"]["properties"]
        for spec in tool_specs()
    }
    source_schemas = {
        name: getattr(registry.get(name), "parameters_schema", None) or {}
        for name in registry.names()
    }
    source_schemas.setdefault("inbox", InboxTool.parameters_schema)
    source_schemas.setdefault("inbound_sms", InboundSmsTool.parameters_schema)

    missing = []
    hidden_on_profile = 0
    for name, hidden in MODEL_HIDDEN_PARAMS.items():
        source = source_schemas[name]
        declared = schema_keys(source)
        absent = hidden - declared
        if absent:
            missing.append((name, sorted(absent)))
        required = set(source.get("required") or [])
        assert not (required & hidden), (name, sorted(required & hidden))
        if name not in visible:
            continue
        shown = set(visible[name])
        assert not (hidden & shown), (name, sorted(hidden & shown))
        hidden_on_profile += len(hidden & declared)
        sample = next(iter(hidden & declared))
        original = {"type": "object", "properties": dict(source["properties"])}
        returned = model_parameters(name, original)
        assert original["properties"].keys() == source["properties"].keys()
        assert sample not in returned["properties"]
        assert (
            cross_tool_arg_error(
                name,
                {sample: "x"},
                declared=declared,
                strict=True,
            )
            is None
        )
    assert not missing, missing
    assert hidden_on_profile == 64
    assert "text" in visible["memory"] and "limit" in visible["memory"]

    notes = visible["notes"]
    assert "content" not in notes and "text" in notes
    with_required = {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    }
    raised = False
    try:
        model_parameters("notes", with_required)
    except ValueError as exc:
        raised = True
        assert "content" in str(exc)
    assert raised, "hiding a required parameter must fail"


def test_short_descriptions_name_real_actions() -> None:
    from arelis.core.compact_prompt import _SHORT_DESC
    from arelis.tools.schedule_jobs import ScheduleTool
    from arelis.tools.tasks import TasksTool

    enums = {
        "tasks": set(TasksTool.parameters_schema["properties"]["action"]["enum"]),
        "schedule": set(ScheduleTool.parameters_schema["properties"]["action"]["enum"]),
    }
    bad = []
    for name, enum in enums.items():
        for match in re.finditer(
            r"action=([a-z_]+(?:\|[a-z_]+)*)", _SHORT_DESC[name]
        ):
            bad.extend(
                (name, verb)
                for verb in match.group(1).split("|")
                if verb not in enum
            )
    assert not bad, bad
    assert "drop" not in _SHORT_DESC["tasks"]
    assert "run_now" in _SHORT_DESC["schedule"]
    data_cell = _SHORT_DESC["data_cell"]
    assert len(data_cell) > 13
    assert "not weather" in data_cell
