"""The round scratch is a real object, and the coordinators write through it.

Roadmap 3.16 / 3.17. ``apply_no_call_path`` and ``dispatch_calls`` each
unpacked 39 locals from a ``SimpleNamespace`` and copied all 39 back in a
``finally``, so an early return still handed the next stage what this one
decided. Two things were wrong with that. A misspelled field was a *new*
attribute and a silently dropped write, and the copy-back was 39 lines that
had to stay in step with a field list nobody could see.

Every test here drives a caller — ``run_round``, ``apply_no_call_path``,
``dispatch_calls`` — rather than the field object, because the claim being
pinned is always "the next stage sees it", not "the setter set it".
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.agent_loop import _native_tool_call
from arelis.core.email_complete import complete_email_draft
from arelis.core.intent_catalog import (
    RUN_SCRIPT,
    inspect_read_path,
    looks_like_source_inspect,
    run_script_path,
)
from arelis.core.preflight import draft_browser_args
from arelis.core.sms_complete import complete_sms_draft
from arelis.core.tile_complete import tile_tool_args
from arelis.core.turn_dispatch import dispatch_calls
from arelis.core.turn_prepare import (
    _prepare_agenda_first_move,
    _prepare_browser_first_move,
    _prepare_calculator_first_move,
    _prepare_email_first_move,
    _prepare_inspect_first_move,
    _prepare_run_script_first_move,
    _prepare_sms_first_move,
    _prepare_tile_first_move,
    _prepare_units_first_move,
    _prepare_weather_first_move,
)
from arelis.core.turn_round import apply_no_call_path, run_round
from arelis.core.turn_scratch import FIELD_NAMES
from arelis.science.constants import lookup_constant
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

# Every module that reads or writes the scratch by name.
PIPELINE = (
    "arelis/core/turn_round.py",
    "arelis/core/turn_dispatch.py",
    "arelis/core/turn_execute.py",
    "arelis/core/no_call_steps.py",
    "arelis/core/no_call_finish.py",
    "arelis/core/call_redirects.py",
)


def _augment(loop: _FakeLoop) -> _FakeLoop:
    """Fill in the loop surface confirm/execute need and the shared fake lacks."""
    loop._timer = None
    loop.max_rounds = 3
    loop._default_max_rounds = 3
    loop.tool_output_chars = 4000
    loop._fail_replan_used = False
    loop.confirm_desktop = False
    loop.config = {}
    loop.tools.needs_confirm = lambda *a, **k: False
    loop.tools.summarize_call = lambda name, args: f"{name} {sorted(args)}"
    loop.tools.ollama_tools = lambda names: sorted(str(n) for n in names)
    return loop


class _RoundLoop(_FakeLoop):
    """Enough AgentLoop to run one whole round without a model."""

    def __init__(self, *, stream_calls: Any = (), content: str = "") -> None:
        super().__init__()
        _augment(self)
        self._turn_role = "fast"
        self.router = SimpleNamespace(model_for=lambda _role: "qwen")
        self._stream_calls = list(stream_calls)
        self._stream_content = content
        self.errors: list[tuple[str, str]] = []
        # Registry.call takes the tool name positional-only. A units payload
        # also has a "name" argument; the shared fake would collide.
        self.tools.call = self._call_tool

    async def _call_tool(self, name: str, /, **kwargs: Any) -> Any:
        return SimpleNamespace(ok=True, output=f"{name} ok", data={})

    async def _maybe_escalate(self, text: str, *, round_i: int, agent_cfg: Any) -> bool:
        return False

    async def _stream_round(
        self,
        role: Any,
        messages: Any,
        tools_arg: Any,
        *,
        round_n: int,
        expect_tools: bool,
    ) -> tuple[str, list[dict[str, Any]], str]:
        return (
            self._stream_content,
            [_native_tool_call(n, a) for n, a in self._stream_calls],
            "",
        )

    async def _publish_error(self, chat: str, *, detail: str = "") -> None:
        self.errors.append((chat, detail))


def test_a_misspelled_field_raises_instead_of_vanishing() -> None:
    """The reason this is a dataclass at all.

    ``r.ollama_tolls = []`` on a SimpleNamespace is a new attribute: the
    write lands nowhere the round reads, the tool array stays on the menu,
    and nothing anywhere says so.
    """
    r = _scratch()
    with pytest.raises(AttributeError):
        r.ollama_tolls = []  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        _ = r.wants_fresh_pages  # type: ignore[attr-defined]
    assert r.ollama_tools == []


def test_every_field_the_pipeline_touches_is_declared() -> None:
    """A step cannot grow a field the scratch does not have.

    Reads are the half a typo'd *write* no longer hides: `r.foo` raising in
    `try_weather` is a crashed turn, not a quiet skip. Pin the set both ways
    so a new field has to be declared, and a dead one has to be removed.
    """
    touched: set[str] = set()
    for rel in PIPELINE:
        tree = ast.parse(Path(rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "r"
            ):
                touched.add(node.attr)

    assert touched, "the scan found nothing; the attribute shape must have changed"
    assert touched - set(FIELD_NAMES) == set()
    assert set(FIELD_NAMES) - touched == set()


@pytest.mark.asyncio
async def test_a_page_nudge_takes_the_schemas_away_before_it_can_be_interrupted() -> None:
    """What the ``finally`` used to buy, and what has to survive without it.

    ``_retract`` talks to the UI and can raise (``_StoppedError`` when they
    hit stop mid-nudge). The decision to pull the tool array is already made
    at that point, and losing it means the next round offers the same tools
    and the 7B re-calls scrape instead of writing the answer.
    """
    loop = _FakeLoop()

    async def _boom() -> None:
        raise RuntimeError("they hit stop")

    loop._retract = _boom  # type: ignore[method-assign]
    r = _scratch(content="", ollama_tools=[{"name": "scrape"}])
    ctx = _ctx()
    ctx.tool_names = {"scrape"}
    r.tool_names = ctx.tool_names
    ctx.ollama_tools = [{"name": "scrape"}]
    ctx.last_ok_tool_name = "scrape"
    ctx.last_ok_tool_out = "x" * 3000

    with pytest.raises(RuntimeError):
        await apply_no_call_path(loop, ctx, r, 0)

    assert ctx.page_write_nudge_used is True
    assert r.offer_tools is False
    assert r.ollama_tools == []
    assert not r.tool_names
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert not ctx.tool_names


@pytest.mark.asyncio
async def test_a_blocked_cas_repeat_strips_both_copies_of_the_surface() -> None:
    """dispatch's own strip. ``r`` drives this round, ``ctx`` the next one."""
    from arelis.core.same_call import record_same_call

    loop = _augment(_FakeLoop())
    args = {"action": "diff", "expr": "1/(x**2-1)", "n": 50, "at": "0"}
    ctx = _ctx()
    ctx.tool_names = {"cas"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "cas"}]
    r = _scratch(
        calls=[("cas", args)],
        content="",
        streamed="",
        tool_names=ctx.tool_names,
        offer_tools=True,
        ollama_tools=[{"name": "cas"}],
    )
    record_same_call(ctx.same_ok, "cas", args)

    assert await dispatch_calls(loop, ctx, r, 2) is False
    assert r.offer_tools is False
    assert r.ollama_tools == []
    assert not r.tool_names
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert not ctx.tool_names


