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
from arelis.core.turn_context import TurnContext
from arelis.core.turn_dispatch import dispatch_calls
from arelis.core.turn_round import apply_no_call_path
from arelis.core.turn_scratch import RoundScratch


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
            ollama_tools=lambda _names, *, param_hints=False: [],
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
        passthrough_tool: str = "",
    ) -> None:
        self.finished = (text, sources, streamed)
        self.passthrough_tool = passthrough_tool

    async def _hold_if_paused(self) -> None:
        return None

    def _look_refuse(self, _content: str) -> str | None:
        return None

    def _tool_message(self, name: str, err: str) -> dict[str, str]:
        return {"role": "tool", "name": name, "content": err}


def _scratch(**overrides: Any) -> RoundScratch:
    base = dict(
        text="hello",
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
    )
    from arelis.core.claims import ExactnessNeed
    from arelis.core.evidence import EvidenceLedger

    if overrides.get("exact_need") is None and "exact_need" not in overrides:
        base["exact_need"] = ExactnessNeed(False, False, False, False)
    if overrides.get("ledger") is None and "ledger" not in overrides:
        base["ledger"] = EvidenceLedger()
    base.update(overrides)
    return RoundScratch(**base)  # type: ignore[arg-type]


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
async def test_plain_thanks_finishes_the_turn() -> None:
    loop = _FakeLoop()
    r = _scratch(content="You're welcome.")
    ctx = _ctx()
    assert await apply_no_call_path(loop, ctx, r, 0) is True
    assert loop.finished is not None
    assert loop.finished[0] == "You're welcome."




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


def test_arxiv_search_and_id_urls_are_one_page() -> None:
    from arelis.core.turn_dispatch import page_key

    search = page_key(
        "https://arxiv.org/search/?query=K2-18b+JWST&searchtype=all&source=recent"
    )
    assert search == page_key(
        "https://arxiv.org/search/?query=K2-18b+JWST&searchtype=all"
        "&source=recent&abstracts=show&all"
    )
    paper = page_key("https://arxiv.org/html/2309.05566")
    assert paper == page_key("https://arxiv.org/abs/2309.05566")
    assert paper == page_key("https://arxiv.org/pdf/2309.05566.pdf")
    assert paper != search


@pytest.mark.asyncio
async def test_search_cap_with_a_page_open_keeps_scrape_for_the_rest() -> None:
    """Live 2026-09-26 turn 41d1f60b: one DMS paper, then scrape was gone.

    The cap said call document and she could not open the 2023 paper.
    She went to recall and quoted an earlier turn until Stop.
    """
    from arelis.core.claims import ExactnessNeed

    loop = _FakeLoop()
    loop.tools.ollama_tools = lambda names, *, param_hints=False: [{"name": n} for n in sorted(names)]
    r = _scratch(
        calls=[("web_search", {"query": "yet another reanalysis"})],
        content="",
        streamed="",
        tool_names={
            "web_search",
            "scrape",
            "document",
            "browser",
            "research_report",
            "recall",
        },
        offer_tools=True,
        messages=[],
        research_mode=True,
        web_search_ok={f"q{i}" for i in range(8)},
    )
    ctx = _ctx()
    ctx.tool_names = r.tool_names
    ctx.exact_need = ExactnessNeed(
        False,
        True,
        False,
        False,
        needs_document=True,
        kinds=("web", "document"),
    )
    ctx.ledger.add(
        source="https://arxiv.org/abs/2504.12267",
        kind="web",
        span="DMS and DMDS at 3 sigma",
        ok=True,
    )
    assert await dispatch_calls(loop, ctx, r, 12) is False
    assert "web_search" in r.tool_names
    assert "scrape" in r.tool_names
    assert "document" in r.tool_names
    assert ctx.document_nudge_used is False
    blob = " ".join(str(m.get("content") or "") for m in r.messages)
    assert "not searching again" in blob
    assert "Wikipedia" not in blob


