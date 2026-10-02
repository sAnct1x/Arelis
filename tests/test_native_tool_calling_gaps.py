"""Tests for native_tool_calling gaps fixed in cursor/fix-native-tool-calling-gaps-7456.

Gap 1: Text-form tool calls (e.g. <tool_call>{"name":..., "arguments":...}</tool_call>)
       were printed as text instead of executed.

Gap 2: sql and memory tools didn't record analyze/recall warrants, causing canned
       "I don't know" responses even when tools succeeded.

Gap 3: Empty-arguments tool calls get clear validation errors for model retry.
"""

from __future__ import annotations

import pytest

from arelis.core.evidence import EvidenceLedger
from arelis.core.json_tools import parse_text_tool_call
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.core.turn_scratch import ExactNeed

pytestmark = pytest.mark.no_ui


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


def test_parse_text_tool_call_validates_against_registered_tools() -> None:
    """Text-form tool calls for unregistered tools should be rejected."""
    text = '<tool_call>{"name": "unregistered_tool", "arguments": {}}</tool_call>'
    registered_tools = {"workspace", "weather", "calculator"}
    
    result = parse_text_tool_call(text, registered_tools=registered_tools)
    
    assert result is None


def test_parse_text_tool_call_only_accepts_trailing_blocks() -> None:
    """Only accept tool calls that are the last thing in the message."""
    # Tool call followed by text should be rejected (it's an example)
    text = '<tool_call>{"name": "workspace", "arguments": {}}</tool_call> and that is how you call it.'
    result = parse_text_tool_call(text, registered_tools={"workspace"})
    assert result is None
    
    # Tool call at the end with trailing whitespace should be accepted
    text = '<tool_call>{"name": "workspace", "arguments": {}}</tool_call>  \n  '
    result = parse_text_tool_call(text, registered_tools={"workspace"})
    assert result is not None


def test_parse_text_tool_call_handles_prose_before_call() -> None:
    """Text before the tool call should not prevent parsing if call is at the end."""
    text = 'Let me read that file for you. <tool_call>{"name": "workspace", "arguments": {"action": "read"}}</tool_call>'
    registered_tools = {"workspace"}
    
    result = parse_text_tool_call(text, registered_tools=registered_tools)
    
    assert result is not None
    assert result["name"] == "workspace"


def test_parse_text_tool_call_handles_openai_style() -> None:
    """OpenAI-style tool calls should also parse."""
    text = '<tool_call>{"function": {"name": "weather", "arguments": {"place": "Boston"}}}</tool_call>'
    registered_tools = {"weather"}
    
    result = parse_text_tool_call(text, registered_tools=registered_tools)
    
    assert result is not None
    assert result["name"] == "weather"
    assert result["args"]["place"] == "Boston"


def test_parse_text_tool_call_rejects_malformed_json() -> None:
    """Malformed JSON should return None."""
    text = '<tool_call>{name: workspace, invalid json}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"workspace"})
    
    assert result is None


def test_parse_text_tool_call_rejects_empty_content() -> None:
    """Empty or whitespace-only content should return None."""
    assert parse_text_tool_call("", registered_tools={"workspace"}) is None
    assert parse_text_tool_call("   ", registered_tools={"workspace"}) is None


def test_parse_text_tool_call_works_without_validation() -> None:
    """When registered_tools is None, skip validation."""
    text = '<tool_call>{"name": "any_tool", "arguments": {}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools=None)
    
    assert result is not None
    assert result["name"] == "any_tool"


# ============================================================================
# Gap 2: record_tool with native_tools flag for sql and memory
# ============================================================================


def test_record_tool_sql_with_native_tools_records_analyze() -> None:
    """With native_tools=True, successful sql records analyze warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "sql",
        ok=True,
        output="row_count\n250",
        data={},
        args={"database": "test.db", "query": "SELECT COUNT(*) FROM users"},
        native_tools=True,
    )
    
    assert ledger.has_ok("analyze")
    assert len(ledger.items) == 1
    assert ledger.items[0].kind == "analyze"


def test_record_tool_sql_without_native_tools_records_nothing() -> None:
    """With native_tools=False, sql records nothing (unchanged behavior)."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "sql",
        ok=True,
        output="row_count\n250",
        data={},
        args={"query": "SELECT COUNT(*) FROM users"},
        native_tools=False,
    )
    
    assert not ledger.has_ok("analyze")
    assert len(ledger.items) == 0