@pytest.mark.asyncio
async def test_a_wander_redirect_narrows_the_surface_even_when_the_tool_explodes() -> None:
    """``_drop_wander`` has to land on the scratch, not on a local.

    It used to rebind four ``nonlocal`` names that only reached ``r`` in the
    ``finally``. A tool that raises is the case that tells the two apart:
    the hide already happened, and the round must not offer web_search again.
    The fixture is ``redirect_agenda``: a close that calls web_search is
    rewritten to agenda, which then raises.
    """
    loop = _augment(_FakeLoop())
    loop._expected_tools = {"agenda"}

    async def _boom(_name: str, **_kwargs: Any) -> Any:
        raise RuntimeError("agenda close failed")

    loop.tools.call = _boom
    text = "close the calendar"
    ctx = _ctx(text=text)
    ctx.tool_names = {"agenda", "web_search"}
    r = _scratch(
        text=text,
        calls=[("web_search", {"query": "calendar"})],
        content="",
        streamed="",
        tool_names=ctx.tool_names,
        available={"agenda", "web_search"},
        visible={"agenda", "web_search"},
        available_all={"agenda", "web_search"},
    )

    with pytest.raises(RuntimeError):
        await dispatch_calls(loop, ctx, r, 1)

    assert r.available == {"agenda"}
    assert r.visible == {"agenda"}
    assert r.tool_names == {"agenda"}
    # Schema bytes stay the list from the start of the round. The hide
    # is the names above; a later call misses tool_names.
    assert r.ollama_tools == []


@pytest.mark.asyncio
async def test_a_no_call_inject_actually_runs_the_tool_it_invented() -> None:
    """``apply_no_call_path`` returning None means dispatch reads ``r.calls``.

    The inject steps fill the calls; the coordinator that returns None does
    not touch them again. Asserting on ``r.calls`` alone would not notice a
    hand-off that dropped them, so drive the whole round and look for the
    tool in ``tools_used``.
    """
    loop = _RoundLoop(content="Sure, here are your goals.")
    loop._expected_tools = {"goals"}
    ctx = _ctx(text="show me my goals")
    ctx.tool_names = {"goals"}
    ctx.available = {"goals"}
    ctx.visible = {"goals"}
    ctx.available_all = {"goals"}

    await run_round(loop, ctx, 1)
    assert "goals" in loop.tools_used, "the injected call never reached dispatch"


@pytest.mark.asyncio
async def test_a_fanned_out_read_runs_the_filled_arguments() -> None:
    """``fill_round_calls`` only matters on the fanout path, so test it there.

    Started as a hole. ``test_fill_round_calls_bumps_weather_days`` drives the
    helper and nothing drove the caller, and every tool the helper fills is
    filled a second time inside the per-call loop — so dropping the
    ``r.calls =`` write changed nothing any test looked at. Fanout calls the
    tools *before* that loop: unfilled there means a one-day reading answered
    as a forecast, with a filled call recorded against it.
    """
    seen: list[dict[str, Any]] = []

    loop = _augment(_FakeLoop())

    async def _record(name: str, **kwargs: Any) -> Any:
        seen.append({"tool": name, **kwargs})
        return SimpleNamespace(ok=True, output=f"{name} ok", data={})

    loop.tools.call = _record
    text = "what's the weather tomorrow in Austin and Dallas"
    ctx = _ctx(text=text)
    ctx.tool_names = {"weather"}
    r = _scratch(
        text=text,
        calls=[("weather", {"place": "Austin"}), ("weather", {"place": "Dallas"})],
        content="",
        streamed="",
        tool_names=ctx.tool_names,
    )

    await dispatch_calls(loop, ctx, r, 1)

    assert len(seen) == 2, "precondition: both reads fan out in one batch"
    assert [c.get("days") for c in seen] == [3, 3]


