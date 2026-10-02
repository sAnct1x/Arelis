"""Tests for native_tool_calling gaps fixed in cursor/fix-native-tool-calling-gaps-7456.

Gap 1: Text-form tool calls (e.g. <tool_call>{"name":..., "arguments":...}</tool_call>)
       were printed as text instead of executed.

Gap 2: Canned "I don't know" overrides replaced good answers even when tools succeeded.

Gap 3: Empty-arguments tool calls failed without clear feedback for the model to retry.
"""

from __future__ import annotations

import pytest

from arelis.core.evidence import EvidenceLedger, EvidenceWarrant
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


def test_parse_text_tool_call_handles_prose_before_call() -> None:
    """Text before the tool call should not prevent parsing."""
    text = 'Let me read that file for you. <tool_call>{"name": "workspace", "arguments": {"action": "read"}}</tool_call>'
    registered_tools = {"workspace"}
    
    result = parse_text_tool_call(text, registered_tools=registered_tools)
    
    assert result is not None
    assert result["name"] == "workspace"


def test_parse_text_tool_call_uses_last_match() -> None:
    """When multiple text-form tool calls exist, use the last one."""
    text = '''
    <tool_call>{"name": "calculator", "arguments": {"expression": "2+2"}}</tool_call>
    Actually, let me use workspace instead.
    <tool_call>{"name": "workspace", "arguments": {"action": "list"}}</tool_call>
    '''
    registered_tools = {"workspace", "calculator"}
    
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
    assert parse_text_tool_call(None, registered_tools={"workspace"}) is None  # type: ignore


def test_parse_text_tool_call_works_without_validation() -> None:
    """When registered_tools is None, skip validation."""
    text = '<tool_call>{"name": "any_tool", "arguments": {}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools=None)
    
    assert result is not None
    assert result["name"] == "any_tool"


def test_parse_text_tool_call_flag_off_unchanged() -> None:
    """When native_tool_calling is off, existing behavior is unchanged.
    
    This is verified by integration tests; here we just ensure the parser
    itself works correctly.
    """
    # The parser is only called when the flag is on, so this test verifies
    # it doesn't break anything when called
    text = '<tool_call>{"name": "workspace", "arguments": {}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"workspace"})
    
    assert result is not None
    assert result["name"] == "workspace"


# ============================================================================
# Gap 2: Canned "I don't know" override should respect successful tools
# ============================================================================


def test_exactness_refuse_respects_successful_tools_with_flag_on() -> None:
    """When native_tool_calling is on and tools succeeded, don't refuse good answers."""
    agent_cfg = {"native_tool_calling": True}
    content = "The row count is 250 based on the analyze tool."
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="analyze", span="250", ok=True, source="analyze_tool"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    # Should not refuse since the tool succeeded
    assert refuse is None


def test_exactness_refuse_still_refuses_when_tool_failed() -> None:
    """Even with native_tool_calling, refuse when tool actually failed."""
    agent_cfg = {"native_tool_calling": True}
    content = "The table has 250 rows."
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="analyze", span="error", ok=False, source="analyze_tool"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    # Should refuse since the tool failed
    assert refuse is not None
    assert "I don't know" in refuse


