"""Test native_tool_calling experiment flag disables regex/intent routing."""

from __future__ import annotations

import pytest

from arelis.core.prompt_sections import append_preflight_guidance
from arelis.core.tool_subset import filter_tool_names

pytestmark = pytest.mark.no_ui

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


def test_default_does_not_nudge_a_tool_from_the_ask() -> None:
    """Missing native_tool_calling does not invent a tool or a preflight nudge."""
    agent_cfg: dict[str, bool] = {}
    text = "What's the weather today?"
    messages: list[dict[str, str]] = []

    class MockLoop:
        def __init__(self) -> None:
            self._expected_tools: set[str] = set()
            self._timer = None
            self.memory = type("obj", (object,), {"messages": []})()

    loop = MockLoop()
    kinds = append_preflight_guidance(
        messages,
        loop,
        text,
        agent_cfg,
        see_no_sms_redirect=frozenset(),
    )
    assert kinds == []
    assert messages == []
    assert loop._expected_tools == set()
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )
    assert "weather" in visible
    assert "send_sms" not in visible


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
            self.memory = type("obj", (object,), {"messages": []})()

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


def test_flag_default_is_false() -> None:
    """Verify the default is false (current regex routing behavior)."""
    # Missing key should default to false
    agent_cfg: dict[str, bool] = {}
    assert not agent_cfg.get("native_tool_calling", False)

    # Explicit false
    agent_cfg = {"native_tool_calling": False}
    assert not agent_cfg.get("native_tool_calling", False)


# Safety gate tests - these must stay ON regardless of native_tool_calling


def test_safety_sms_authorization_gate_still_active() -> None:
    """SMS authorization must stay active even with native_tool_calling=true."""
    agent_cfg = {"native_tool_calling": True}

    # A request that does NOT mention sending SMS should hide send_sms
    text = "What's the weather today?"

    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )

    # SMS should be hidden when not requested (authorization filter)
    assert "send_sms" not in visible

    # But when SMS is explicitly requested, it should be visible
    text_with_sms = "text Brian that I'm running late"
    visible_sms = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text_with_sms,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )

    # SMS should be authorized when asked for
    assert "send_sms" in visible_sms


def test_safety_email_authorization_gate_still_active() -> None:
    """Email authorization must stay active even with native_tool_calling=true."""
    agent_cfg = {"native_tool_calling": True}

    # A request that does NOT mention sending email should hide send_email
    text = "What's the weather today?"

    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )

    # Email should be hidden when not requested (authorization filter)
    assert "send_email" not in visible

    # But when email is explicitly requested, it should be visible
    text_with_email = "email Sarah about the meeting"
    visible_email = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=text_with_email,
        enabled=False,
        skill_subset=True,
        agent_cfg=agent_cfg,
    )

    # Email should be authorized when asked for
    assert "send_email" in visible_email