@pytest.mark.asyncio
async def test_a_js_shell_failure_mid_loop_leaves_the_browser_visible() -> None:
    """``execute_call`` widens the surface, and the round has to keep it.

    Started as a hole. The finish-step version of this is covered below, but
    the *execute* version — a scrape that comes back "this page is a JS
    shell" — writes the same widening from inside the tool loop, and nothing
    asserted the round still had it afterwards.
    """
    loop = _augment(_FakeLoop())

    async def _js_shell(name: str, **kwargs: Any) -> Any:
        return SimpleNamespace(
            ok=False,
            output="that page renders client-side",
            data={"fail_class": "fail:js_shell", "url": "https://x.com/feed"},
        )

    loop.tools.call = _js_shell
    ctx = _ctx()
    ctx.tool_names = {"scrape"}
    r = _scratch(
        calls=[("scrape", {"url": "https://x.com/feed"})],
        content="",
        streamed="",
        tool_names=ctx.tool_names,
        available={"scrape"},
        visible={"scrape"},
        available_all={"scrape", "browser"},
    )

    assert await dispatch_calls(loop, ctx, r, 1) is False
    assert ctx.js_shell_url == "https://x.com/feed"
    assert "browser" in r.visible
    assert "browser" in r.available
    assert "browser" in r.tool_names


@pytest.mark.asyncio
async def test_a_js_shell_page_puts_the_browser_back_on_the_menu() -> None:
    """A finish step widens the surface; the widening has to outlive the step."""
    loop = _FakeLoop()
    ctx = _ctx()
    ctx.tool_names = {"web_search", "scrape"}
    ctx.js_shell_url = "https://x.com/feed"
    r = _scratch(
        content="Nothing on that page.",
        available_all={"browser", "web_search", "scrape"},
        available={"web_search", "scrape"},
        visible={"web_search", "scrape"},
        tool_names=ctx.tool_names,
    )

    assert await apply_no_call_path(loop, ctx, r, 1) is False
    assert "browser" in r.visible
    assert "browser" in r.available
    assert "browser" in r.tool_names
    assert "browser" in ctx.tool_names


@pytest.mark.asyncio
async def test_run_round_hands_the_next_round_the_narrowed_surface() -> None:
    """The whole chain: model call -> redirect -> drop -> scratch -> ctx.

    ``run_round`` is where the round's surface becomes the *turn's* surface.
    A field that stops being carried out of the scratch here is a room's
    skills surviving round one and not round two.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "calendar"})])
    loop._expected_tools = {"agenda"}
    text = "close the calendar"
    ctx = _ctx(text=text)
    ctx.tool_names = {"agenda", "web_search"}
    ctx.available = {"agenda", "web_search"}
    ctx.visible = {"agenda", "web_search"}
    ctx.available_all = {"agenda", "web_search"}
    ctx.ollama_tools = [{"name": "agenda"}, {"name": "web_search"}]

    assert await run_round(loop, ctx, 1) is False
    assert "agenda" in loop.tools_used
    assert ctx.available == {"agenda"}
    assert ctx.visible == {"agenda"}
    assert ctx.tool_names == {"agenda"}
    # Schema bytes stay the list from the start of the round. The hide
    # is the names above; a later call misses tool_names.
    assert ctx.ollama_tools == [{"name": "agenda"}, {"name": "web_search"}]


@pytest.mark.asyncio
async def test_a_raise_mid_round_still_hands_ctx_the_narrowed_surface() -> None:
    """The write-back used to snapshot locals *before* dispatch.

    ``_drop_wander`` lands on the scratch. If the tool then explodes,
    ``dispatch_calls`` never returns, and a ``finally`` that wrote the
    locals from the *start* of the round would put web_search back on
    ``ctx``. Next round offers it again. The explode-on-``r`` test below
    does not catch that — it never goes through ``run_round``.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "calendar"})])
    loop._expected_tools = {"agenda"}

    async def _boom(_name: str, **_kwargs: Any) -> Any:
        raise RuntimeError("agenda close failed")

    loop.tools.call = _boom  # type: ignore[method-assign]
    text = "close the calendar"
    ctx = _ctx(text=text)
    ctx.tool_names = {"agenda", "web_search"}
    ctx.available = {"agenda", "web_search"}
    ctx.visible = {"agenda", "web_search"}
    ctx.available_all = {"agenda", "web_search"}
    ctx.ollama_tools = [{"name": "agenda"}, {"name": "web_search"}]

    with pytest.raises(RuntimeError, match="agenda close failed"):
        await run_round(loop, ctx, 1)

    assert ctx.available == {"agenda"}
    assert ctx.visible == {"agenda"}
    assert ctx.tool_names == {"agenda"}


