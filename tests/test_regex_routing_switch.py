"""agent.compensation.regex_routing. Off skips regex routing. On is today.

The model in these tests is a scripted stand-in. It never talks to a server.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from arelis.config import DEFAULT_CONFIG_PATH
from arelis.contacts import Contact, normalize_phone
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.core.prompt_sections import append_preflight_guidance
from arelis.core.tool_subset import filter_tool_names
from arelis.core.tool_surface import apply_expected, session_tool_schemas
from arelis.core.turn_dispatch import fill_round_calls
from arelis.tools.base import ToolRegistry, ToolResult

OFF: dict[str, Any] = {
    "compensation": {"regex_routing": False},
    "native_tool_calling": False,
}

# (tool name, user text, thinking line the preinject publishes)
PREINJECTS = [
    ("calculator", "what is 17-3", "inject  calculator from intent (pre-model)"),
    (
        "units",
        "what is the gravitational constant",
        "inject  units from intent (pre-model)",
    ),
    (
        "browser",
        "open https://example.com",
        "inject  browser from intent (pre-model)",
    ),
    ("tile", "show me the workspace", "inject  tile from intent (pre-model)"),
    (
        "run_script",
        "run hello_script.py",
        "inject  run_script from named script (pre-model)",
    ),
    (
        "send_sms",
        "Text Brian: Running late",
        "inject  send_sms from a complete draft (pre-model)",
    ),
    (
        "send_email",
        "email you@example.com subject: test, body: just a test",
        "inject  send_email from a complete draft (pre-model)",
    ),
    (
        "weather",
        "what's the weather in Springfield",
        "inject  weather from intent (pre-model)",
    ),
    ("agenda", "open my calendar", "inject  agenda from intent (pre-model)"),
    (
        "workspace",
        "how do you work",
        "inject  workspace from inspect ask (pre-model)",
    ),
]


class _Stub:
    def __init__(self, name: str, *, risk: str = "read") -> None:
        self.name = name
        self.description = name
        self.risk = risk
        self.parameters_schema = {"type": "object", "properties": {}}
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            ok=True,
            output=f"{self.name} ok",
            data={
                "url": "https://example.com",
                "path": "/tmp/out.png",
            },
        )


class _Router:
    """Scripted model. Extra rounds get a plain token so the turn can end."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.prompts: list[list[dict[str, Any]]] = []
        self.active_model = "mock"
        self.default_role = "fast"

    def model_for(self, role: Any = None) -> str:
        del role
        return "mock"

    async def ensure_role(self, role: Any, *, force: bool = False) -> str:
        del role, force
        return "mock"

    def mark_sticky(self, role: Any) -> None:
        del role

    def apply_sticky(self, wanted: Any, reason: str) -> tuple[Any, str]:
        return wanted, reason

    async def stream(self, role: Any, messages: list[dict[str, Any]], **kwargs: Any):
        del role, kwargs
        self.prompts.append(list(messages))
        self.i += 1
        steps = (
            self.script[self.i - 1]
            if self.i <= len(self.script)
            else [("token", "FROM_THE_MODEL")]
        )
        for item in steps:
            yield item


