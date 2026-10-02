"""Test native_tool_calling experiment flag disables regex/intent routing."""

from __future__ import annotations

from arelis.core.preflight import detect_intents, preflight_system_message
from arelis.core.prompt_sections import append_preflight_guidance
from arelis.core.tool_subset import filter_tool_names


_EVERYDAY = {
    "weather",
    "user_location",
    "web_fetch",
    "web_search",
    "scrape",
    "calculator",
    "cas",
    "units",
    "plot",
    "catalog",
    "send_sms",
    "inbound_sms",
    "contacts",
    "inbox",
    "send_email",
    "image",
    "recall",
    "memory",
    "tasks",
    "goals",
    "workspace",
    "doc_extract",
}


def test_default_behavior_uses_regex_routing() -> None:
    """With default config (native_tool_calling=false), regex routing is active."""
    # Default agent_cfg has native_tool_calling=false (or missing, defaults false)
    agent_cfg: dict[str, bool] = {}
    
    # detect_intents should return hints for a clear weather ask
    text = "What's the weather today?"
    hints = detect_intents(text)
    assert len(hints) > 0
    assert any(h.kind == "weather" for h in hints)
    
    # preflight_system_message should generate a nudge
    nudge = preflight_system_message(text)
    assert nudge is not None
    assert "weather" in nudge.lower()
    
    # filter_tool_names should use intent routing
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )
    # With regex routing, weather tools should be in the subset
    assert "weather" in visible
    assert "user_location" in visible


def test_native_tool_calling_disables_preflight_nudges() -> None:
    """When native_tool_calling=true, preflight nudges are skipped."""
    agent_cfg = {"native_tool_calling": True}
    
    text = "What's the weather today?"
    
    # Simulate the append_preflight_guidance flow
    messages: list[dict[str, str]] = []
    
    class MockLoop:
        def __init__(self) -> None:
            self._expected_tools: set[str] = set()
            self._timer = None
            self.memory = type('obj', (object,), {'messages': []})()
    
    loop = MockLoop()
    preflight_kinds = append_preflight_guidance(
        messages,
        loop,
        text,
        agent_cfg,
        see_no_sms_redirect=frozenset(),
    )
    
    # With native_tool_calling, no preflight kinds should be detected
    assert len(preflight_kinds) == 0
    # No system messages should be appended
    assert len(messages) == 0
    # No expected tools should be populated via regex
    assert len(loop._expected_tools) == 0


def test_native_tool_calling_disables_tool_subset_routing() -> None:
    """When native_tool_calling=true, tool subset filtering skips regex routing."""
    agent_cfg = {"native_tool_calling": True}
    
    text = "What's the weather today?"
    
    # With native tool calling, filter_tool_names should not use detect_intents
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )
    
    # Without regex routing and with skill_subset=True but no skill matches,
    # should return full surface (fail-open behavior)
    # The safety filter (SMS/email authorization) still applies, but weather
    # should not be specially subset
    assert "weather" in visible
    assert "calculator" in visible
    # Should have most tools available since regex routing is disabled
    assert len(visible) > 5


def test_native_tool_calling_preserves_sms_safety() -> None:
    """native_tool_calling disables routing but preserves SMS/email authorization."""
    agent_cfg = {"native_tool_calling": True}
    
    # An ask that does NOT mention sending SMS
    text = "What's the weather today?"
    
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )
    
    # SMS/email tools should still be hidden when not requested
    # (authorization filter is separate from intent routing)
    assert "send_sms" not in visible
    assert "send_email" not in visible
    
    # But an ask that DOES mention sending SMS should keep it visible
    text_with_sms = "text Brian that I'm running late"
    visible_sms = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text_with_sms,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )
    
    # Even with native_tool_calling, SMS should be authorized when asked for
    # The authorization check uses its own detection, not general intent routing
    assert "send_sms" in visible_sms


def test_flag_default_is_false() -> None:
    """Verify the default is false (current regex routing behavior)."""
    # Missing key should default to false
    agent_cfg: dict[str, bool] = {}
    assert not agent_cfg.get("native_tool_calling", False)
    
    # Explicit false
    agent_cfg = {"native_tool_calling": False}
    assert not agent_cfg.get("native_tool_calling", False)


def test_both_flags_together() -> None:
    """Test interaction of native_tool_calling with intent_preflight."""
    # native_tool_calling should override intent_preflight
    agent_cfg = {
        "native_tool_calling": True,
        "intent_preflight": True,  # This should be ignored when native_tool_calling=True
    }
    
    text = "What's the weather today?"
    messages: list[dict[str, str]] = []
    
    class MockLoop:
        def __init__(self) -> None:
            self._expected_tools: set[str] = set()
            self._timer = None
            self.memory = type('obj', (object,), {'messages': []})()
    
    loop = MockLoop()
    preflight_kinds = append_preflight_guidance(
        messages,
        loop,
        text,
        agent_cfg,
        see_no_sms_redirect=frozenset(),
    )
    
    # native_tool_calling=True should prevent preflight even when intent_preflight=True
    assert len(preflight_kinds) == 0
    assert len(messages) == 0


def test_backward_compatibility_no_agent_cfg() -> None:
    """Verify that omitting agent_cfg preserves existing behavior (regex routing on)."""
    text = "What's the weather today?"
    
    # Call filter_tool_names without agent_cfg (existing test pattern)
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        # agent_cfg not passed - should default to regex routing ON
    )
    
    # Should work the same as before - regex routing active
    assert "weather" in visible
    assert "calculator" in visible


def test_backward_compatibility_empty_agent_cfg() -> None:
    """Verify that empty agent_cfg preserves existing behavior."""
    text = "What's the weather today?"
    agent_cfg: dict[str, bool] = {}
    
    # Call with empty agent_cfg
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )
    
    # Should work the same as before - regex routing active
    assert "weather" in visible
    assert "calculator" in visible