@pytest.mark.asyncio
async def test_search_cap_on_wikipedia_keeps_scrape_and_drops_the_browser() -> None:
    """Live 2026-09-26 turn d246e037: eight searches, one wiki page.

    The cap told her to write the PDF and left browser and research_report
    on. She wrote a markdown report, opened the wrong arXiv id, and the
    second open of that URL pasted the Google click into chat.
    """
    from arelis.core.claims import ExactnessNeed

    loop = _FakeLoop()
    loop.tools.ollama_tools = lambda names, *, param_hints=False: [{"name": n} for n in sorted(names)]
    r = _scratch(
        calls=[("web_search", {"query": "one more madhusudhan query"})],
        content="",
        streamed="",
        tool_names={
            "web_search",
            "scrape",
            "document",
            "browser",
            "research_report",
            "recall",
        },
        offer_tools=True,
        messages=[],
        research_mode=True,
        web_search_ok={f"q{i}" for i in range(8)},
    )
    ctx = _ctx()
    ctx.tool_names = r.tool_names
    ctx.exact_need = ExactnessNeed(
        False,
        True,
        False,
        False,
        needs_document=True,
        kinds=("web", "document"),
    )
    ctx.ledger.add(
        source="https://en.wikipedia.org/wiki/K2-18b",
        kind="web",
        span="sub-Neptune",
        ok=True,
    )
    assert await dispatch_calls(loop, ctx, r, 10) is False
    assert loop.finished is None
    assert "scrape" in r.tool_names
    assert "document" in r.tool_names
    assert "web_search" in r.tool_names
    assert "scrape" in r.tool_names
    assert ctx.document_nudge_used is False
    blob = " ".join(str(m.get("content") or "") for m in r.messages)
    assert "not searching again" in blob
    assert "Wikipedia" not in blob


@pytest.mark.asyncio
async def test_a_second_search_waits_until_a_hit_is_opened() -> None:
    loop = _FakeLoop()
    paper = "https://arxiv.org/abs/2309.05566"
    wiki = "https://en.wikipedia.org/wiki/K2-18b"
    r = _scratch(
        calls=[("web_search", {"query": "same topic again"})],
        content="",
        streamed="",
        tool_names={"web_search", "scrape", "document"},
        offer_tools=True,
        messages=[],
    )
    ctx = _ctx()
    ctx.tool_names = r.tool_names
    ctx.last_hit_urls = [paper, wiki]
    from arelis.core.search_loop import page_key

    ctx.hit_urls = {page_key(paper), page_key(wiki)}
    assert await dispatch_calls(loop, ctx, r, 2) is False
    assert loop.finished is None
    assert "scrape" in r.tool_names
    assert "web_search" in r.tool_names
    blob = " ".join(str(m.get("content") or "") for m in r.messages)
    assert "Open a page from the last search" in blob
    assert paper in blob
    assert blob.index(paper) < blob.index(wiki)


@pytest.mark.asyncio
async def test_an_invented_url_is_not_scraped() -> None:
    loop = _FakeLoop()
    paper = "https://arxiv.org/abs/2309.05566"
    r = _scratch(
        calls=[("scrape", {"url": "https://arxiv.org/abs/2309.15684"})],
        content="",
        streamed="",
        tool_names={"scrape", "web_search", "document"},
        messages=[],
    )
    ctx = _ctx()
    ctx.tool_names = r.tool_names
    ctx.last_hit_urls = [paper]
    from arelis.core.search_loop import page_key

    ctx.hit_urls = {page_key(paper)}
    assert await dispatch_calls(loop, ctx, r, 3) is False
    assert loop.finished is None
    blob = " ".join(str(m.get("content") or "") for m in r.messages)
    assert "Do not invent an address" in blob
    assert paper in blob
    assert "url not in search hits" in " ".join(loop._trace)


@pytest.mark.asyncio
async def test_repeated_browser_open_does_not_paint_the_page_when_a_pdf_is_owed() -> None:
    from arelis.core.claims import ExactnessNeed
    from arelis.core.same_call import record_same_call, same_call_key

    loop = _FakeLoop()
    loop.tools.ollama_tools = lambda names, *, param_hints=False: [{"name": n} for n in sorted(names)]
    args = {"action": "open", "url": "https://arxiv.org/abs/2309.16758"}
    r = _scratch(
        calls=[("browser", args)],
        content="",
        streamed="",
        tool_names={"browser", "scrape", "document"},
        offer_tools=True,
        messages=[],
    )
    ctx = _ctx()
    ctx.tool_names = r.tool_names
    ctx.exact_need = ExactnessNeed(
        False,
        False,
        False,
        False,
        needs_document=True,
        kinds=("document",),
    )
    ctx.last_ok_tool_out = "Clicked [e36] Carbon bearing molecules"
    ctx.last_ok_tool_name = "browser"
    record_same_call(ctx.same_ok, "browser", args)
    key = same_call_key("browser", args)
    assert key
    ctx.same_skip_keys.add(key)
    assert await dispatch_calls(loop, ctx, r, 20) is False
    assert loop.finished is None
    assert "browser" not in r.tool_names
    assert "document" in r.tool_names
    assert "Clicked" not in " ".join(str(m.get("content") or "") for m in r.messages)


