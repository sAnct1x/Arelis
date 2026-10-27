"""A ratchet on what the model is told about its own tools.

Today this pins the status quo. It is not an aspiration — every number here is
measured, and the only permitted edits are the ones that make the surface more
informative. If a change makes any of these worse, that is the failing test
doing its job.

The number that matters is the last one. **Every** parameter description is
written and sitting in the source schemas, and
`compact_prompt.skinny_parameters` deletes all of them before the array reaches
the model server. That was a deliberate trade for prefix-cache stability, priced against
a tools array that changed shape per turn (`tool_subset.py:11-31`). The array
does not change shape any more. When that gets re-priced, the assertion below
flips from "none get through" to "all of them do", and this file is where the
change is recorded.

The counts here are the ones seen under pytest, where conftest points
ARELIS_DATA_DIR at a throwaway root and the four credential-gated tools
(send_sms, send_email, inbox, inbound_sms) plus schedule do not register.
Desktop is out unless the host is Windows, and vision and camera are out
unless the VL model is installed. This file pins that isolated profile.
"""

from __future__ import annotations

import sys

from scripts.measure_tool_schema import (
    SCHEMA_TOKEN_CAP,
    measure,
    tool_specs,
)

# Measured under conftest's isolated data root.
# Raise the floors, never lower them. The ceiling moved when Phase 5
# registered notes/remind/transcribe/sql/pdf (38 → 43), then again when
# run_task registered beside run_script (43 → 44). Re-measured, not
# guessed: skinny schema ≈ 5821 tokens. Tier A hides parameters from
# the model-facing schema on this profile and retargets the ceiling:
# 5,400 on the old chars/4 scale, which is 6,536 Qwen tokens at the
# calibrated ratio. Diagram (45 → 46) stays under that ceiling by also
# hiding negative, format, fit, text_align, and warmth. Class description
# text does not move this count: the one-line catalog overrides it.
# Re-measured after the session set: non-Windows, no VL model, no mail
# or SMS is 43 tools, 20,347 chars, 6,157 Qwen tokens. The old ceiling
# was 6,536. It is now 7,036 (+500 Qwen tokens, +1.7 s cold prefill,
# 0 when the prefix is warm). Worst case (every optional tool, 51) is
# 23,803 chars, 7,203 Qwen tokens, capped at 7,640. Poster look plus
# annotate, scale_bar, and stretch measured 20,883 chars / 6,319 tokens
# on that profile and 24,339 chars / 7,365 on the worst case. With
# remove_background and upscale as well: 20,973 chars / 6,346 tokens
# and 24,429 chars / 7,392. The surface then shrank and the caps were
# ratcheted to 6,600 and 7,450 (issue 291: 6,171 here, about 6,391 with
# desktop, 7,216 worst). Both caps live in SCHEMA_TOKEN_CAP. This order is that non-Windows profile. Windows CI
# inserts desktop in front of tile. Hidden parameters on the
# non-Windows profile are 67 (69 with desktop's x and y).
MAX_SCHEMA_TOKENS = SCHEMA_TOKEN_CAP["default"]
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
    "diagram",
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
    "browser",
    "tile",
)


def default_session_order() -> tuple[str, ...]:
    """CI profile for this host. Desktop is in the list only on Windows."""
    if sys.platform != "win32":
        return SESSION_TOOL_ORDER
    names = list(SESSION_TOOL_ORDER)
    names.insert(names.index("tile"), "desktop")
    return tuple(names)


def test_no_tool_ships_without_a_description() -> None:
    """An unnamed tool is a coin flip for the model."""
    thin = [
        (f.get("name"), len(f.get("description") or ""))
        for spec in tool_specs()
        for f in [spec.get("function", spec)]
        if len(f.get("description") or "") < MIN_DESCRIPTION_CHARS
    ]
    assert not thin, f"tools described in under {MIN_DESCRIPTION_CHARS} chars: {thin}"


def test_an_action_parameter_always_lists_its_verbs() -> None:
    """Without an enum the model invents the verb, and the call is rejected."""
    stats = measure(tool_specs())
    assert not stats["action_without_enum"], (
        "tools whose action= has no enum: "
        f"{stats['action_without_enum']}. The model has to guess the verb."
    )


def test_hidden_params_leave_the_model_schema_and_stay_accepted() -> None:
    from arelis.core.tool_args import cross_tool_arg_error, schema_keys
    from arelis.tools.desktop_tool import DesktopTool
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
    source_schemas.setdefault("desktop", DesktopTool.parameters_schema)

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
    # 69 on the old profile, which included desktop. x and y are the two
    # hidden desktop parameters. A non-Windows session does not register it.
    expected_hidden = 67 + (2 if "desktop" in visible else 0)
    assert hidden_on_profile == expected_hidden
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


def test_workspace_actions_stay_in_the_model_enum() -> None:
    """The one-liner no longer lists verbs. The enum the model sees still does.

    Checked on every session profile, with parameter hints off and on.
    Tail mode does not send workspace at all, which was already true.
    """
    from types import SimpleNamespace

    from arelis.config import load_config
    from arelis.tools import build_tool_registry
    from scripts.measure_tool_schema import registry_for_profile, tool_specs

    needed = (
        "list",
        "read",
        "grep",
        "find",
        "write",
        "edit",
        "patch",
        "delete",
        "move",
        "rename",
        "copy",
    )
    router = SimpleNamespace(provider=SimpleNamespace(list_models=None))
    windows = load_config()
    windows["_vl_model_installed"] = False
    windows["_session_platform"] = "win32"
    windows_reg = build_tool_registry(
        windows, allow_send=True, attended=True, router=router
    )
    profiles = {
        "default": registry_for_profile("default"),
        "mac": registry_for_profile("mac"),
        "worst": registry_for_profile("worst"),
        "windows": windows_reg,
    }
    missing = []
    for name, registry in profiles.items():
        for hints in (False, True):
            specs = (
                tool_specs(registry)
                if not hints
                else list(registry.chat_tools(param_hints=True))
            )
            action = None
            for spec in specs:
                fn = spec["function"]
                if fn["name"] == "workspace":
                    action = fn["parameters"]["properties"]["action"]
                    break
            assert action is not None, (name, hints)
            enum = action.get("enum") or []
            gone = [verb for verb in needed if verb not in enum]
            if gone:
                missing.append((name, hints, gone))
    assert not missing, missing




def test_schema_stays_under_its_token_cap() -> None:
    """The cap was a number nothing checked, so it drifted 700 tokens loose."""
    from scripts.measure_tool_schema import registry_for_profile

    default = measure(tool_specs())["schema_tokens_approx"]
    worst = measure(tool_specs(registry_for_profile("worst")))["schema_tokens_approx"]
    assert default <= MAX_SCHEMA_TOKENS, default
    assert worst <= SCHEMA_TOKEN_CAP["worst"], worst
