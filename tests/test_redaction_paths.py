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
from arelis.tools.safety import redact_data

_SECRET = "sk-live-abcdefghijklmnopqrstuvwx"
_ASSIGNMENT = "api_key=sk-live-abcdefghijklmnopqrstuvwx"


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


# --------------------------------------------------------------------------
# The structured half of a result
# --------------------------------------------------------------------------


def test_the_shape_of_data_survives() -> None:
    """UI readers index into this. Scrubbing must not reshape it."""
    original = {"ok": True, "count": 3, "rows": [{"a": 1}], "pair": ("x", "y")}
    cleaned = redact_data(original)
    assert cleaned == original
    assert isinstance(cleaned["pair"], tuple)
    assert isinstance(cleaned["rows"], list)


def test_secret_eight_deep_is_redacted() -> None:
    """Past the depth cap the walk used to return the value raw."""
    node: object = _ASSIGNMENT
    for _ in range(8):
        node = {"n": node}
    cleaned = redact_data(node)
    assert _SECRET not in str(cleaned)
    assert "[redacted: too deep]" in str(cleaned)


