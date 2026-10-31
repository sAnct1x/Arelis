"""Pins apply_no_call_path / dispatch_calls return contracts before the split.

These two functions are the turn coordinator. The loop tests already cover
them through AgentLoop.run. This file calls them directly so a dispatch-table
extract cannot change nudge / inject / finish without a failing name.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from arelis.core.events import Event
from arelis.core.turn_context import TurnContext
from arelis.core.turn_dispatch import dispatch_calls
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
            chat_tools=lambda _names, *, param_hints=False: [],
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
        chat_tools=[],
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
async def test_search_cap_with_a_page_open_keeps_scrape_for_the_rest() -> None:
    """Live 2026-09-26 turn 41d1f60b: one DMS paper, then scrape was gone.

    The cap said call document and she could not open the 2023 paper.
    She went to recall and quoted an earlier turn until Stop.
    """
    from arelis.core.claims import ExactnessNeed

    loop = _FakeLoop()
    loop.tools.chat_tools = lambda names, *, param_hints=False: [{"name": n} for n in sorted(names)]
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
async def test_repeated_browser_open_does_not_paint_the_page_when_a_pdf_is_owed() -> None:
    from arelis.core.claims import ExactnessNeed
    from arelis.core.same_call import record_same_call, same_call_key

    loop = _FakeLoop()
    loop.tools.chat_tools = lambda names, *, param_hints=False: [{"name": n} for n in sorted(names)]
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


_MOON_DUMP = (
    "API VERSION: 1.2\n"
    "Target body name: Moon (301)\n"
    "Center body name: Earth (399)\n"
)
_CATALOG_TOOLS = [{"type": "function", "function": {"name": "catalog"}}]


