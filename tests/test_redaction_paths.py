"""The scrubber ran on the way to the model and nowhere else.

`safety.py` line 10 states: "Redaction runs on every tool output before it
reaches the model, the UI, or a confirm card." Two of those three were false.

**The evidence ledger.** `turn_execute` calls `ledger.record_tool` with the
raw `result.output`, roughly sixty lines before it computes
`redact_secrets(result.output)` for the model. Warrant spans are not a dead
end: `quote_lines()` feeds them back into the conversation on the quote-first
nudge, so a credential printed by a tool reached model context by the single
route that skipped the scrubber.

**The event bus.** `TOOL_RESULT` published a redacted `output` beside a
verbatim `data`. The python tool puts its entire cell output in
`data["result"]`, so a secret was scrubbed on one key of the same event and
published intact on the next.

Both are fixed at the boundary rather than the call site — in `add()`, which
every warrant passes through, and by walking `data` before publishing — so a
tool added next month is covered without anyone remembering this file.
"""

from __future__ import annotations

from arelis.core.evidence import EvidenceLedger
from arelis.tools.safety import redact_data, redact_secrets

_SECRET = "sk-live-abcdefghijklmnopqrstuvwx"
_ASSIGNMENT = "api_key=sk-live-abcdefghijklmnopqrstuvwx"


def test_the_pattern_actually_matches_the_fixture() -> None:
    """Guard the guard: if the fixture stopped matching, every test below
    would pass while proving nothing."""
    assert _SECRET not in redact_secrets(_ASSIGNMENT)
    assert "[redacted]" in redact_secrets(_ASSIGNMENT)


# --------------------------------------------------------------------------
# The ledger
# --------------------------------------------------------------------------


def test_a_secret_in_a_tool_output_does_not_become_a_warrant() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "python",
        ok=True,
        output=f"print output: {_ASSIGNMENT}",
        data={"result": f"print output: {_ASSIGNMENT}"},
    )
    assert ledger.items, "the fixture stopped producing a warrant"
    for warrant in ledger.items:
        assert _SECRET not in warrant.span


def test_the_span_that_reaches_the_model_is_scrubbed() -> None:
    """quote_lines() is the path back into the conversation, so it is the one
    that has to be clean."""
    ledger = EvidenceLedger()
    ledger.record_tool(
        "python", ok=True, output=_ASSIGNMENT, data={"result": _ASSIGNMENT}
    )
    assert _SECRET not in "\n".join(ledger.quote_lines())


def test_credentials_in_a_url_do_not_survive_as_a_source() -> None:
    """`source` is a url on every web warrant, and a url can carry userinfo."""
    ledger = EvidenceLedger()
    ledger.add(
        source="https://example.test/x?token=sk-live-abcdefghijklmnopqrstuvwx",
        kind="web",
        span="a page",
        ok=True,
    )
    assert _SECRET not in ledger.items[0].source


def test_an_ordinary_warrant_is_untouched() -> None:
    """Redaction that eats real evidence is its own kind of wrong answer."""
    ledger = EvidenceLedger()
    ledger.add(source="calculator", kind="calc", span="6 * 7 = 42", ok=True)
    assert ledger.items[0].span == "6 * 7 = 42"
    assert ledger.items[0].source == "calculator"


# --------------------------------------------------------------------------
# The structured half of a result
# --------------------------------------------------------------------------


def test_a_secret_nested_in_data_is_scrubbed() -> None:
    cleaned = redact_data(
        {"result": _ASSIGNMENT, "rows": [{"note": _ASSIGNMENT}], "ok": True}
    )
    assert _SECRET not in str(cleaned)


def test_the_shape_of_data_survives() -> None:
    """UI readers index into this. Scrubbing must not reshape it."""
    original = {"ok": True, "count": 3, "rows": [{"a": 1}], "pair": ("x", "y")}
    cleaned = redact_data(original)
    assert cleaned == original
    assert isinstance(cleaned["pair"], tuple)
    assert isinstance(cleaned["rows"], list)


def test_keys_are_left_alone() -> None:
    """A key is a field name we chose, not content a service returned.
    Rewriting one breaks every reader looking for it."""
    cleaned = redact_data({"api_key": "value-here"})
    assert "api_key" in cleaned


def test_non_strings_pass_through() -> None:
    marker = object()
    cleaned = redact_data({"obj": marker, "n": 1, "f": 1.5, "none": None})
    assert cleaned["obj"] is marker
    assert cleaned["n"] == 1
    assert cleaned["none"] is None


def test_a_cycle_does_not_spin() -> None:
    """Bounded on purpose: a tool result is not guaranteed to be a tree."""
    node: dict = {"name": "root"}
    node["self"] = node
    redact_data(node)  # must return, not recurse forever