@pytest.mark.asyncio
async def test_a_preinjected_sms_is_spent_by_the_round_that_sends_it() -> None:
    """``sms_preinject`` is a one-shot, and the clearing rides on the scratch.

    Leaving it on ``ctx`` is a second text to the same person on round two,
    which is the failure the draft lock exists to stop.
    """
    loop = _RoundLoop()
    ctx = _ctx(text="text brian that I'm running late")
    ctx.tool_names = {"send_sms"}
    ctx.available = {"send_sms"}
    ctx.visible = {"send_sms"}
    ctx.available_all = {"send_sms"}
    ctx.sms_preinject = {"to": "brian", "body": "Running late"}

    await run_round(loop, ctx, 1)
    assert ctx.sms_preinject is None
    assert "send_sms" in loop.tools_used


@pytest.mark.asyncio
async def test_round_two_after_a_preinjected_sms_offers_no_tools() -> None:
    """A successful preinjected send is the answer. Round two gets no tools.

    Same payload as the spend test. This does not script a second text.
    """
    loop = _RoundLoop()
    ctx = _ctx(text="text brian that I'm running late")
    ctx.tool_names = {"send_sms"}
    ctx.available = {"send_sms"}
    ctx.visible = {"send_sms"}
    ctx.available_all = {"send_sms"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "send_sms"}]
    ctx.sms_preinject = {"to": "brian", "body": "Running late"}

    await run_round(loop, ctx, 1)
    assert ctx.sms_preinject is None
    assert "send_sms" in loop.tools_used

    await run_round(loop, ctx, 2)
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


