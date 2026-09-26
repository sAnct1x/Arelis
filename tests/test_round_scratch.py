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

from arelis.core.agent_loop import _native_tool_call
from arelis.core.claims import ExactnessNeed
from arelis.core.turn_dispatch import dispatch_calls
from arelis.core.turn_round import apply_no_call_path, run_round
from arelis.core.turn_scratch import FIELD_NAMES
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
    """
    loop = _augment(_FakeLoop())
    loop._expected_tools = {"weather"}

    async def _boom(_name: str, **_kwargs: Any) -> Any:
        raise RuntimeError("open-meteo is down")

    loop.tools.call = _boom
    text = "what's the weather in austin"
    ctx = _ctx(text=text)
    ctx.tool_names = {"weather", "web_search"}
    r = _scratch(
        text=text,
        calls=[("web_search", {"query": "austin weather"})],
        content="",
        streamed="",
        tool_names=ctx.tool_names,
        available={"weather", "web_search"},
        visible={"weather", "web_search"},
        available_all={"weather", "web_search"},
        exact_need=ExactnessNeed(False, False, True, False, kinds=("weather",)),
    )

    with pytest.raises(RuntimeError):
        await dispatch_calls(loop, ctx, r, 1)

    assert r.available == {"weather"}
    assert r.visible == {"weather"}
    assert r.tool_names == {"weather"}
    assert r.ollama_tools == ["weather"]


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
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "austin weather"})])
    loop._expected_tools = {"weather"}
    text = "what's the weather in austin"
    ctx = _ctx(text=text)
    ctx.tool_names = {"weather", "web_search"}
    ctx.available = {"weather", "web_search"}
    ctx.visible = {"weather", "web_search"}
    ctx.available_all = {"weather", "web_search"}
    ctx.ollama_tools = [{"name": "weather"}, {"name": "web_search"}]
    ctx.exact_need = ExactnessNeed(False, False, True, False, kinds=("weather",))

    assert await run_round(loop, ctx, 1) is False
    assert "weather" in loop.tools_used
    assert ctx.available == {"weather"}
    assert ctx.visible == {"weather"}
    assert ctx.ollama_tools == ["weather"]


@pytest.mark.asyncio
async def test_a_raise_mid_round_still_hands_ctx_the_narrowed_surface() -> None:
    """The write-back used to snapshot locals *before* dispatch.

    ``_drop_wander`` lands on the scratch. If the tool then explodes,
    ``dispatch_calls`` never returns, and a ``finally`` that wrote the
    locals from the *start* of the round would put web_search back on
    ``ctx``. Next round offers it again. The explode-on-``r`` test below
    does not catch that — it never goes through ``run_round``.
    """
    loop = _RoundLoop(stream_calls=[("web_search", {"query": "austin weather"})])
    loop._expected_tools = {"weather"}

    async def _boom(_name: str, **_kwargs: Any) -> Any:
        raise RuntimeError("open-meteo is down")

    loop.tools.call = _boom  # type: ignore[method-assign]
    text = "what's the weather in austin"
    ctx = _ctx(text=text)
    ctx.tool_names = {"weather", "web_search"}
    ctx.available = {"weather", "web_search"}
    ctx.visible = {"weather", "web_search"}
    ctx.available_all = {"weather", "web_search"}
    ctx.ollama_tools = [{"name": "weather"}, {"name": "web_search"}]
    ctx.exact_need = ExactnessNeed(False, False, True, False, kinds=("weather",))

    with pytest.raises(RuntimeError, match="open-meteo"):
        await run_round(loop, ctx, 1)

    assert ctx.available == {"weather"}
    assert ctx.visible == {"weather"}
    assert ctx.tool_names == {"weather"}


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


def test_the_scratch_carries_no_field_the_turn_context_cannot_supply() -> None:
    """``run_round`` builds the scratch straight off ``ctx``.

    Nothing here is clever — it is the check that a field added to the
    scratch got a source, instead of defaulting to whatever the last round
    left behind.
    """
    built = re.findall(
        r"^\s{12}(\w+)=",
        Path("arelis/core/turn_round.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert set(FIELD_NAMES) <= set(built)
