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

from scripts.measure_tool_schema import authored_parameter_docs, measure, tool_specs

# Measured 2026-09-17 under conftest's isolated data root.
# Raise the floors, never lower them.
EXPECTED_TOOLS = 38
MAX_SCHEMA_TOKENS = 5_000
MIN_DESCRIPTION_CHARS = 12
MIN_MEDIAN_DESCRIPTION = 41


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