@pytest.mark.asyncio
async def test_second_duplicate_page_does_not_force_the_file() -> None:
    """Repeating a URL is a skip. It does not end the research and write."""
    from arelis.core.claims import ExactnessNeed

    loop = _FakeLoop()
    offered: list[set[str]] = []

    def _schemas(names: set[str], *, param_hints: bool = False) -> list[dict[str, str]]:
        offered.append(set(names))
        return [{"name": n} for n in sorted(names)]

    loop.tools.ollama_tools = _schemas
    url = "https://arxiv.org/html/2309.05566"
    from arelis.core.turn_dispatch import page_key

    r = _scratch(
        calls=[("scrape", {"url": url, "max_chars": 8000})],
        content="",
        streamed="",
        tool_names={"scrape", "web_search", "web_fetch", "document"},
        offer_tools=True,
        messages=[],
        page_ok={page_key(url)},
    )
    ctx = _ctx()
    ctx.tool_names = r.tool_names
    ctx.page_ok = r.page_ok
    ctx.duplicate_page_skips = 1
    ctx.ledger.add(
        source="https://arxiv.org/abs/2309.05566",
        kind="web",
        span="methane and carbon dioxide",
        ok=True,
    )
    ctx.exact_need = ExactnessNeed(
        False,
        False,
        False,
        False,
        needs_document=True,
        kinds=("document",),
    )
    assert await dispatch_calls(loop, ctx, r, 11) is False
    assert loop.finished is None
    assert "scrape" in r.tool_names
    assert "web_search" in r.tool_names
    assert "document" in r.tool_names
    assert ctx.document_nudge_used is False
    blob = " ".join(str(m.get("content") or "") for m in r.messages)
    assert "Call document now" not in blob
    assert "Already fetched that URL" in blob


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
async def test_dispatch_calculator_same_call_ships_the_number() -> None:
    from arelis.core.same_call import record_same_call

    loop = _FakeLoop()
    args = {"expression": "14-6"}
    r = _scratch(
        calls=[("calculator", args)],
        tool_calls=[],
        content="",
        streamed="",
        tool_names={"calculator"},
        offer_tools=True,
        messages=[],
    )
    ctx = _ctx()
    ctx.tool_names = {"calculator"}
    ctx.offer_tools = True
    ctx.last_ok_tool_out = "14-6 = 8"
    ctx.last_ok_tool_name = "calculator"
    record_same_call(ctx.same_ok, "calculator", args)
    assert await dispatch_calls(loop, ctx, r, 2) is True
    assert loop.finished is not None
    # #121: same-call finish ships a plain sentence with the number, not the formula.
    assert loop.finished[0] == "That works out to 8."
    thinking = " ".join(str(e.payload.get("text") or "") for e in loop.bus.events)
    assert "same-call algebra" not in thinking


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










@pytest.mark.asyncio
async def test_a_vague_source_ask_is_left_alone() -> None:
    """No mapped file means no injected path. A guessed path is a wrong answer."""
    from arelis.core.intent_catalog import (
        inspect_read_path,
        looks_like_source_inspect,
    )

    text = "look through the code"
    assert looks_like_source_inspect(text), "precondition: this is an inspect ask"
    assert inspect_read_path(text) is None, "precondition: it maps to no file"

    loop = _FakeLoop()
    r = _scratch(
        text=text,
        content="Sure.",
        tool_names={"workspace"},
        available={"workspace"},
        visible={"workspace"},
        available_all={"workspace"},
    )
    ctx = _ctx(text=text)
    ctx.tool_names = {"workspace"}
    ctx.inspect_nudge_used = True
    await apply_no_call_path(loop, ctx, r, 1)
    assert not r.calls


@pytest.mark.asyncio
async def test_a_plain_chat_line_is_not_dragged_into_a_source_read() -> None:
    """The backstop must not fire on anything that is not an inspect ask."""
    loop = _FakeLoop()
    r = _scratch(
        text="thanks, that's great",
        content="Any time.",
        tool_names={"workspace"},
        available={"workspace"},
        visible={"workspace"},
        available_all={"workspace"},
    )
    ctx = _ctx(text="thanks, that's great")
    ctx.tool_names = {"workspace"}
    await apply_no_call_path(loop, ctx, r, 0)
    assert not r.calls




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