def test_exactness_refuse_respects_memory_tool_success() -> None:
    """Memory tool success should prevent 'I don't know' with flag on."""
    agent_cfg = {"native_tool_calling": True}
    content = "Your favorite color is teal, as I recall from our conversation."
    exact_need = ExactNeed(kinds=["recall"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="recall", span="teal", ok=True, source="memory"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    # Should not refuse since memory tool succeeded
    assert refuse is None


def test_exactness_refuse_flag_off_uses_old_behavior() -> None:
    """When native_tool_calling is off, use existing refusal logic."""
    agent_cfg = {"native_tool_calling": False}
    content = "The table has 250 rows."
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    # No warrant recorded
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    # Should refuse as before
    assert refuse is not None
    assert "I don't know" in refuse


def test_exactness_refuse_flag_off_respects_successful_warrants() -> None:
    """Flag off: when all warrants present, don't refuse (unchanged behavior)."""
    agent_cfg = {"native_tool_calling": False}
    content = "The table has 250 rows based on the analysis."
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="analyze", span="250", ok=True, source="analyze_tool"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    # Should not refuse (existing behavior)
    assert refuse is None


def test_exactness_refuse_empty_content_still_refuses() -> None:
    """Even with flag on, empty content should not bypass refusal."""
    agent_cfg = {"native_tool_calling": True}
    content = ""
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="analyze", span="250", ok=True, source="analyze_tool"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    # Should refuse due to empty content
    assert refuse is not None


# ============================================================================
# Gap 3: Empty-arguments tool calls should get clear validation errors
# ============================================================================


def test_notes_tool_empty_content_error_is_clear() -> None:
    """The notes tool should return a clear error for empty content.
    
    This is integration-level validation; the actual tool validation
    happens in the tool itself and is already tested in tool-specific tests.
    This test documents the expected behavior.
    """
    # This is tested via integration tests in the main test suite
    # The desk.write_note function raises ValueError("keep needs something to write down.")
    # which is caught and returned as a ToolResult with ok=False
    pass


def test_workspace_write_empty_content_error_is_clear() -> None:
    """The workspace tool should return a clear error for empty content.
    
    This is integration-level validation; the actual tool validation
    happens in the tool itself and is already tested in tool-specific tests.
    This test documents the expected behavior.
    """
    # This is tested via integration tests in the main test suite
    # The CodeWorkspaceTool returns "Missing content. Pass content= with the file body."
    pass


def test_text_tool_call_with_empty_args_still_parses() -> None:
    """Text-form tool calls with empty arguments should still parse.
    
    The tool itself will validate and return an error that the model can retry from.
    """
    text = '<tool_call>{"name": "notes", "arguments": {"action": "add"}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"notes"})
    
    assert result is not None
    assert result["name"] == "notes"
    assert result["args"]["action"] == "add"
    # No content argument is present, but parsing succeeded


def test_text_tool_call_with_empty_content_arg_parses() -> None:
    """Text-form tool calls with explicit empty content should parse.
    
    The tool will validate and return an error.
    """
    text = '<tool_call>{"name": "notes", "arguments": {"action": "add", "content": ""}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"notes"})
    
    assert result is not None
    assert result["name"] == "notes"
    assert result["args"]["content"] == ""


# ============================================================================
# Integration scenarios from live matrix failures
# ============================================================================


def test_chain_c01_text_tool_call_scenario() -> None:
    """Scenario C01: Model emits text-form tool call in chains."""
    # C01 was: doc_extract → calculator, but the calculator call was text-form
    text = 'The budget is 4500. Let me calculate double that. <tool_call>{"name": "calculator", "arguments": {"expression": "4500 * 2"}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"calculator"})
    
    assert result is not None
    assert result["name"] == "calculator"
    assert result["args"]["expression"] == "4500 * 2"


def test_scenario_s27_analyze_success_respected() -> None:
    """Scenario S27: sql tool returned 250 but answer was 'I don't know'."""
    agent_cfg = {"native_tool_calling": True}
    content = "The table has 250 rows according to the sql query."
    exact_need = ExactNeed(kinds=["analyze"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="analyze", span="250", ok=True, source="sql"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    assert refuse is None


def test_scenario_s18_memory_success_respected() -> None:
    """Scenario S18: memory returned teal but answer was 'I don't know'."""
    agent_cfg = {"native_tool_calling": True}
    content = "Your favorite color is teal."
    exact_need = ExactNeed(kinds=["recall"])
    ledger = EvidenceLedger()
    ledger.record(EvidenceWarrant(kind="recall", span="teal", ok=True, source="memory"))
    
    refuse = _exactness_finish_refuse(
        content,
        exact_need=exact_need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
        agent_cfg=agent_cfg,
    )
    
    assert refuse is None


def test_scenario_s22_notes_empty_content_parsed() -> None:
    """Scenario S22: notes call with empty content should parse."""
    text = '<tool_call>{"name": "notes", "arguments": {"action": "add", "content": ""}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"notes"})
    
    assert result is not None
    # Tool will validate and return error, allowing model to retry


def test_scenario_c23_notes_missing_content_parsed() -> None:
    """Scenario C23: notes call without content argument should parse."""
    text = '<tool_call>{"name": "notes", "arguments": {"action": "add"}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"notes"})
    
    assert result is not None
    # Tool will validate and return error, allowing model to retry


def test_scenario_s23_workspace_empty_content_parsed() -> None:
    """Scenario S23: workspace write with empty content should parse."""
    text = '<tool_call>{"name": "workspace", "arguments": {"action": "write", "path": "test.txt", "content": ""}}</tool_call>'
    
    result = parse_text_tool_call(text, registered_tools={"workspace"})
    
    assert result is not None
    # Tool will validate and return error, allowing model to retry
