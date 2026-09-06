"""Pin the policy table to the confirm / capability behaviour tests already own."""

from __future__ import annotations

import pytest

from arelis.core.bus import EventBus
from arelis.core.turn_confirm import SKIP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.tools import build_tool_registry
from arelis.tools.base import NEVER_BATCH, ToolRegistry, capability_class, confirm_args_blocked
from arelis.tools.policy import (
    always_pause,
    batch_ok,
    confirm_toggles_for_call,
    evaluate_capability,
    evaluate_confirm,
    persist_confirm_off,
    persist_label,
    persist_ok,
    set_confirm_mode,
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
        ("run_script", {"path": "x.py"}, "SIDE_EFFECT_LOCAL"),
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
        ("run_script", "side_effect"),
    ):
        reg.register(_Stub(name, risk))

    pairs = [
        ("workspace", {"action": "read"}, False),
        ("workspace", {"action": "write"}, True),
        ("workspace", {"action": "keep"}, True),
        ("image", {}, True),
        ("send_sms", {}, True),
        ("browser", {"action": "open"}, True),
        ("vision", {"path": "x.png"}, True),
        ("camera", {"action": "snapshot"}, False),
        ("earth", {"action": "dump"}, False),
        ("plot", {}, True),
        ("run_script", {"path": "x.py"}, True),
        ("unknown", {}, False),
    ]
    for name, args, expected in pairs:
        tool = reg.get(name)
        risk = tool.risk if tool is not None else None
        assert evaluate_confirm(name, args, risk=risk) is expected
        assert reg.needs_confirm(name, args) is expected
    set_confirm_mode("card")
    assert evaluate_confirm("workspace", {"action": "write"}, risk="read")
    assert evaluate_confirm("send_sms", {}, risk="side_effect")
    assert evaluate_confirm("browser", {"action": "open"}, risk="side_effect")
    assert not evaluate_confirm("workspace", {"action": "read"}, risk="read")


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
    assert batch_ok("workspace", {"action": "write"})
    assert not batch_ok("workspace", {"action": "delete"})
    assert not batch_ok("run_script", {"path": "x.py"})
    assert "send_email" in NEVER_BATCH


def test_ask_is_grant_skips_local_work() -> None:
    set_confirm_mode("card")
    assert not evaluate_confirm("image", {"prompt": "x"}, asked=True)
    assert not evaluate_confirm(
        "vision", {"path": "x.png"}, asked=True, risk="side_effect"
    )
    assert not evaluate_confirm(
        "workspace", {"action": "write"}, asked=True, risk="read"
    )
    assert not evaluate_confirm(
        "browser", {"action": "open", "url": "youtube"}, asked=True, risk="side_effect"
    )
    assert evaluate_confirm("image", {"prompt": "x"}, asked=False)
    assert evaluate_confirm("send_sms", {}, asked=True)
    assert evaluate_confirm("send_email", {}, asked=True)
    assert evaluate_confirm(
        "workspace", {"action": "delete"}, asked=True, risk="read"
    )
    assert evaluate_confirm(
        "run_script", {"path": "x.py"}, asked=True, risk="side_effect"
    )
    assert evaluate_confirm("inbox", {"action": "trash"}, asked=True)
    assert evaluate_confirm(
        "browser",
        {"action": "click", "text": "Pay now"},
        asked=True,
        risk="side_effect",
    )
    assert evaluate_confirm("external_read", {"path": "C:/x"}, asked=True)


def test_ask_me_everything_restores_cards() -> None:
    set_confirm_mode("card")
    assert evaluate_confirm(
        "image", {"prompt": "x"}, asked=True, ask_is_grant=False
    )
    assert evaluate_confirm(
        "workspace",
        {"action": "write"},
        asked=True,
        ask_is_grant=False,
        risk="read",
    )


def test_always_pause_and_persist_ok() -> None:
    assert always_pause("send_sms")
    assert always_pause("run_script")
    assert always_pause("workspace", {"action": "delete"})
    assert always_pause("browser", {"action": "upload", "path": "x.csv"})
    assert not always_pause("browser", {"action": "download"})
    assert not always_pause("workspace", {"action": "write"})
    assert not always_pause("image")
    assert persist_ok("image", {})
    assert persist_label("image", {}) == "don't ask again about pictures"
    assert persist_ok("workspace", {"action": "write"})
    assert persist_label("workspace", {"action": "write"}) == (
        "don't ask again about files"
    )
    assert persist_ok("vision", {"path": "x.png"})
    assert persist_ok("browser", {"action": "open"})
    assert not persist_ok("send_sms", {})
    assert persist_label("send_sms", {}) == ""
    assert not persist_ok("workspace", {"action": "delete"})
    assert not persist_ok("run_script", {"path": "x.py"})
    assert not persist_ok("inbox", {"action": "trash"})