@pytest.mark.asyncio
async def test_empty_after_search_keeps_tools_on_a_research_goal() -> None:
    """Live 2026-09-26: empty chat after web_search stripped scrape and
    document, then the next round's calls were unknown tools.
    """
    from arelis.core.turn_goal import derive_turn_goal

    loop = _FakeLoop()
    ask = (
        "Research what JWST measured. Search the web, then open the papers. "
        "Write the result as a PDF."
    )
    r = _scratch(content="")
    ctx = _ctx(text=ask)
    ctx.research_mode = True
    ctx.goal = derive_turn_goal(ask, role="research", research_mode=True)
    ctx.last_ok_tool_name = "web_search"
    ctx.last_ok_tool_out = "Title: Madhusudhan\n" + ("https://arxiv.org/abs/2309.05566 " * 30)
    ctx.tool_names = {"web_search", "scrape", "web_fetch", "document", "research_report"}
    r.tool_names = ctx.tool_names
    assert ctx.goal.kind == "research"
    assert await apply_no_call_path(loop, ctx, r, 3) is False
    assert ctx.page_write_nudge_used is False
    assert ctx.goal_unlock_used is True
    assert "scrape" in ctx.tool_names
    assert "document" in r.tool_names
    thinking = " ".join(str(e.payload.get("text") or "") for e in loop.bus.events)
    assert "goal unlock" in thinking
    assert "empty after page" not in thinking


@pytest.mark.asyncio
async def test_empty_after_a_page_asks_for_the_pdf_without_stripping_it() -> None:
    from arelis.core.claims import ExactnessNeed
    from arelis.core.turn_goal import derive_turn_goal

    loop = _FakeLoop()
    ask = "Search the web. Write the result as a PDF."
    r = _scratch(content="")
    ctx = _ctx(text=ask)
    ctx.research_mode = True
    ctx.goal = derive_turn_goal(ask, role="research", research_mode=True)
    ctx.exact_need = ExactnessNeed(
        False,
        True,
        False,
        False,
        needs_document=True,
        kinds=("web", "document"),
    )
    ctx.last_ok_tool_name = "scrape"
    ctx.last_ok_tool_out = "Site: nasa.gov\n" + ("methane and carbon dioxide. " * 40)
    ctx.tool_names = {"scrape", "document", "web_search"}
    r.tool_names = ctx.tool_names
    assert await apply_no_call_path(loop, ctx, r, 4) is False
    assert ctx.document_nudge_used is True
    assert ctx.page_write_nudge_used is False
    assert "document" in ctx.tool_names
    assert r.offer_tools is True
    thinking = " ".join(str(e.payload.get("text") or "") for e in loop.bus.events)
    assert "report still needs a file" in thinking





@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "tool"),
    [
        (
            "no need to look at the book, its just crazy that she wrote a scenario",
            "desktop",
        ),
        (
            "i never asked you to do anything, why did you open your browser, check the time",
            "browser",
        ),
    ],
)
async def test_declined_or_complaining_text_injects_no_tool(text: str, tool: str) -> None:
    loop = _FakeLoop()
    r = _scratch(
        text=text,
        content="Sure.",
        tool_names={tool},
        available={tool},
        visible={tool},
        available_all={tool},
    )
    ctx = _ctx(text=text)
    ctx.tool_names = {tool}
    await apply_no_call_path(loop, ctx, r, 0)
    assert r.calls == []
    assert loop._expected_tools == set()




_MOON_DUMP = (
    "API VERSION: 1.2\n"
    "Target body name: Moon (301)\n"
    "Center body name: Earth (399)\n"
)
_CATALOG_TOOLS = [{"type": "function", "function": {"name": "catalog"}}]


@pytest.mark.asyncio
async def test_empty_after_data_dump_retry_turns_tools_off() -> None:
    """Retry branch itself drops every tool, then a second empty ships the fallback."""
    ask = "how far away is the moon right now?"
    loop = _FakeLoop()
    r = _scratch(
        content="",
        text=ask,
        tool_names={"catalog"},
        ollama_tools=list(_CATALOG_TOOLS),
        offer_tools=True,
    )
    ctx = _ctx(
        text=ask,
        last_ok_tool_out=_MOON_DUMP,
        last_ok_tool_name="catalog",
        tool_names={"catalog"},
        ollama_tools=list(_CATALOG_TOOLS),
        offer_tools=True,
    )
    assert await apply_no_call_path(loop, ctx, r, 2) is False
    assert ctx.tool_answer_nudge_used is True
    # Schemas stay. The cleared names are what stop another call.
    assert r.ollama_tools == list(_CATALOG_TOOLS)
    assert r.offer_tools is False
    assert ctx.ollama_tools == list(_CATALOG_TOOLS)
    assert ctx.offer_tools is False
    assert not ctx.tool_names
    assert loop.finished is None

    r2 = _scratch(
        content="", text=ask, tool_names=set(), ollama_tools=[], offer_tools=False
    )
    assert await apply_no_call_path(loop, ctx, r2, 3) is True
    assert loop.finished is not None
    shipped = loop.finished[0]
    assert "could not put it into words" in shipped
    assert "API VERSION" not in shipped
