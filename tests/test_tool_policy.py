"""Pin the policy table to the confirm / capability behaviour tests already own."""

from __future__ import annotations

import asyncio
import itertools

import pytest

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _ScriptedRouter, foundation_registry
from arelis.tools.base import ToolRegistry
from arelis.tools.policy import (
    DELETE_ACTIONS,
    confirm_mode,
    evaluate_confirm,
    persist_confirm_off,
    set_confirm_mode,
)
from arelis.ui.theme import THEME_IDS, apply_theme

# Voice-mode themes. The send floor applies here too. The drift guard
# below still pins this set to filament.
FLOOR_EXEMPT_THEMES = frozenset({"filament"})

_TOGGLE_KEYS = (
    "confirm_writes",
    "confirm_send",
    "confirm_image",
    "confirm_browser",
    "confirm_vision",
    "confirm_run",
)


def _floor_calls() -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = [("send_email", {}), ("send_sms", {})]
    for tool, actions in DELETE_ACTIONS.items():
        action = sorted(actions)[0]
        calls.append((tool, {"action": action}))
    calls.append(("web_fetch", {"method": "DELETE"}))
    return calls


def _toggle_flag_sets() -> list[dict[str, bool]]:
    out: list[dict[str, bool]] = []
    for bits in itertools.product((True, False), repeat=len(_TOGGLE_KEYS)):
        out.append(dict(zip(_TOGGLE_KEYS, bits, strict=True)))
    return out


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
        ("run_task", "side_effect"),
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
        ("camera", {"action": "snapshot"}, True),
        ("earth", {"action": "dump"}, False),
        ("plot", {}, True),
        ("run_script", {"path": "x.py"}, True),
        ("run_task", {"action": "run", "name": "pytest"}, True),
        ("run_task", {"action": "list"}, False),
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


class _ConfirmLoop:
    def __init__(self) -> None:
        self.bus = EventBus()
        self._trace: list[str] = []
        self._expected_tools: set[str] = set()
        self.tools_used: set[str] = set()
        self._timer = None

    def _tool_message(self, name: str, content: str) -> dict[str, str]:
        return {"role": "tool", "tool_name": name, "content": content}


def test_theme_confirm_mode_drift_guard() -> None:
    covered = [t for t in THEME_IDS if t not in FLOOR_EXEMPT_THEMES]
    try:
        for theme_id in THEME_IDS:
            apply_theme(theme_id)
            expected = "voice" if theme_id in FLOOR_EXEMPT_THEMES else "card"
            assert confirm_mode() == expected
        assert FLOOR_EXEMPT_THEMES == {"filament"}
        assert FLOOR_EXEMPT_THEMES <= set(THEME_IDS)
        assert "sodium" in covered
        assert "night" in covered
    finally:
        apply_theme("sodium")


@pytest.mark.asyncio
async def test_scripted_send_sms_confirms_when_send_toggle_off() -> None:
    apply_theme("sodium")
    confirms: list[str] = []

    async def _count_confirm(_cid: str, name: str, _args: dict, _summary: str) -> str:
        confirms.append(name)
        return "allow"

    full = foundation_registry()
    tools = ToolRegistry()
    sms = full.get("send_sms")
    assert sms is not None
    tools.register(sms)
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "send_sms",
                            "arguments": {"to": "wife", "body": "hello"},
                        },
                    }
                ],
            )
        ],
        [("token", "sent.")],
    ]
    bus = EventBus()
    loop = AgentLoop(
        bus,
        _ScriptedRouter(script),
        tools,
        SessionMemory(),
        persona="You are Arelis under eval.",
        config={
            "agent": {
                "max_rounds": 6,
                "exactness": True,
                "numeric_gate": True,
                "evidence_gate": True,
                "confirm_send": False,
            },
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_count_confirm,
        is_cancelled=lambda: False,
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run("text wife hello", "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
    assert confirms == ["send_sms"]


@pytest.mark.asyncio
async def test_model_send_email_still_confirms_and_locks_the_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model calls send_email. Allow shows the user's subject and body."""
    from arelis.contacts import Contact
    from arelis.tools.policy import describe_call

    book = {
        "brian": Contact(
            alias="brian",
            name="Brian",
            phone="",
            digits="",
            email="brian@example.com",
            aliases=("brian",),
        )
    }
    monkeypatch.setattr("arelis.core.email_complete.load_contacts", lambda: book)
    apply_theme("sodium")
    confirms: list[dict] = []

    async def _keep(_cid: str, name: str, args: dict, summary: str) -> str:
        confirms.append(
            {"tool": name, "args": dict(args or {}), "summary": summary}
        )
        return "allow"

    full = foundation_registry()
    tools = ToolRegistry()
    email = full.get("send_email")
    assert email is not None
    tools.register(email)
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "send_email",
                            "arguments": {
                                "to": "other@evil.test",
                                "subject": "Totally different",
                                "body": "Model invention",
                            },
                        },
                    }
                ],
            )
        ],
        [("token", "sent.")],
    ]
    bus = EventBus()
    loop = AgentLoop(
        bus,
        _ScriptedRouter(script),
        tools,
        SessionMemory(),
        persona="You are Arelis under eval.",
        config={
            "agent": {
                "max_rounds": 4,
                "exactness": True,
                "numeric_gate": True,
                "evidence_gate": True,
                "chat_fast_path": False,
            },
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_keep,
        is_cancelled=lambda: False,
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(
            "Email Brian about Running late: Stuck in traffic",
            "fast",
            source="eval",
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
    assert confirms
    assert confirms[0]["tool"] == "send_email"
    args = confirms[0]["args"]
    assert args.get("subject") == "Running late"
    assert args.get("body") == "Stuck in traffic"
    assert "Totally different" not in str(args.get("subject") or "")
    assert "Model invention" not in str(args.get("body") or "")
    card = describe_call("send_email", args)
    assert "Running late" in card
    assert "Stuck in traffic" in card
    assert "Totally different" not in card
    assert "Model invention" not in card