@pytest.mark.asyncio
async def test_a_preinjected_weather_is_spent_by_the_round_that_calls_it() -> None:
    """``weather_preinject`` is a one-shot, and the clearing rides on the scratch.

    Leaving it on ``ctx`` is a second forecast on round two. The route
    already drafted the call; this round spends it and does not ask the model.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "austin weather"})])
    ctx = _ctx(text="what's the weather in austin")
    ctx.tool_names = {"weather", "web_search"}
    ctx.available = {"weather", "web_search"}
    ctx.visible = {"weather", "web_search"}
    ctx.available_all = {"weather", "web_search"}
    ctx.weather_preinject = {"days": 3, "place": "Austin"}

    await run_round(loop, ctx, 1)
    assert ctx.weather_preinject is None
    assert "weather" in loop.tools_used
    assert "web_search" not in loop.tools_used


def test_open_and_a_today_read_arm_agenda_and_a_create_does_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    Phrases are the ones ``tests/test_agenda_complete.py`` already treats
    as an open, a today read, and a create.
    """
    opened = _ctx(text="open my calendar")
    opened.tool_names = {"agenda", "web_search"}
    _prepare_agenda_first_move(opened, "open my calendar", {})
    assert opened.agenda_preinject == {"action": "open"}

    today = _ctx(text="what is on my calendar today")
    today.tool_names = {"agenda", "web_search"}
    _prepare_agenda_first_move(today, "what is on my calendar today", {})
    assert today.agenda_preinject == {"action": "today"}

    created = _ctx(text="add a calendar event called Dentist, tomorrow at 3pm")
    created.tool_names = {"agenda", "web_search"}
    _prepare_agenda_first_move(
        created,
        "add a calendar event called Dentist, tomorrow at 3pm",
        {},
    )
    assert created.agenda_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_agenda_is_spent_by_the_round_that_calls_it() -> None:
    """``agenda_preinject`` is a one-shot, and the clearing rides on the scratch.

    Leaving it on ``ctx`` is a second open on round two. The route already
    drafted the call; this round spends it and does not ask the model.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "my calendar"})])
    ctx = _ctx(text="open my calendar")
    ctx.tool_names = {"agenda", "web_search"}
    ctx.available = {"agenda", "web_search"}
    ctx.visible = {"agenda", "web_search"}
    ctx.available_all = {"agenda", "web_search"}
    ctx.agenda_preinject = {"action": "open"}

    await run_round(loop, ctx, 1)
    assert ctx.agenda_preinject is None
    assert "agenda" in loop.tools_used
    assert "web_search" not in loop.tools_used
    assert ctx.agenda_open_read_ok is True
    assert ctx.offer_tools is True

    await run_round(loop, ctx, 2)
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


def test_the_scratch_carries_no_field_the_turn_context_cannot_supply() -> None:
    """``run_round`` builds the scratch straight off ``ctx``.

    Nothing here is clever — it is the check that a field added to the
    scratch got a source, instead of defaulting to whatever the last round
    left behind.
    """
    built = re.findall(
        r"^\s{12}(\w+)=", Path("arelis/core/turn_round.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert set(FIELD_NAMES) <= set(built)


def test_a_math_ask_arms_calculator_and_units_a_constant_and_a_create_do_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    ``what is 17-3`` is the arithmetic ``detect_math_ask`` already accepts.
    ``how many feet in 3 meters`` is a units ask. The constant and the
    calendar create are not a calculator call.
    """
    armed = _ctx(text="what is 17-3")
    armed.tool_names = {"calculator", "web_search"}
    _prepare_calculator_first_move(armed, "what is 17-3")
    assert armed.calculator_preinject == {"expression": "what is 17-3"}

    units = _ctx(text="how many feet in 3 meters")
    units.tool_names = {"calculator", "units", "web_search"}
    _prepare_calculator_first_move(units, "how many feet in 3 meters")
    assert units.calculator_preinject is None

    constant = _ctx(text="explain the gravitational constant")
    constant.tool_names = {"calculator", "web_search"}
    _prepare_calculator_first_move(constant, "explain the gravitational constant")
    assert constant.calculator_preinject is None

    created = _ctx(text="add a calendar event called Dentist, tomorrow at 3pm")
    created.tool_names = {"calculator", "agenda", "web_search"}
    _prepare_calculator_first_move(
        created,
        "add a calendar event called Dentist, tomorrow at 3pm",
    )
    assert created.calculator_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_calculator_is_spent_by_the_round_that_calls_it() -> None:
    """``calculator_preinject`` is a one-shot, and the clearing rides on the scratch.

    Leaving it on ``ctx`` is a second calculation on round two. The route
    already drafted the call; this round spends it and does not ask the model.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "17-3"})])
    ctx = _ctx(text="what is 17-3")
    ctx.tool_names = {"calculator", "web_search"}
    ctx.available = {"calculator", "web_search"}
    ctx.visible = {"calculator", "web_search"}
    ctx.available_all = {"calculator", "web_search"}
    ctx.calculator_preinject = {"expression": "what is 17-3"}

    await run_round(loop, ctx, 1)
    assert "calculator" in loop.tools_used
    assert "web_search" not in loop.tools_used
    assert ctx.calculator_preinject is None
    assert ctx.calculator_ok is True

    await run_round(loop, ctx, 2)
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


def test_a_constant_ask_arms_units_and_a_concept_and_arithmetic_do_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    ``what is the gravitational constant`` is a published-constant lookup.
    ``explain the gravitational constant`` is a concept. ``what is 17-3``
    is arithmetic. The number stays in the tool.
    """
    armed = _ctx(text="what is the gravitational constant")
    armed.tool_names = {"units", "web_search"}
    _prepare_units_first_move(armed, "what is the gravitational constant")
    assert armed.units_preinject is not None
    assert armed.units_preinject["action"] == "constant"
    assert lookup_constant(str(armed.units_preinject["name"])) is not None

    concept = _ctx(text="explain the gravitational constant")
    concept.tool_names = {"units", "web_search"}
    _prepare_units_first_move(concept, "explain the gravitational constant")
    assert concept.units_preinject is None

    arith = _ctx(text="what is 17-3")
    arith.tool_names = {"units", "calculator", "web_search"}
    _prepare_units_first_move(arith, "what is 17-3")
    assert arith.units_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_units_call_is_spent_by_the_round_that_calls_it() -> None:
    """``units_preinject`` is a one-shot, and the clearing rides on the scratch.

    Leaving it on ``ctx`` is a second lookup on round two. The route already
    drafted the call; this round spends it and does not ask the model.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "gravitational constant"})])
    ctx = _ctx(text="what is the gravitational constant")
    ctx.tool_names = {"units", "web_search"}
    ctx.available = {"units", "web_search"}
    ctx.visible = {"units", "web_search"}
    ctx.available_all = {"units", "web_search"}
    ctx.units_preinject = {"action": "constant", "name": "gravitational constant"}

    await run_round(loop, ctx, 1)
    assert "units" in loop.tools_used
    assert "web_search" not in loop.tools_used
    assert ctx.units_preinject is None
    assert ctx.units_ok is True

    await run_round(loop, ctx, 2)
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


_COMPLETE_EMAIL = (
    "Email brian@example.com subject: Status body: All green on the deploy."
)
_INCOMPLETE_EMAIL = "Email bob@example.com"
_NOT_AN_EMAIL = "What's in my email?"


def test_a_complete_email_draft_arms_send_and_an_incomplete_one_does_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    The complete line is the one ``complete_email_draft`` already treats
    as ready to send. A to-only compose is missing a body. A mailbox
    question is not a draft.
    """
    armed = _ctx(text=_COMPLETE_EMAIL)
    armed.email_draft = complete_email_draft(_COMPLETE_EMAIL)
    armed.tool_names = {"send_email", "web_search"}
    _prepare_email_first_move(armed, {})
    assert armed.email_preinject is not None
    assert armed.email_preinject["to"] == "brian@example.com"

    missing_body = _ctx(text=_INCOMPLETE_EMAIL)
    missing_body.email_draft = complete_email_draft(_INCOMPLETE_EMAIL)
    missing_body.tool_names = {"send_email", "web_search"}
    _prepare_email_first_move(missing_body, {})
    assert missing_body.email_preinject is None

    not_email = _ctx(text=_NOT_AN_EMAIL)
    not_email.email_draft = complete_email_draft(_NOT_AN_EMAIL)
    not_email.tool_names = {"send_email", "web_search"}
    _prepare_email_first_move(not_email, {})
    assert not_email.email_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_email_is_spent_before_a_scripted_search() -> None:
    """``email_preinject`` is a one-shot. The scripted search never runs.

    Round two is the answer. It offers no tools.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "deploy status"})])
    ctx = _ctx(text=_COMPLETE_EMAIL)
    ctx.email_draft = complete_email_draft(_COMPLETE_EMAIL)
    ctx.tool_names = {"send_email", "web_search"}
    ctx.available = {"send_email", "web_search"}
    ctx.visible = {"send_email", "web_search"}
    ctx.available_all = {"send_email", "web_search"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "send_email"}, {"name": "web_search"}]
    _prepare_email_first_move(ctx, {})

    await run_round(loop, ctx, 1)
    assert "send_email" in loop.tools_used
    assert "web_search" not in loop.tools_used
    assert ctx.email_preinject is None
    assert ctx.email_sent_ok is True

    await run_round(loop, ctx, 2)
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


# Existing open-site line. utterance guards and preflight already treat it
# as a browser ask, and it is not a tile, a calendar, or a sign-in click.
_BROWSER_ASK = "open x.com"


def test_a_browser_ask_arms_and_a_tile_calendar_weather_and_status_do_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    ``open x.com`` is the open-site line the browser guards already accept.
    A tile, a calendar open, a forecast, and a solar or earth status do not.
    """
    armed = _ctx(text=_BROWSER_ASK)
    armed.tool_names = {"browser", "web_search"}
    _prepare_browser_first_move(armed, _BROWSER_ASK)
    assert armed.browser_preinject == draft_browser_args(_BROWSER_ASK)

    tile = _ctx(text="show me the Drive strip")
    tile.tool_names = {"browser", "web_search"}
    _prepare_browser_first_move(tile, "show me the Drive strip")
    assert tile.browser_preinject is None

    calendar = _ctx(text="open my calendar")
    calendar.tool_names = {"browser", "web_search"}
    _prepare_browser_first_move(calendar, "open my calendar")
    assert calendar.browser_preinject is None

    forecast = _ctx(text="what's the weather in austin")
    forecast.tool_names = {"browser", "web_search"}
    _prepare_browser_first_move(forecast, "what's the weather in austin")
    assert forecast.browser_preinject is None

    solar = _ctx(text="what's the solar system status")
    solar.tool_names = {"browser", "web_search"}
    _prepare_browser_first_move(solar, "what's the solar system status")
    assert solar.browser_preinject is None

    earth = _ctx(text="what's the earth status")
    earth.tool_names = {"browser", "web_search"}
    _prepare_browser_first_move(earth, "what's the earth status")
    assert earth.browser_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_browser_call_is_spent_by_the_round_that_calls_it() -> None:
    """``browser_preinject`` is a one-shot. The scripted search never runs.

    Browser calls don't automatically disable tools (chaining scenarios like
    screenshot+vision need follow-up tools). Other factors control when the
    turn ends.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "x.com"})])
    ctx = _ctx(text=_BROWSER_ASK)
    ctx.tool_names = {"browser", "web_search"}
    ctx.available = {"browser", "web_search"}
    ctx.visible = {"browser", "web_search"}
    ctx.available_all = {"browser", "web_search"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "browser"}, {"name": "web_search"}]
    _prepare_browser_first_move(ctx, _BROWSER_ASK)

    await run_round(loop, ctx, 1)
    assert "browser" in loop.tools_used
    assert "web_search" not in loop.tools_used
    assert ctx.browser_preinject is None
    assert ctx.browser_ok is True

    await run_round(loop, ctx, 2)
    # Browser success doesn't automatically disable tools; chaining scenarios
    # like screenshot+vision need follow-up tools available.
    assert ctx.offer_tools is True
    assert "browser" in ctx.tool_names or "web_search" in ctx.tool_names


# Existing tile line. match_tile_intent already accepts it as an open of workspace.
_TILE_ASK = "show me the workspace"


def test_a_tile_ask_arms_and_a_calendar_with_agenda_a_drive_strip_and_a_url_do_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    ``show me the workspace`` is an open ``match_tile_intent`` already
    accepts. ``open my calendar`` is a calendar open; agenda wins when
    that tool is registered, and calendar arms when it is not. A Drive
    strip is not a tile name. ``open x.com`` is a browser URL.
    """
    armed = _ctx(text=_TILE_ASK)
    armed.tool_names = {"tile", "browser"}
    _prepare_tile_first_move(armed, _TILE_ASK)
    assert armed.tile_preinject == tile_tool_args(_TILE_ASK)
    assert armed.tile_preinject is not None
    assert armed.tile_preinject["action"] == "open"
    assert armed.tile_preinject["name"] == "workspace"

    calendar_with_agenda = _ctx(text="open my calendar")
    calendar_with_agenda.tool_names = {"tile", "agenda"}
    _prepare_tile_first_move(calendar_with_agenda, "open my calendar")
    assert calendar_with_agenda.tile_preinject is None

    calendar = _ctx(text="open my calendar")
    calendar.tool_names = {"tile", "browser"}
    _prepare_tile_first_move(calendar, "open my calendar")
    assert calendar.tile_preinject == {"action": "open", "name": "calendar"}

    drive = _ctx(text="where is the Drive strip?")
    drive.tool_names = {"tile", "browser"}
    _prepare_tile_first_move(drive, "where is the Drive strip?")
    assert drive.tile_preinject is None

    url = _ctx(text="open x.com")
    url.tool_names = {"tile", "browser"}
    _prepare_tile_first_move(url, "open x.com")
    assert url.tile_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_tile_call_is_spent_by_the_round_that_calls_it() -> None:
    """``tile_preinject`` is a one-shot. The scripted browser call never runs.

    Round two is the answer. It offers no tools. Round one does not clear them.
    """
    loop = _RoundLoop(stream_calls=[("browser", {"action": "open", "url": "https://x.com"})])
    ctx = _ctx(text=_TILE_ASK)
    ctx.tool_names = {"tile", "browser"}
    ctx.available = {"tile", "browser"}
    ctx.visible = {"tile", "browser"}
    ctx.available_all = {"tile", "browser"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "tile"}, {"name": "browser"}]
    _prepare_tile_first_move(ctx, _TILE_ASK)

    await run_round(loop, ctx, 1)
    assert "tile" in loop.tools_used
    assert "browser" not in loop.tools_used
    assert ctx.tile_preinject is None
    assert ctx.tile_ok is True
    assert ctx.offer_tools is True

    await run_round(loop, ctx, 2)
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


