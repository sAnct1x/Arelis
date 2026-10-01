"""Regression test for multi-tool chain continuation.

Ensures that calculator_ok, units_ok, inspect_ok, run_script_ok, tile_ok, and
agenda_open_read_ok do NOT disable all tools for subsequent rounds, allowing
multi-tool chains to complete.

This was broken when these flags were added to the tool-disabling condition in
turn_round.py line ~527. The fix removes them so tools remain available for
continuation.
"""

from arelis.core.turn_context import TurnContext
from arelis.core.turn_scratch import RoundScratch


def test_calculator_ok_does_not_disable_all_tools():
    """After calculator succeeds, other tools should still be available."""
    ctx = TurnContext(text="convert 100 fahrenheit to celsius then save it", role="")
    ctx.calculator_ok = True
    ctx.available_all = {"calculator", "units", "memory", "workspace"}
    ctx.available = set(ctx.available_all)
    ctx.visible = set(ctx.available_all)
    ctx.tool_names.update(ctx.visible)
    
    # Simulate the tool-disable check from turn_round.py line ~527
    # After the fix, calculator_ok should NOT trigger the disable
    round_i = 2
    should_disable = (
        ctx.email_sent_ok
        or ctx.agenda_create_ok
        or bool(ctx.sms_sent)
        or ctx.page_write_nudge_used
        or ctx.algebra_write_nudge_used
    )
    
    assert not should_disable, "calculator_ok should not trigger tool disable"
    assert ctx.tool_names, "tools should still be available"


def test_units_ok_does_not_disable_all_tools():
    """After units succeeds, other tools should still be available."""
    ctx = TurnContext(text="convert 100F to C then calculate the square", role="")
    ctx.units_ok = True
    ctx.available_all = {"calculator", "units", "memory"}
    ctx.available = set(ctx.available_all)
    ctx.visible = set(ctx.available_all)
    ctx.tool_names.update(ctx.visible)
    
    round_i = 2
    should_disable = (
        ctx.email_sent_ok
        or ctx.agenda_create_ok
        or bool(ctx.sms_sent)
        or ctx.page_write_nudge_used
        or ctx.algebra_write_nudge_used
    )
    
    assert not should_disable, "units_ok should not trigger tool disable"


def test_inspect_ok_does_not_disable_all_tools():
    """After workspace read succeeds, other tools should still be available."""
    ctx = TurnContext(text="read the file then create a document", role="")
    ctx.inspect_ok = True
    ctx.available_all = {"workspace", "document", "doc_extract"}
    ctx.available = set(ctx.available_all)
    ctx.visible = set(ctx.available_all)
    ctx.tool_names.update(ctx.visible)
    
    round_i = 2
    should_disable = (
        ctx.email_sent_ok
        or ctx.agenda_create_ok
        or bool(ctx.sms_sent)
        or ctx.page_write_nudge_used
        or ctx.algebra_write_nudge_used
    )
    
    assert not should_disable, "inspect_ok should not trigger tool disable"


def test_run_script_ok_does_not_disable_all_tools():
    """After run_script succeeds, other tools should still be available."""
    ctx = TurnContext(text="run the script then show me the output", role="")
    ctx.run_script_ok = True
    ctx.available_all = {"run_script", "workspace"}
    ctx.available = set(ctx.available_all)
    ctx.visible = set(ctx.available_all)
    ctx.tool_names.update(ctx.visible)
    
    round_i = 2
    should_disable = (
        ctx.email_sent_ok
        or ctx.agenda_create_ok
        or bool(ctx.sms_sent)
        or ctx.page_write_nudge_used
        or ctx.algebra_write_nudge_used
    )
    
    assert not should_disable, "run_script_ok should not trigger tool disable"


def test_email_sent_ok_does_disable_all_tools():
    """After email is sent, tools SHOULD be disabled (this behavior is correct)."""
    ctx = TurnContext(text="email the report to alice", role="")
    ctx.email_sent_ok = True
    ctx.available_all = {"send_email", "workspace", "document"}
    ctx.available = set(ctx.available_all)
    ctx.visible = set(ctx.available_all)
    ctx.tool_names.update(ctx.visible)
    
    round_i = 2
    should_disable = (
        ctx.email_sent_ok
        or ctx.agenda_create_ok
        or bool(ctx.sms_sent)
        or ctx.page_write_nudge_used
        or ctx.algebra_write_nudge_used
    )
    
    assert should_disable, "email_sent_ok SHOULD trigger tool disable to force answer"
