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
from arelis.core.turn_dispatch import dispatch_calls
from arelis.core.turn_round import apply_no_call_path
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
    loop.tools.ollama_tools = lambda names, *, param_hints=False: sorted(str(n) for n in names)
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
    # Schemas stay so the next request can reuse the prefix. Calls are still blocked.
    assert r.ollama_tools == [{"name": "scrape"}]
    assert not r.tool_names
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == [{"name": "scrape"}]
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
    # Schemas stay. tool_names is what blocks the repeat call.
    assert r.ollama_tools == [{"name": "cas"}]
    assert not r.tool_names
    assert ctx.offer_tools is False
    assert ctx.ollama_tools == [{"name": "cas"}]
    assert not ctx.tool_names








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










_COMPLETE_EMAIL = (
    "Email brian@example.com subject: Status body: All green on the deploy."
)
_INCOMPLETE_EMAIL = "Email bob@example.com"
_NOT_AN_EMAIL = "What's in my email?"






# Existing open-site line. utterance guards and preflight already treat it
# as a browser ask, and it is not a tile, a calendar, or a sign-in click.
_BROWSER_ASK = "open x.com"






# Existing tile line. match_tile_intent already accepts it as an open of workspace.
_TILE_ASK = "show me the workspace"






# The inspect tests already use this phrasing. The path comes from
# inspect_read_path, not a string copied into the assertion.
_DRIVE_ASK = "where is the Drive strip?"
# Already pinned in tests/test_no_call_path.py: looks_like_source_inspect
# accepts it and inspect_read_path returns None.
_VAGUE_INSPECT = "look through the code"












