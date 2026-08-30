"""Pin the policy table to the confirm / capability behaviour tests already own."""

from __future__ import annotations

from arelis.tools import build_tool_registry
from arelis.tools.base import NEVER_BATCH, ToolRegistry, capability_class
from arelis.tools.policy import (
    batch_ok,
    confirm_toggles_for_call,
    evaluate_capability,
    evaluate_confirm,
)


def test_capability_class_is_the_policy_table() -> None:
    cases = [
        ("web_search", None, "READ"),
        ("python", None, "READ"),
        ("research_report", None, "WRITE_LOCAL_ARTIFACT"),
        ("document", None, "WRITE_LOCAL_ARTIFACT"),
        ("plot", None, "WRITE_LOCAL"),
        ("workspace", {"action": "read"}, "READ"),
        ("workspace", {"action": "write"}, "WRITE_LOCAL"),
        ("send_email", None, "WRITE_EXTERNAL"),
        ("inbox", {"action": "trash"}, "WRITE_EXTERNAL"),
        ("inbox", {"action": "list"}, "READ"),
        ("agenda", {"action": "create"}, "WRITE_EXTERNAL"),
        ("agenda", {"action": "sync", "provider": "ics"}, "WRITE_LOCAL"),
        ("image", None, "SIDE_EFFECT_LOCAL"),
        ("earth", {"action": "dump"}, "READ"),
    ]
    for name, args, expected in cases:
        assert evaluate_capability(name, args) == expected
        assert capability_class(name, args) == expected


def test_evaluate_confirm_matches_registry() -> None:
    class _Stub:
        def __init__(self, name: str, risk: str = "read") -> None:
            self.name = name
            self.description = name
            self.risk = risk
            self.parameters_schema = {"type": "object", "properties": {}}

        async def run(self, **kwargs):
            raise AssertionError("not called")

    reg = ToolRegistry()
    for name, risk in (
        ("workspace", "read"),
        ("image", "side_effect"),
        ("send_sms", "side_effect"),
        ("browser", "side_effect"),
        ("vision", "side_effect"),
        ("camera", "side_effect"),
        ("earth", "read"),
        ("plot", "write"),
    ):
        reg.register(_Stub(name, risk))

    pairs = [
        ("workspace", {"action": "read"}, False),
        ("workspace", {"action": "write"}, True),
        ("image", {}, True),
        ("send_sms", {}, True),
        ("browser", {"action": "open"}, True),
        ("vision", {"path": "x.png"}, True),
        ("camera", {"action": "snapshot"}, False),
        ("earth", {"action": "dump"}, False),
        ("plot", {}, True),
        ("unknown", {}, False),
    ]
    for name, args, expected in pairs:
        tool = reg.get(name)
        risk = tool.risk if tool is not None else None
        assert evaluate_confirm(name, args, risk=risk) is expected
        assert reg.needs_confirm(name, args) is expected


def test_allow_turn_does_not_cover_send_or_agenda() -> None:
    flags = confirm_toggles_for_call(
        "workspace",
        confirm_writes=True,
        confirm_image=True,
        confirm_send=True,
        confirm_browser=True,
        confirm_vision=True,
        allow_writes_this_turn=True,
    )
    assert flags["confirm_writes"] is False
    assert flags["confirm_image"] is False
    agenda = confirm_toggles_for_call(
        "agenda",
        confirm_writes=True,
        confirm_image=True,
        confirm_send=True,
        confirm_browser=True,
        confirm_vision=True,
        allow_writes_this_turn=True,
    )
    assert agenda["confirm_writes"] is True
    assert agenda["confirm_send"] is True


def test_never_batch_and_batch_ok() -> None:
    assert not batch_ok("send_sms")
    assert not batch_ok("agenda")
    assert batch_ok("workspace")
    assert "send_email" in NEVER_BATCH


def test_attended_follows_allow_send_by_default() -> None:
    config = {"tools": {}, "agent": {}, "workspace": {"roots": ["."]}}
    jobs = build_tool_registry(config, allow_send=False)
    assert "send_sms" not in jobs.names()
    assert "vision" not in jobs.names()
    assert "tile" not in jobs.names()
    assert "image" in jobs.names()
    assert "image_edit" in jobs.names()
    assert "research_report" not in jobs.names()


def test_attended_can_differ_from_allow_send() -> None:
    """Person present, but outbound send withheld — the split's reason to exist."""
    config = {"tools": {}, "agent": {}, "workspace": {"roots": ["."]}}
    registry = build_tool_registry(config, allow_send=False, attended=True)
    assert "tile" in registry.names()
    assert "send_email" not in registry.names()
    assert "send_sms" not in registry.names()
