"""Tests for native_tool_calling gaps fixed in cursor/fix-native-tool-calling-gaps-7456.

Gap 1: Text-form tool calls (e.g. <tool_call>{"name":..., "arguments":...}</tool_call>)
       were printed as text instead of executed.

Gap 2: sql and memory tools didn't record analyze/recall warrants, causing canned
       "I don't know" responses even when tools succeeded.

Gap 3: Empty-arguments tool calls get clear validation errors for model retry.
"""

from __future__ import annotations

import pytest

from arelis.core.claims import ExactnessNeed, detect_exactness_need
from arelis.core.evidence import EvidenceLedger
from arelis.core.json_tools import parse_text_tool_call
from arelis.core.loop_helpers import _exactness_finish_refuse

pytestmark = pytest.mark.no_ui


def _need(kinds: tuple[str, ...]) -> ExactnessNeed:
    """Helper to build ExactnessNeed with required fields."""
    return ExactnessNeed(
        needs_calculator=False,
        needs_web_evidence=False,
        needs_weather=False,
        needs_recall=False,
        kinds=kinds,
    )


# ============================================================================
# Gap 1: Text-form tool call parsing
# ============================================================================


def test_parse_text_tool_call_extracts_valid_call() -> None:
    """When native_tool_calling is on, text-form tool calls should be parsed."""
    text = '<tool_call>{"name": "workspace", "arguments": {"action": "read", "path": "test.txt"}}</tool_call>'
    registered_tools = {"workspace", "weather", "calculator"}
    
    result = parse_text_tool_call(text, registered_tools=registered_tools)
    
    assert result is not None
    assert result["kind"] == "tool"
    assert result["name"] == "workspace"
    assert result["args"]["action"] == "read"
    assert result["args"]["path"] == "test.txt"


# ============================================================================
# Gap 2: record_tool with native_tools flag for sql and memory
# ============================================================================


# ============================================================================
# Gap 2: Integration with _exactness_finish_refuse
# ============================================================================


def test_exactness_refuse_with_sql_warrant_from_native_tools() -> None:
    """When sql records analyze warrant, exactness doesn't refuse."""
    content = "The table has 250 rows according to the sql query."
    exact_need = _need(kinds=("analyze",))
    ledger = EvidenceLedger()
    
    # Simulate sql tool with native_tools=True
    ledger.record_tool(
        "sql",
        ok=True,
        output="row_count\n250",
        data={},
        args={},
        native_tools=True,
    )
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    
    # Should not refuse since we have the analyze warrant
    assert refuse is None


# ============================================================================
# Integration scenarios from live matrix failures
# ============================================================================


def test_scenario_s27_sql_with_native_tools() -> None:
    """S27: sql tool returned 250, now records analyze warrant with flag on."""
    ledger = EvidenceLedger()
    ledger.record_tool(
        "sql",
        ok=True,
        output="row_count\n250",
        data={},
        args={},
        native_tools=True,
    )
    
    assert ledger.has_ok("analyze")
    
    # Now exactness won't refuse
    refuse = _exactness_finish_refuse(
        "The table has 250 rows.",
        exact_need=_need(kinds=("analyze",)),
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None


def _shipped_native_flag() -> bool:
    """The flag in arelis/config/default.yaml, not a local override."""
    import yaml

    from arelis.config import DEFAULT_CONFIG_PATH

    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    return bool(shipped["agent"]["native_tool_calling"])


def test_default_flag_sql_row_count_satisfies_analyze() -> None:
    """S27: a 250-row sql result satisfies a row-count question with the flag off."""
    assert _shipped_native_flag() is False
    question = "How many rows are in work/sales.csv?"
    exact_need = detect_exactness_need(question)
    assert "analyze" in exact_need.kinds
    ledger = EvidenceLedger()
    ledger.record_tool(
        "sql",
        ok=True,
        output="row_count\n250",
        data={},
        args={"database": "work/sales.csv", "query": "SELECT COUNT(*) AS row_count FROM sales"},
        native_tools=_shipped_native_flag(),
    )
    assert ledger.missing_kinds(("analyze",)) == []
    refuse = _exactness_finish_refuse(
        "The table has 250 rows.",
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None


def test_scenario_s18_memory_with_native_tools() -> None:
    """S18: memory returned teal, now records recall warrant with flag on."""
    ledger = EvidenceLedger()
    ledger.record_tool(
        "memory",
        ok=True,
        output="Your favorite color is teal.",
        data={"action": "recall"},
        args={},
        native_tools=True,
    )
    
    assert ledger.has_ok("recall")
    
    # Now exactness won't refuse
    refuse = _exactness_finish_refuse(
        "Your favorite color is teal.",
        exact_need=_need(kinds=("recall",)),
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None