def _call(name: str, args: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    return (
        "tool_calls",
        [
            {
                "type": "function",
                "function": {"name": name, "arguments": dict(args)},
            }
        ],
    )


def _brian_book() -> dict[str, Contact]:
    phone = "5551112222"
    return {
        "brian": Contact(
            alias="brian",
            name="Brian",
            phone=phone,
            digits=normalize_phone(phone),
            aliases=("brian",),
        )
    }


def _thinking(events: list[Event]) -> str:
    return "\n".join(
        str(event.payload.get("text") or "")
        for event in events
        if event.type == EventType.THINKING
    )


def _prompt_text(router: _Router) -> str:
    parts: list[str] = []
    for messages in router.prompts:
        for item in messages:
            parts.append(str(item.get("content") or ""))
    return "\n".join(parts)


async def _run(
    text: str,
    names: list[str],
    script: list[list[tuple[str, Any]]],
    *,
    agent: dict[str, Any] | None = None,
) -> SimpleNamespace:
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    registry = ToolRegistry()
    stubs = {name: _Stub(name, risk="side_effect" if name.startswith("send_") else "read") for name in names}
    for stub in stubs.values():
        registry.register(stub)
    router = _Router(script)
    confirms: list[dict[str, Any]] = []

    async def confirm(_cid: str, name: str, args: dict[str, Any], _summary: str) -> str:
        confirms.append({"tool": name, "args": dict(args or {})})
        return "allow"

    cfg_agent: dict[str, Any] = {
        "max_rounds": 4,
        "tool_output_chars": 4000,
        "json_fallback": True,
        "chat_fast_path": False,
        "turn_telemetry": False,
        "exactness": True,
        "numeric_gate": True,
        "evidence_gate": True,
        "intent_preflight": True,
    }
    if agent:
        cfg_agent.update(agent)
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "You are Arelis.",
        {"agent": cfg_agent, "ollama": {"num_ctx": 8192}},
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run(text, "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return SimpleNamespace(
        events=events,
        router=router,
        confirms=confirms,
        stubs=stubs,
        thinking=_thinking(events),
    )


def test_shipped_default_yaml_regex_routing_is_true() -> None:
    """The file on disk, not a merged local config, ships the boolean true."""
    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    value = shipped["agent"]["compensation"]["regex_routing"]
    assert value is True


def test_helper_defaults_true_and_ignores_native() -> None:
    from arelis.core.compensation import regex_routing

    assert regex_routing(None) is True
    assert regex_routing({}) is True
    assert regex_routing({"compensation": {}}) is True
    assert regex_routing({"native_tool_calling": True}) is True
    assert regex_routing({"compensation": {"regex_routing": True}}) is True
    assert regex_routing({"compensation": {"regex_routing": False}}) is False
    assert regex_routing({"compensation": {"regex_routing": "false"}}) is True


def test_regex_off_does_not_change_native_schema_hints() -> None:
    """Native hints stay tied to native_tool_calling. This switch does not add them."""
    from scripts.measure_tool_schema import registry_for_profile

    plain = session_tool_schemas(registry_for_profile("worst"), {})
    regex_off = session_tool_schemas(
        registry_for_profile("worst"),
        {"compensation": {"regex_routing": False}},
    )
    native = session_tool_schemas(
        registry_for_profile("worst"),
        {"native_tool_calling": True},
    )
    both = session_tool_schemas(
        registry_for_profile("worst"),
        {
            "native_tool_calling": True,
            "compensation": {"regex_routing": False},
        },
    )
    assert regex_off == plain
    assert both == native
    assert native != plain


@pytest.mark.parametrize(("tool", "ask", "marker"), PREINJECTS)
async def test_preinject_skipped_when_regex_routing_off(
    tool: str, ask: str, marker: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scripted model answers in words. The preinject must not run first."""
    monkeypatch.setattr(
        "arelis.core.sms_complete.load_contacts", lambda: _brian_book()
    )
    ran = await _run(ask, [tool], [[("token", "FROM_THE_MODEL")]], agent=OFF)
    assert marker not in ran.thinking
    assert ran.stubs[tool].calls == []
    assert ran.router.i >= 1


async def test_missing_switch_still_preinjects_calculator() -> None:
    """No compensation block is today's path. The calculator call is armed."""
    ran = await _run(
        "what is 17-3",
        ["calculator"],
        [[("token", "FROM_THE_MODEL")]],
    )
    assert "inject  calculator from intent (pre-model)" in ran.thinking
    assert ran.stubs["calculator"].calls


def test_saved_place_tool_list_edit_skipped() -> None:
    """'where am I' must not strip earth and browser or force user_location."""
    loop = SimpleNamespace(
        _look=None,
        _expected_tools=set(),
        _timer=None,
        memory=SimpleNamespace(messages=[]),
        config={"agent": OFF},
    )
    names = {
        "earth",
        "browser",
        "web_search",
        "scrape",
        "web_fetch",
        "user_location",
        "calculator",
    }
    available, _visible = apply_expected(
        loop, set(names), text="where am I", available_all=set(names)
    )
    assert "earth" in available
    assert "browser" in available
    assert "web_search" in available
    assert "user_location" not in loop._expected_tools


def test_preflight_hints_skipped() -> None:
    """Intent hints and the routing system line stay off the model prompt."""
    messages: list[dict[str, str]] = []

    class _Loop:
        def __init__(self) -> None:
            self._expected_tools: set[str] = set()
            self._timer = None
            self.memory = SimpleNamespace(messages=[])
            self.tools = SimpleNamespace(names=lambda: {"weather", "calculator"})

    loop = _Loop()
    kinds = append_preflight_guidance(
        messages,
        loop,
        "what's the weather in Springfield",
        {**OFF, "intent_preflight": True},
        see_no_sms_redirect=frozenset(),
    )
    assert kinds == []
    assert messages == []
    assert loop._expected_tools == set()


def test_tool_list_intent_widening_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intent hints must not widen the menu. The send guard still looks once."""
    from arelis.core.preflight import detect_intents

    calls: list[int] = []
    real = detect_intents

    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr("arelis.core.tool_subset.detect_intents", _wrapped)
    visible = filter_tool_names(
        {"weather", "catalog", "calculator", "send_sms", "python"},
        role="fast",
        text="what's the weather in Paris tomorrow",
        enabled=False,
        skill_subset=True,
        agent_cfg=OFF,
    )
    # One look remains: _must_keep_full_surface, so a send is not subset away.
    # The two use_intent_routing sites do not call detect_intents.
    assert calls == [1]
    assert "send_sms" not in visible


async def test_no_call_inject_skipped() -> None:
    """A task ask the model only chats about must not get a tasks call invented."""
    ran = await _run(
        "add a task to call the dentist",
        ["tasks"],
        [[("token", "I can add that for you.")]],
        agent=OFF,
    )
    assert "inject  tasks from intent" not in ran.thinking
    assert ran.stubs["tasks"].calls == []
    assert ran.router.i >= 1


async def test_wrong_tool_redirect_skipped() -> None:
    """A browser call on a solar ask stays a browser call."""
    ran = await _run(
        "solar system status",
        ["browser", "solar"],
        [[_call("browser", {"action": "snapshot"})], [("token", "FROM_THE_MODEL")]],
        agent=OFF,
    )
    assert ran.stubs["browser"].calls
    assert ran.stubs["solar"].calls == []
    assert "redirect  browser → solar" not in ran.thinking


async def test_finish_nudges_skipped() -> None:
    """Math the model answers in words must not be forced through calculator."""
    ran = await _run(
        "what is 17-3",
        ["calculator"],
        [[("token", "14")]],
        agent=OFF,
    )
    assert ran.stubs["calculator"].calls == []
    assert "forcing tool" not in ran.thinking
    assert ran.router.i >= 1


async def test_schedule_rewrite_skipped() -> None:
    """A timer ask the model only chats about must not become a schedule call."""
    ran = await _run(
        "Every day at 7am, email me a summary of the weather.",
        ["weather", "schedule", "send_email"],
        [[("token", "FROM_THE_MODEL")]],
        agent=OFF,
    )
    assert ran.stubs["schedule"].calls == []
    assert "inject  schedule briefing from intent" not in ran.thinking
    assert ran.router.i >= 1


async def test_browser_call_rewrite_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """An invented sign-in action planted on the empty-call path stays put.

    The rewrite only sees calls added after the model said nothing. The
    plant stands in for that call so the assertion is the rewrite itself.
    """

    async def _plant(_loop: Any, _ctx: Any, scratch: Any) -> str:
        scratch.calls = [("browser", {"action": "goto_sign_in"})]
        return "none"

    monkeypatch.setattr("arelis.core.turn_round.run_inject_steps", _plant)
    ran = await _run(
        "note this down",
        ["browser"],
        [[("token", "FROM_THE_MODEL")]],
        agent=OFF,
    )
    assert ran.stubs["browser"].calls
    assert ran.stubs["browser"].calls[0].get("action") == "goto_sign_in"


async def test_plan_block_skipped() -> None:
    """A research-shaped ask does not get a keyword Plan block."""
    ran = await _run(
        "Investigate recent battery recycling and write a report",
        ["research_report", "web_search"],
        [[("token", "FROM_THE_MODEL")]],
        agent=OFF,
    )
    assert ran.router.i >= 1
    assert "Plan:" not in _prompt_text(ran.router)


class _RoleRouter:
    default_role = "fast"
    active_model = "stub"


def test_role_regex_uses_configured_default() -> None:
    """Research and file regexes do not pick the model. A research chip still does."""
    orch = Orchestrator(
        EventBus(),
        _RoleRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "workspace": {"roots": ["."]},
            "_persona_path": "persona.md",
            "agent": OFF,
        },
        SessionMemory(),
    )
    role, reason = orch.classify_role(
        "Investigate recent battery recycling and write a report"
    )
    assert role == "fast"
    assert reason == "default"
    role, reason = orch.classify_role("please edit the python file and lint it")
    assert role == "fast"
    assert reason == "default"
    chip, why = orch.classify_role("hello", "research")
    assert chip == "research"
    assert why == "chip"


async def test_desk_guide_and_tile_shortcut_skipped() -> None:
    """Hands help and a named tile go to the agent loop instead of answering first."""
    published: list[Event] = []

    async def grab(event: Event) -> None:
        published.append(event)

    orch = Orchestrator(
        EventBus(),
        _RoleRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "workspace": {"roots": ["."]},
            "_persona_path": "persona.md",
            "agent": OFF,
        },
        SessionMemory(),
    )
    orch.bus.publish = grab  # type: ignore[method-assign]
    await orch.on_voice_transcript(
        Event(EventType.VOICE_TRANSCRIPT, {"text": "how do hands work"})
    )
    assert published
    assert published[0].type == EventType.USER_MESSAGE
    published.clear()
    await orch.on_voice_transcript(
        Event(EventType.VOICE_TRANSCRIPT, {"text": "open history"})
    )
    assert published
    assert published[0].type == EventType.USER_MESSAGE


def test_fill_round_calls_regex_fills_skipped() -> None:
    """Fanout fills from the user's words stay off. The plot key alias stays."""
    loop = SimpleNamespace(
        tools=SimpleNamespace(get=lambda _name: None),
        memory=SimpleNamespace(messages=[]),
        _receipts=[],
        config={"agent": OFF},
    )
    out = fill_round_calls(
        loop,
        [
            ("weather", {"place": "Baltimore", "days": 1}),
            ("plot", {"subplots": [{"xs": [1], "ys": [2]}]}),
        ],
        text="what's the weather",
    )
    assert out[0] == ("weather", {"place": "Baltimore", "days": 1})
    assert out[1][0] == "plot"
    assert "panels" in out[1][1]
    assert "subplots" not in out[1][1]


async def test_serial_weather_arg_fill_skipped() -> None:
    """The per-call weather fill does not rewrite the model's place."""
    ran = await _run(
        "what's the weather",
        ["weather"],
        [[_call("weather", {"place": "Baltimore", "days": 1})], [("token", "FROM_THE_MODEL")]],
        agent=OFF,
    )
    assert ran.stubs["weather"].calls
    assert ran.stubs["weather"].calls[0].get("place") == "Baltimore"


async def test_dispatch_regex_arg_fills_skipped() -> None:
    """Inbox delete is not rewritten to trash from the ask."""
    ran = await _run(
        "delete the email from ada",
        ["inbox"],
        [[_call("inbox", {"action": "delete", "id": "42"})], [("token", "FROM_THE_MODEL")]],
        agent=OFF,
    )
    assert ran.stubs["inbox"].calls
    assert ran.stubs["inbox"].calls[0].get("action") == "delete"


async def test_send_sms_confirm_card_when_model_calls_with_switch_off() -> None:
    """The model calls send_sms. Allow still shows, and the body is the user's."""
    ran = await _run(
        "Text Brian: Running late",
        ["send_sms"],
        [
            [_call("send_sms", {"to": "brian", "body": "WRONG"})],
            [("token", "sent")],
        ],
        agent=OFF,
    )
    assert ran.router.i >= 1
    assert ran.confirms
    assert ran.confirms[0]["tool"] == "send_sms"
    body = str(ran.confirms[0]["args"].get("body") or "")
    assert "WRONG" not in body
    assert "late" in body.lower()


async def test_browser_errand_autofinish_skipped() -> None:
    """A finished browser open does not end the turn for the model."""
    ran = await _run(
        "open https://example.com",
        ["browser"],
        [
            [_call("browser", {"action": "open", "url": "https://example.com"})],
            [("token", "FROM_THE_MODEL")],
        ],
        agent=OFF,
    )
    assert "browser errand done; stopping" not in ran.thinking
    assert ran.router.i >= 2


async def test_image_edit_autofinish_skipped() -> None:
    """image_edit does not end the turn before the model writes it up."""
    ran = await _run(
        "brighten the picture",
        ["image_edit"],
        [
            [_call("image_edit", {"path": "/tmp/in.png"})],
            [("token", "FROM_THE_MODEL")],
        ],
        agent=OFF,
    )
    assert ran.router.i >= 2


async def test_daily_wander_hide_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A web_search the menu hid on an SMS turn is an unknown tool, not a free pass."""
    monkeypatch.setattr(
        "arelis.core.sms_complete.load_contacts", lambda: _brian_book()
    )
    ran = await _run(
        "Text Brian: Running late",
        ["send_sms", "web_search"],
        [[_call("web_search", {"query": "brian"})], [("token", "FROM_THE_MODEL")]],
        agent={**OFF, "sms_preinject": False},
    )
    assert ran.stubs["web_search"].calls == []
    assert "Unknown tool `web_search`" in ran.thinking
