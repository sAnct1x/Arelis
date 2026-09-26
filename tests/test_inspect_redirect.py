"""Asking about her own source must not be answered from the open web.

Roadmap guard hole, confirmed 2026-09-17 by reading the wiring rather than
guessing at it:

    INSPECT.expected_tools            == ("workspace",)
    _HIDE_WANDER_FOR                  == _DAILY_WANDER | _LOCAL_STORE
                                         | _SEE_TOOLS | {"browser"}

`workspace` is in none of those. So on "where is the Drive strip?" preflight
does its whole job — it fires the inspect intent, maps the ask to
`arelis/ui/panels/drive.py`, and writes a nudge naming that file — and then
`web_search`, `scrape`, `web_fetch` and `browser` all stay on the menu anyway.
When the model takes one, the call is dispatched and runs, and she describes
her own UI from whatever the web said about "drive strip".

`try_inspect` cannot save this. It is the *no-call* floor, and a call was
made, so it never runs.

Fixed as a redirect rather than by adding `workspace` to `_HIDE_WANDER_FOR`.
`_hide_daily_wander` only sees the expected *tool names*, so it cannot tell an
inspect turn from "search the web for X and save it to notes.md" — a turn with
`workspace` expected that genuinely needs `web_search`. Hiding there would
trade this bug for a worse one. A redirect can gate on the text, which is what
every other specific redirect in that table already does.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.call_redirects import (
    REDIRECT_STEPS,
    apply_redirects,
    redirect_inspect_wander,
)
from tests.test_no_call_path import _ctx, _FakeLoop, _scratch

WANDER = ["web_search", "scrape", "web_fetch", "browser"]


def _inspect_turn(text: str = "where is the Drive strip?") -> tuple[Any, ...]:
    loop = _FakeLoop()
    loop._expected_tools = {"workspace"}
    r = _scratch(
        text=text,
        content="",
        tool_names={"workspace", *WANDER},
        available={"workspace", *WANDER},
        visible={"workspace", *WANDER},
        available_all={"workspace", *WANDER},
    )
    r.messages = []
    ctx = _ctx(text=text)
    ctx.tool_names = {"workspace", *WANDER}
    return loop, ctx, r


def _dropped() -> tuple[Any, list[str]]:
    seen: list[str] = []

    def drop_wander(*names: str) -> None:
        seen.extend(names)

    return drop_wander, seen


# --------------------------------------------------------------------------


@pytest.mark.parametrize("wander", WANDER)
@pytest.mark.asyncio
async def test_a_web_call_about_her_own_source_becomes_a_file_read(
    wander: str,
) -> None:
    loop, ctx, r = _inspect_turn()
    drop, _ = _dropped()

    hit = await redirect_inspect_wander(loop, ctx, r, wander, {"query": "x"}, drop)

    assert hit is not None, f"{wander} ran and answered from the web"
    assert hit == ("run", "workspace", {"action": "read", "path": "arelis/ui/panels/drive.py"})


@pytest.mark.asyncio
async def test_the_model_is_told_why_so_it_does_not_retry_the_same_call() -> None:
    loop, ctx, r = _inspect_turn()
    drop, dropped = _dropped()

    await redirect_inspect_wander(loop, ctx, r, "web_search", {"query": "x"}, drop)

    assert r.messages, "the call vanished with no explanation in the transcript"
    assert "workspace" in r.messages[-1]["content"]
    # Dropping the rest of the wander set is what stops the next round going
    # straight back to scrape after web_search was blocked.
    assert set(WANDER) <= set(dropped)


@pytest.mark.asyncio
async def test_a_vague_source_ask_lands_on_the_architecture_doc() -> None:
    """Not the assertion this test started with, and the code was right.

    `try_inspect`'s docstring says `inspect_read_path` returns None for a
    vague "read your source". It does not — it falls back to
    `docs/architecture.md`, which is a better answer to "can you read your own
    source code?" than any single module would be, and far better than a web
    search. The docstring is stale; the behaviour is fine.
    """
    loop, ctx, r = _inspect_turn("can you read your own source code?")
    drop, _ = _dropped()

    hit = await redirect_inspect_wander(loop, ctx, r, "web_search", {}, drop)

    assert hit == ("run", "workspace", {"action": "read", "path": "docs/architecture.md"})


@pytest.mark.asyncio
async def test_an_unmapped_ask_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Injecting a guessed path would be the same class of bug, not a fix.

    No live phrasing reaches this today because of the architecture-doc
    fallback above, so the branch is driven directly rather than left
    unexercised.
    """
    monkeypatch.setattr("arelis.core.call_redirects.inspect_read_path", lambda _text: None)
    loop, ctx, r = _inspect_turn()
    drop, _ = _dropped()

    assert await redirect_inspect_wander(loop, ctx, r, "web_search", {}, drop) is None


@pytest.mark.asyncio
async def test_a_real_web_question_still_reaches_the_web() -> None:
    loop, ctx, r = _inspect_turn("how does a diesel engine work?")
    drop, _ = _dropped()

    assert await redirect_inspect_wander(loop, ctx, r, "web_search", {}, drop) is None


@pytest.mark.asyncio
async def test_search_and_save_is_not_hijacked() -> None:
    """The exact turn that made hiding the wrong fix.

    `workspace` is expected here and the web call is correct. If this ever
    redirects, the cure is worse than the disease.
    """
    loop, ctx, r = _inspect_turn(
        "search the web for the Cesium release notes and save them to notes.md"
    )
    drop, _ = _dropped()

    assert await redirect_inspect_wander(loop, ctx, r, "web_search", {}, drop) is None


@pytest.mark.asyncio
async def test_it_does_not_fire_once_the_file_has_been_read() -> None:
    """She read the file and then searched. That is a follow-up, not a misroute."""
    loop, ctx, r = _inspect_turn()
    loop.tools_used = {"workspace"}
    drop, _ = _dropped()

    assert await redirect_inspect_wander(loop, ctx, r, "web_search", {}, drop) is None


@pytest.mark.asyncio
async def test_it_is_skipped_when_the_gate_is_off() -> None:
    loop, ctx, r = _inspect_turn()
    r.agent_cfg["inspect_force_call"] = False
    drop, _ = _dropped()

    assert await redirect_inspect_wander(loop, ctx, r, "web_search", {}, drop) is None


@pytest.mark.asyncio
async def test_a_tool_that_is_not_wander_is_untouched() -> None:
    loop, ctx, r = _inspect_turn()
    drop, _ = _dropped()

    assert await redirect_inspect_wander(loop, ctx, r, "git_info", {}, drop) is None


@pytest.mark.asyncio
async def test_it_is_reached_through_the_real_table() -> None:
    """Registering it last means an earlier step could still claim the call."""
    loop, ctx, r = _inspect_turn()
    drop, _ = _dropped()

    hit = await apply_redirects(loop, ctx, r, "web_search", {"query": "x"}, drop)

    assert hit[0] == "run"
    assert hit[1] == "workspace"


def test_it_runs_last() -> None:
    """Same argument as try_inspect being last in INJECT_STEPS.

    "show me the Drive strip" is a tile ask and a source ask at once, and the
    tile redirect has to keep winning it.
    """
    assert REDIRECT_STEPS[-1] is redirect_inspect_wander