def test_persist_confirm_off_flips_image_toggle(tmp_path, monkeypatch) -> None:
    local = tmp_path / "config.local.yaml"
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)

    class _Loop:
        confirm_image = True
        config = {"agent": {"confirm_image": True}}

    loop = _Loop()
    assert persist_confirm_off(loop, "image", {}) == "confirm_image"
    assert loop.confirm_image is False
    assert loop.config["agent"]["confirm_image"] is False
    text = local.read_text(encoding="utf-8")
    assert "confirm_image" in text
    assert persist_confirm_off(loop, "send_sms", {}) == ""


def test_attended_follows_allow_send_by_default() -> None:
    config = {"tools": {}, "agent": {}, "workspace": {"roots": ["."]}}
    jobs = build_tool_registry(config, allow_send=False)
    assert "send_sms" not in jobs.names()
    assert "vision" not in jobs.names()
    assert "tile" not in jobs.names()
    assert "image" in jobs.names()
    assert "image_edit" in jobs.names()
    assert "research_report" not in jobs.names()
    assert "run_script" not in jobs.names()


def test_placeholder_phone_still_blocks_allow_card() -> None:
    reason = confirm_args_blocked(
        "contacts",
        {"action": "add", "name": "Wife", "phone": "<user_phone_number>"},
    )
    assert reason is not None
    assert "placeholder" in reason.lower() or "user_phone" in reason.lower()


def test_empty_workspace_write_still_blocks() -> None:
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt", "content": ""},
    )
    assert reason is not None
    assert "empty" in reason.lower()


def test_math_comparison_text_is_not_a_placeholder() -> None:
    """A homework dump with '<30 Hz ... >30 Hz' used to look like HTML tags.

    Confirm blocked the write, the 9B retried document/workspace until
    max_rounds, and the turn died with no answer after ~7 minutes.
    """
    body = (
        "At low frequencies (<30 Hz), coating thermal noise dominates. "
        "At higher frequencies (>30 Hz), quantum noise dominates.\n"
        r"$$\tilde{x}_{\text{SQL}}(f)=\frac{1}{2\pi f}\sqrt{\frac{\hbar c}{4m}}$$"
    )
    assert confirm_args_blocked("document", {"body": body, "title": "SQL"}) is None
    assert (
        confirm_args_blocked(
            "workspace",
            {"action": "write", "path": "sql.md", "content": body},
        )
        is None
    )


def test_html_document_body_is_not_a_placeholder() -> None:
    html = "<html><body><p>Turn in homework</p></body></html>"
    assert confirm_args_blocked("document", {"body": html, "format": "html"}) is None


def test_placeholder_reason_does_not_echo_the_whole_body() -> None:
    body = "<user_phone_number>\n" + ("x" * 4000)
    reason = confirm_args_blocked("document", {"body": body})
    assert reason is not None
    assert len(reason) < 200


def test_attended_can_differ_from_allow_send() -> None:
    """Person present, but outbound send withheld — the split's reason to exist."""
    config = {"tools": {}, "agent": {}, "workspace": {"roots": ["."]}}
    registry = build_tool_registry(config, allow_send=False, attended=True)
    assert "tile" in registry.names()
    assert "send_email" not in registry.names()
    assert "send_sms" not in registry.names()


class _ConfirmLoop:
    def __init__(self) -> None:
        self.bus = EventBus()
        self._trace: list[str] = []
        self._expected_tools: set[str] = set()
        self.tools_used: set[str] = set()
        self._timer = None

    def _tool_message(self, name: str, content: str) -> dict[str, str]:
        return {"role": "tool", "tool_name": name, "content": content}


@pytest.mark.asyncio
async def test_identical_blocked_write_stops_after_two_tries() -> None:
    """Confirm-blocked writes used to skip without incrementing fail_counts.

    The model then re-issued the same document body until max_rounds.
    """
    loop = _ConfirmLoop()
    ctx = TurnContext(text="derive the SQL", role="fast")
    args = {"body": "<user_phone_number> " + ("x" * 200)}
    fail_counts: dict[str, int] = {}
    messages: list[dict] = []
    seen = ""
    for _ in range(3):
        action, _, call_fp = await confirm_call(
            loop,
            ctx,
            "document",
            args,
            text="derive the SQL",
            fail_counts=fail_counts,
            skip_counts={},
            messages=messages,
            tool_names={"document"},
            drop_wander=lambda _n: None,
        )
        assert action == SKIP
        seen = call_fp
    assert fail_counts[seen] >= 2
    joined = " ".join(str(m) for m in messages)
    assert "already failed twice" in joined.lower()
    assert "Stop calling" in joined
