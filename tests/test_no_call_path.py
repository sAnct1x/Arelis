"""Pins apply_no_call_path / dispatch_calls return contracts before the split.

These two functions are the turn coordinator. The loop tests already cover
them through AgentLoop.run. This file calls them directly so a dispatch-table
extract cannot change nudge / inject / finish without a failing name.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from arelis.core.events import Event
from arelis.core.sms_complete import SmsDraft
from arelis.core.turn_context import TurnContext
from arelis.core.turn_dispatch import dispatch_calls
from arelis.core.turn_round import _round_scratch, apply_no_call_path


class _Bus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


class _Timer:
    def mark(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeLoop:
    def __init__(self) -> None:
        self.bus = _Bus()
        self.json_fallback = True
        self._timer = _Timer()
        self.tools_used: set[str] = set()
        self._expected_tools: set[str] = set()
        self._receipts: list[Any] = []
        self._look = None
        self._active_plan = None
        self.memory = SimpleNamespace(messages=[])
        self.tools = SimpleNamespace(
            get=lambda _name: None,
            ollama_tools=lambda _names: [],
            call=self._call,
        )
        self._trace: list[str] = []
        self.finished: tuple[Any, ...] | None = None
        self.retracts = 0
        self.confirm_writes = False
        self.confirm_image = False
        self.confirm_send = False
        self.confirm_browser = False
        self.confirm_vision = False
        self.confirm_run = False

    async def _call(self, name: str, **kwargs: Any) -> Any:
        return SimpleNamespace(ok=True, output=f"{name} ok", data={})

    async def _retract(self) -> None:
        self.retracts += 1

    # Signature mirrors AgentLoop._finish exactly. A double that gives
    # `sources` a default hides a caller that forgot to pass it: the real
    # method raises TypeError while this file stays green.
    async def _finish(
        self,
        text: str,
        sources: Any,
        *,
        streamed: str = "",
        fallback_text: str = "",
    ) -> None:
        self.finished = (text, sources, streamed)

    async def _hold_if_paused(self) -> None:
        return None

    def _look_refuse(self, _content: str) -> str | None:
        return None

    def _tool_message(self, name: str, err: str) -> dict[str, str]:
        return {"role": "tool", "name": name, "content": err}


def _scratch(**overrides: Any) -> SimpleNamespace:
    base = dict(
        text="hello",
        role="fast",
        agent_cfg={
            "sms_force_call": True,
            "email_force_call": True,
            "agenda_force_call": True,
            "scrape_after_search": True,
            "json_fallback": True,
        },
        available_all={"send_sms", "web_search", "scrape"},
        available={"send_sms", "web_search", "scrape"},
        visible={"send_sms", "web_search", "scrape"},
        tool_names={"send_sms", "web_search", "scrape"},
        sources=[],
        ledger=None,
        fail_counts={},
        skip_counts={},
        web_search_ok=set(),
        page_ok=set(),
        sms_sent=set(),
        agenda_created=set(),
        weather_ok_places=set(),
        weather_days_retried=set(),
        numeric_gate=True,
        evidence_gate=True,
        research_dual=True,
        research_min_sources=2,
        exact_need=None,
        offer_tools=True,
        ollama_tools=[],
        messages=[],
        sms_preinject=None,
        sms_draft=None,
        email_draft=None,
        agenda_draft=None,
        research_mode=False,
        preflight_kinds=[],
        wants_fresh_page=False,
        active_room=None,
        content="Thanks.",
        streamed="",
        calls=[],
        tool_calls=[],
        round_ms=1,
        model="qwen",
    )
    from arelis.core.claims import ExactnessNeed
    from arelis.core.evidence import EvidenceLedger

    if overrides.get("exact_need") is None and "exact_need" not in overrides:
        base["exact_need"] = ExactnessNeed(False, False, False, False)
    if overrides.get("ledger") is None and "ledger" not in overrides:
        base["ledger"] = EvidenceLedger()
    base.update(overrides)
    return _round_scratch(**base)


def _ctx(**overrides: Any) -> TurnContext:
    ctx = TurnContext(text=str(overrides.pop("text", "hello")), role="fast")  # type: ignore[arg-type]
    for key, value in overrides.items():
        setattr(ctx, key, value)
    if not ctx.tool_names:
        ctx.tool_names = {"send_sms", "web_search", "scrape"}
    return ctx


@pytest.mark.asyncio
async def test_prose_tool_call_asks_for_a_real_one() -> None:
    loop = _FakeLoop()
    r = _scratch(content='{"tool":"send_sms","args":{"to":"brian","body":"hi"}}')
    ctx = _ctx()
    assert await apply_no_call_path(loop, ctx, r, 0) is False
    assert ctx.nudges == 1
    thinking = " ".join(str(e.payload.get("text") or "") for e in loop.bus.events)
    assert "written as prose" in thinking


@pytest.mark.asyncio
async def test_empty_after_tool_finishes_from_the_result() -> None:
    loop = _FakeLoop()
    r = _scratch(content="")
    ctx = _ctx()
    ctx.last_ok_tool_out = "It is 72 degrees."
    ctx.last_ok_tool_name = "weather"
    assert await apply_no_call_path(loop, ctx, r, 0) is True
    assert loop.finished is not None
    assert "72" in str(loop.finished[0])


@pytest.mark.asyncio
async def test_sms_draft_nudges_once_then_injects() -> None:
    draft = SmsDraft(to="brian", body="Running late", alias="brian")
    loop = _FakeLoop()
    r = _scratch(sms_draft=draft, content="Sure.")
    ctx = _ctx()
    ctx.sms_draft = draft
    assert await apply_no_call_path(loop, ctx, r, 0) is False
    assert ctx.sms_nudge_used == 1

    r2 = _scratch(sms_draft=draft, content="Sure.")
    ctx2 = _ctx()
    ctx2.sms_draft = draft
    ctx2.sms_nudge_used = 1
    assert await apply_no_call_path(loop, ctx2, r2, 1) is None
    assert r2.calls and r2.calls[0][0] == "send_sms"


@pytest.mark.asyncio
async def test_plain_thanks_finishes_the_turn() -> None:
    loop = _FakeLoop()
    r = _scratch(content="You're welcome.")
    ctx = _ctx()
    assert await apply_no_call_path(loop, ctx, r, 0) is True
    assert loop.finished is not None
    assert loop.finished[0] == "You're welcome."


@pytest.mark.asyncio
async def test_scrape_after_search_asks_for_a_page() -> None:
    loop = _FakeLoop()
    loop.tools_used = {"web_search"}
    r = _scratch(content="Here are some links.", wants_fresh_page=True)
    ctx = _ctx()
    ctx.wants_fresh_page = True
    assert await apply_no_call_path(loop, ctx, r, 0) is False
    assert ctx.scrape_nudge_used is True


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_dispatch_same_browser_url_finishes_an_open_ask() -> None:
    from arelis.core.same_call import record_same_call
    from arelis.core.turn_goal import derive_turn_goal

    loop = _FakeLoop()
    args = {"action": "navigate", "url": "https://x.com/login"}
    r = _scratch(
        text="go to x.com and take me to the login page if not signed in",
        calls=[("browser", args)],
        tool_calls=[],
        content="",
        streamed="",
        tool_names={"browser"},
    )
    ctx = _ctx(text="go to x.com and take me to the login page if not signed in")
    ctx.tool_names = {"browser"}
    ctx.goal = derive_turn_goal(ctx.text, kinds=["browser"])
    record_same_call(ctx.same_ok, "browser", args)
    assert await dispatch_calls(loop, ctx, r, 2) is True
    assert loop.finished is not None
    assert "signed in" in str(loop.finished[0]).lower()
    assert "browser same call blocked" in loop._trace


@pytest.mark.asyncio
async def test_dispatch_second_same_call_skip_finishes() -> None:
    from arelis.core.same_call import record_same_call, same_call_key

    loop = _FakeLoop()
    args = {"action": "list", "path": "."}
    r = _scratch(
        calls=[("workspace", args)],
        tool_calls=[],
        content="",
        streamed="",
        tool_names={"workspace"},
    )
    ctx = _ctx()
    ctx.tool_names = {"workspace"}
    r.tool_names = {"workspace"}
    record_same_call(ctx.same_ok, "workspace", args)
    key = same_call_key("workspace", args)
    assert key
    ctx.same_skip_keys.add(key)
    ctx.last_ok_tool_out = "listed 3 files"
    ctx.last_ok_tool_name = "workspace"
    assert await dispatch_calls(loop, ctx, r, 3) is True
    assert loop.finished is not None
    assert "listed 3 files" in str(loop.finished[0])
    assert "already have that result" not in str(loop.finished[0]).lower()


@pytest.mark.asyncio
async def test_dispatch_cas_same_call_strips_tools_for_a_writeup() -> None:
    from arelis.core.same_call import record_same_call

    loop = _FakeLoop()
    args = {"action": "diff", "expr": "1/(x**2-1)", "n": 50, "at": "0"}
    r = _scratch(
        calls=[("cas", args)],
        tool_calls=[],
        content="",
        streamed="",
        tool_names={"cas"},
        offer_tools=True,
        messages=[],
    )
    ctx = _ctx()
    ctx.tool_names = {"cas"}
    ctx.offer_tools = True
    ctx.last_ok_tool_out = "diff(...) =\n-factorial(50)"
    ctx.last_ok_tool_name = "cas"
    record_same_call(ctx.same_ok, "cas", args)
    assert await dispatch_calls(loop, ctx, r, 2) is False
    assert loop.finished is None
    assert ctx.algebra_write_nudge_used is True
    assert ctx.offer_tools is False
    assert "cas same call blocked" in loop._trace
    thinking = " ".join(str(e.payload.get("text") or "") for e in loop.bus.events)
    assert "same-call algebra; asking for a write-up" in thinking
    assert any(
        m.get("role") == "user" and "Write the chat line" in str(m.get("content") or "")
        for m in r.messages
    )


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_does_not_end_the_turn() -> None:
    loop = _FakeLoop()
    r = _scratch(
        calls=[("not_a_tool", {})],
        tool_calls=[],
        content="",
        streamed="",
    )
    ctx = _ctx()
    ctx.tool_names = {"send_sms"}
    r.tool_names = {"send_sms"}
    assert await dispatch_calls(loop, ctx, r, 0) is False
    thinking = " ".join(str(e.payload.get("text") or "") for e in loop.bus.events)
    assert "reject" in thinking


def test_fill_round_calls_bumps_weather_days() -> None:
    from arelis.core.turn_dispatch import fill_round_calls

    loop = _FakeLoop()
    filled = fill_round_calls(
        loop,
        [
            ("weather", {"place": "Austin"}),
            ("weather", {"place": "Dallas"}),
        ],
        text="what's the weather tomorrow in Austin and Dallas",
    )
    assert filled[0][1].get("days") == 3
    assert filled[1][1].get("days") == 3
    assert filled[0][1].get("place") == "Austin"


@pytest.mark.asyncio
async def test_show_all_goals_does_not_inject_remove() -> None:
    loop = _FakeLoop()
    loop._expected_tools = {"goals"}
    loop._receipts = [{"tool": "goals", "action": "goals.list", "ids": ["1", "2"]}]
    r = _scratch(
        text="show all my goals",
        content="Sure.",
        tool_names={"goals"},
        available={"goals"},
        visible={"goals"},
        available_all={"goals"},
    )
    ctx = _ctx(text="show all my goals")
    ctx.tool_names = {"goals"}
    hit = await apply_no_call_path(loop, ctx, r, 0)
    assert hit is None
    assert r.calls
    assert all(args.get("action") != "remove" for _name, args in r.calls)


def test_fake_loop_finish_matches_the_real_signature() -> None:
    """The double must never accept more than AgentLoop._finish does.

    turn_round called _finish with the text alone and no sources. The real
    method takes sources positionally and would have raised TypeError, but
    this file's fake defaulted it to None, so the arity drift was invisible
    to the one test module whose job is pinning that contract.
    """
    from arelis.core.agent_loop import AgentLoop

    def shape(fn: Any) -> list[tuple[str, Any, bool]]:
        return [
            (p.name, p.kind, p.default is inspect.Parameter.empty)
            for p in inspect.signature(fn).parameters.values()
        ]

    assert shape(_FakeLoop._finish) == shape(AgentLoop._finish)


def test_dispatch_tables_are_named_and_ordered() -> None:
    """The extract must keep a table, not hide the chain in one blob."""
    from arelis.core import call_redirects, no_call_finish, no_call_steps

    assert len(no_call_steps.INJECT_STEPS) >= 8
    assert all(callable(step) for step in no_call_steps.INJECT_STEPS)
    assert len(no_call_finish.FINISH_STEPS) >= 6
    assert len(call_redirects.REDIRECT_STEPS) >= 4
    assert all(callable(step) for step in call_redirects.REDIRECT_STEPS)