# The inspect tests already use this phrasing. The path comes from
# inspect_read_path, not a string copied into the assertion.
_DRIVE_ASK = "where is the Drive strip?"
# Already pinned in tests/test_no_call_path.py: looks_like_source_inspect
# accepts it and inspect_read_path returns None.
_VAGUE_INSPECT = "look through the code"


def test_a_source_ask_arms_a_workspace_read_and_a_tile_a_url_and_a_vague_crawl_do_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    ``where is the Drive strip?`` is a source ask with a mapped file.
    ``show me the workspace`` is a tile. ``open x.com`` is a browser URL.
    A crawl with no mapped path does not get a guessed one.
    """
    armed = _ctx(text=_DRIVE_ASK)
    armed.tool_names = {"workspace", "web_search"}
    _prepare_inspect_first_move(armed, _DRIVE_ASK)
    path = inspect_read_path(_DRIVE_ASK)
    assert path
    assert armed.workspace_preinject == {"action": "read", "path": path}

    tile = _ctx(text=_TILE_ASK)
    tile.tool_names = {"workspace", "tile"}
    _prepare_inspect_first_move(tile, _TILE_ASK)
    assert tile.workspace_preinject is None

    url = _ctx(text="open x.com")
    url.tool_names = {"workspace", "browser"}
    _prepare_inspect_first_move(url, "open x.com")
    assert url.workspace_preinject is None

    assert looks_like_source_inspect(_VAGUE_INSPECT)
    assert inspect_read_path(_VAGUE_INSPECT) is None
    vague = _ctx(text=_VAGUE_INSPECT)
    vague.tool_names = {"workspace"}
    _prepare_inspect_first_move(vague, _VAGUE_INSPECT)
    assert vague.workspace_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_workspace_read_is_spent_by_the_round_that_calls_it() -> None:
    """``workspace_preinject`` is a one-shot. The scripted search never runs.

    Round two is the answer. It offers no tools. Round one does not clear them.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "drive strip"})])
    ctx = _ctx(text=_DRIVE_ASK)
    ctx.tool_names = {"workspace", "web_search"}
    ctx.available = {"workspace", "web_search"}
    ctx.visible = {"workspace", "web_search"}
    ctx.available_all = {"workspace", "web_search"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "workspace"}, {"name": "web_search"}]
    _prepare_inspect_first_move(ctx, _DRIVE_ASK)

    await run_round(loop, ctx, 1)
    assert "workspace" in loop.tools_used
    assert "web_search" not in loop.tools_used
    assert ctx.workspace_preinject is None
    assert ctx.inspect_ok is True
    assert ctx.offer_tools is True

    await run_round(loop, ctx, 2)
    assert "web_search" not in loop.tools_used
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