def test_record_tool_sql_failed_records_nothing() -> None:
    """Failed sql doesn't record a warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "sql",
        ok=False,
        output="error: no such table",
        data={},
        args={},
        native_tools=True,
    )
    
    assert not ledger.has_ok("analyze")
    assert len(ledger.items) == 0


def test_record_tool_sql_empty_output_records_nothing() -> None:
    """Successful sql with empty output doesn't record a warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "sql",
        ok=True,
        output="",
        data={},
        args={},
        native_tools=True,
    )
    
    assert not ledger.has_ok("analyze")
    assert len(ledger.items) == 0


def test_record_tool_memory_recall_records_warrant() -> None:
    """Memory recall action records recall warrant with native_tools=True."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="Your favorite color is teal.",
        data={"action": "recall"},
        args={"action": "recall", "query": "favorite color"},
        native_tools=True,
    )
    
    assert ledger.has_ok("recall")
    assert len(ledger.items) == 1
    assert ledger.items[0].kind == "recall"


def test_record_tool_memory_search_records_warrant() -> None:
    """Memory search action records recall warrant with native_tools=True."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="Found 2 memories about colors.",
        data={"action": "search"},
        args={"action": "search"},
        native_tools=True,
    )
    
    assert ledger.has_ok("recall")


def test_record_tool_memory_list_records_warrant() -> None:
    """Memory list action records recall warrant with native_tools=True."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="Recent memories: ...",
        data={"action": "list"},
        args={"action": "list"},
        native_tools=True,
    )
    
    assert ledger.has_ok("recall")


def test_record_tool_memory_remember_records_nothing() -> None:
    """Memory remember (write) action doesn't record recall warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="Remembered.",
        data={"action": "remember"},
        args={"action": "remember"},
        native_tools=True,
    )
    
    assert not ledger.has_ok("recall")
    assert len(ledger.items) == 0


def test_record_tool_memory_forget_records_nothing() -> None:
    """Memory forget action doesn't record recall warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="Forgot.",
        data={"action": "forget"},
        args={"action": "forget"},
        native_tools=True,
    )
    
    assert not ledger.has_ok("recall")


def test_record_tool_memory_without_native_tools_records_nothing() -> None:
    """With native_tools=False, memory records nothing (unchanged)."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="Your favorite color is teal.",
        data={"action": "recall"},
        args={"action": "recall"},
        native_tools=False,
    )
    
    assert not ledger.has_ok("recall")
    assert len(ledger.items) == 0


def test_record_tool_memory_failed_records_nothing() -> None:
    """Failed memory doesn't record a warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=False,
        output="error",
        data={"action": "recall"},
        args={},
        native_tools=True,
    )
    
    assert not ledger.has_ok("recall")


def test_record_tool_memory_empty_output_records_nothing() -> None:
    """Successful memory with empty output doesn't record a warrant."""
    ledger = EvidenceLedger()
    
    ledger.record_tool(
        "memory",
        ok=True,
        output="",
        data={"action": "recall"},
        args={},
        native_tools=True,
    )
    
    assert not ledger.has_ok("recall")


# ============================================================================
# Gap 2: Integration with _exactness_finish_refuse
# ============================================================================


def test_exactness_refuse_with_sql_warrant_from_native_tools() -> None:
    """When sql records analyze warrant, exactness doesn't refuse."""
    content = "The table has 250 rows according to the sql query."
    exact_need = ExactNeed(kinds=["analyze"])
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


def test_exactness_refuse_with_memory_warrant_from_native_tools() -> None:
    """When memory records recall warrant, exactness doesn't refuse."""
    content = "Your favorite color is teal."
    exact_need = ExactNeed(kinds=["recall"])
    ledger = EvidenceLedger()
    
    # Simulate memory tool with native_tools=True
    ledger.record_tool(
        "memory",
        ok=True,
        output="Your favorite color is teal.",
        data={"action": "recall"},
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
    
    assert refuse is None


def test_exactness_refuse_without_native_tools_still_refuses() -> None:
    """Without native_tools, sql/memory don't record warrants and exactness refuses."""
    content = "The table has 250 rows."
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    
    # Simulate sql tool with native_tools=False (default)
    ledger.record_tool(
        "sql",
        ok=True,
        output="row_count\n250",
        data={},
        args={},
        native_tools=False,
    )
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    
    # Should refuse since no analyze warrant was recorded
    assert refuse is not None
    assert "I don't know" in refuse


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
        exact_need=ExactNeed(kinds=["analyze"]),
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
        exact_need=ExactNeed(kinds=["recall"]),
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None