def test_a_named_py_arms_run_script_and_a_bare_script_the_tests_and_a_source_ask_do_not() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    ``run measure_drift.py`` names a file. ``run the script`` matches the
    intent and has no path. ``run the tests`` is diagnostics. A source ask
    is not a script.
    """
    phrase = "run measure_drift.py"
    armed = _ctx(text=phrase)
    armed.tool_names = {"run_script", "python"}
    _prepare_run_script_first_move(armed, phrase)
    path = run_script_path(phrase)
    assert path
    assert armed.run_script_preinject == {"path": path}

    bare = _ctx(text="run the script")
    bare.tool_names = {"run_script"}
    assert RUN_SCRIPT.matches("run the script")
    assert run_script_path("run the script") == ""
    _prepare_run_script_first_move(bare, "run the script")
    assert bare.run_script_preinject is None

    tests_ask = _ctx(text="run the tests")
    tests_ask.tool_names = {"run_script", "diagnostics"}
    _prepare_run_script_first_move(tests_ask, "run the tests")
    assert tests_ask.run_script_preinject is None

    drive = _ctx(text=_DRIVE_ASK)
    drive.tool_names = {"run_script", "workspace"}
    _prepare_run_script_first_move(drive, _DRIVE_ASK)
    assert drive.run_script_preinject is None


@pytest.mark.asyncio
async def test_a_preinjected_run_script_is_spent_by_the_round_that_calls_it() -> None:
    """``run_script_preinject`` is a one-shot. The scripted python call never runs.

    Round two is the answer. It offers no tools. Round one does not clear them.
    """
    phrase = "run measure_drift.py"
    loop = _RoundLoop(stream_calls=[("python", {"code": "print(1)"})])
    ctx = _ctx(text=phrase)
    ctx.tool_names = {"run_script", "python"}
    ctx.available = {"run_script", "python"}
    ctx.visible = {"run_script", "python"}
    ctx.available_all = {"run_script", "python"}
    ctx.offer_tools = True
    ctx.ollama_tools = [{"name": "run_script"}, {"name": "python"}]
    _prepare_run_script_first_move(ctx, phrase)

    await run_round(loop, ctx, 1)
    assert "run_script" in loop.tools_used
    assert "python" not in loop.tools_used
    assert ctx.run_script_preinject is None
    assert ctx.run_script_ok is True
    assert ctx.offer_tools is True

    await run_round(loop, ctx, 2)
    assert "python" not in loop.tools_used
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == []
    assert ctx.tool_names == set()


@pytest.mark.asyncio
async def test_the_landed_routes_spend_the_prepared_call() -> None:
    """The prepare helper is the route. A stuffed dict is not.

    Unit conversions are not preinjected. They stay on the units force gate.
    "how many feet in 3 meters" must leave units_preinject None.

    Agenda create, delete, and close are not preinjected. A create phrase
    must leave agenda_preinject None.

    Earth and solar are not on this board.
    """

    def _fresh(phrase: str, tool: str) -> tuple[_RoundLoop, Any]:
        loop = _RoundLoop(stream_calls=[("web_search", {"query": phrase})])
        ctx = _ctx(text=phrase)
        names = {tool, "web_search"}
        ctx.tool_names = set(names)
        ctx.available = set(names)
        ctx.visible = set(names)
        ctx.available_all = set(names)
        return loop, ctx

    async def _spent(
        loop: _RoundLoop, ctx: Any, tool: str, field: str, phrase: str
    ) -> None:
        assert getattr(ctx, field) is not None, phrase
        await run_round(loop, ctx, 1)
        assert tool in loop.tools_used, phrase
        assert "web_search" not in loop.tools_used, phrase
        assert getattr(ctx, field) is None, phrase

    conversion = "how many feet in 3 meters"
    _, ctx = _fresh(conversion, "units")
    _prepare_units_first_move(ctx, conversion)
    assert ctx.units_preinject is None, conversion

    create = "add a calendar event called Dentist, tomorrow at 3pm"
    _, ctx = _fresh(create, "agenda")
    _prepare_agenda_first_move(ctx, create, {})
    assert ctx.agenda_preinject is None, create

    delete = "delete the Dentist event"
    _, ctx = _fresh(delete, "agenda")
    _prepare_agenda_first_move(ctx, delete, {})
    assert ctx.agenda_preinject is None, delete

    close = "close the calendar"
    _, ctx = _fresh(close, "agenda")
    _prepare_agenda_first_move(ctx, close, {})
    assert ctx.agenda_preinject is None, close

    phrase = "what's the weather in austin"
    loop, ctx = _fresh(phrase, "weather")
    _prepare_weather_first_move(ctx, phrase, {})
    await _spent(loop, ctx, "weather", "weather_preinject", phrase)

    phrase = "open my calendar"
    loop, ctx = _fresh(phrase, "agenda")
    _prepare_agenda_first_move(ctx, phrase, {})
    assert ctx.agenda_preinject == {"action": "open"}, phrase
    await _spent(loop, ctx, "agenda", "agenda_preinject", phrase)

    phrase = "what is on my calendar today"
    loop, ctx = _fresh(phrase, "agenda")
    _prepare_agenda_first_move(ctx, phrase, {})
    assert ctx.agenda_preinject == {"action": "today"}, phrase
    await _spent(loop, ctx, "agenda", "agenda_preinject", phrase)

    phrase = "what is 17-3"
    loop, ctx = _fresh(phrase, "calculator")
    _prepare_calculator_first_move(ctx, phrase)
    await _spent(loop, ctx, "calculator", "calculator_preinject", phrase)

    phrase = "what is the gravitational constant"
    loop, ctx = _fresh(phrase, "units")
    _prepare_units_first_move(ctx, phrase)
    assert ctx.units_preinject is not None, phrase
    assert ctx.units_preinject["action"] == "constant", phrase
    await _spent(loop, ctx, "units", "units_preinject", phrase)

    phrase = _COMPLETE_EMAIL
    loop, ctx = _fresh(phrase, "send_email")
    ctx.email_draft = complete_email_draft(phrase)
    _prepare_email_first_move(ctx, {})
    await _spent(loop, ctx, "send_email", "email_preinject", phrase)

    phrase = "text brian that I'm running late"
    loop, ctx = _fresh(phrase, "send_sms")
    phone = "5551112222"
    ctx.sms_draft = complete_sms_draft(
        phrase,
        contacts={
            "brian": Contact(
                alias="brian",
                name="Brian",
                phone=phone,
                digits=normalize_phone(phone),
            )
        },
    )
    await _prepare_sms_first_move(loop, ctx, phrase, {})
    await _spent(loop, ctx, "send_sms", "sms_preinject", phrase)

    phrase = "open x.com"
    loop, ctx = _fresh(phrase, "browser")
    _prepare_browser_first_move(ctx, phrase)
    await _spent(loop, ctx, "browser", "browser_preinject", phrase)

    phrase = "show me the workspace"
    loop, ctx = _fresh(phrase, "tile")
    _prepare_tile_first_move(ctx, phrase)
    await _spent(loop, ctx, "tile", "tile_preinject", phrase)

    phrase = "where is the Drive strip?"
    loop, ctx = _fresh(phrase, "workspace")
    _prepare_inspect_first_move(ctx, phrase)
    await _spent(loop, ctx, "workspace", "workspace_preinject", phrase)

    phrase = "run measure_drift.py"
    loop, ctx = _fresh(phrase, "run_script")
    _prepare_run_script_first_move(ctx, phrase)
    await _spent(loop, ctx, "run_script", "run_script_preinject", phrase)
