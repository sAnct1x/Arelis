"""#373: a pasted article is not a fetch, a CAS ask, or a tool round.

prepare_turn used to classify the whole paste. Ordinary prose then armed
web/CAS, pinned the tool-round hint, and the claims guard replaced a
drafted summary with the CAS refusal.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import _TOOL_ROUND_HINT, AgentLoop
from arelis.core.bus import EventBus
from arelis.core.claims import detect_exactness_need
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import prepare_turn, split_user_ask
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

pytestmark = pytest.mark.no_ui

_SUMMARY = (
    "The piece walks through a measurement and the model the authors tried "
    "to expand. It is a summary of the pasted text, not a CAS result."
)
_ARTICLE_BODY = (
    "The article discusses a factor of two in the measurement. "
    "Researchers tried to expand the model of the integral of motion. "
    "They wanted a closed form for the latest news on the topic. "
    + ("Ordinary prose about the findings continues here. " * 20)
)
_SUMMARIZE_ASK = "Summarize this long article.\n\n" + _ARTICLE_BODY
_URL_ASK = "Summarize this article: https://example.com/foo"
_CAS_ASK = (
    "I have been stuck on this homework problem for a while and I already "
    "tried the substitution they showed in lecture.\n\n"
    "Please find the integral of x**2 * sin(x) and give the closed form."
)


class _Tool:
    description = "probe"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(ok=True, output="ok")


class _RecordingRouter(_ScriptedRouter):
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        super().__init__(script)
        self.stream_messages: list[list[dict[str, Any]]] = []

    async def stream(self, role, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.stream_messages.append([dict(row) for row in messages])
        async for item in super().stream(role, messages, **kwargs):
            yield item


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in (
        "weather",
        "web_search",
        "scrape",
        "web_fetch",
        "user_location",
        "calculator",
        "cas",
    ):
        registry.register(_Tool(name))  # type: ignore[arg-type]
    return registry


def _agent_config() -> dict[str, Any]:
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = True
    cfg["llamacpp"] = {"default_cap": 8192}
    return cfg


def _loop(*, router: _ScriptedRouter | None = None) -> AgentLoop:
    return AgentLoop(
        EventBus(),
        router or _ScriptedRouter([[("token", _SUMMARY)]]),  # type: ignore[arg-type]
        _registry(),
        SessionMemory(),
        "persona",
        _agent_config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )


@pytest.mark.asyncio
async def test_pasted_article_summary_is_not_a_cas_or_fetch_round() -> None:
    instruction, provided_body = split_user_ask(_SUMMARIZE_ASK)
    assert instruction == "Summarize this long article."
    assert "factor of" in provided_body
    assert "expand the" in provided_body
    assert "integral of" in provided_body
    assert "latest news" in provided_body
    assert "article" in provided_body
    assert _ARTICLE_BODY in _SUMMARIZE_ASK

    loop = _loop()
    ctx = await prepare_turn(loop, _SUMMARIZE_ASK, "fast")
    assert ctx is not None
    assert ctx.expect_tool_round is False
    assert ctx.wants_fresh_page is False
    assert "symbolic" not in ctx.exact_need.kinds
    assert "web" not in ctx.exact_need.kinds
    assert not ctx.exact_need.needs_cas
    assert not ctx.exact_need.needs_web_evidence
    user_text = "\n".join(
        str(row.get("content") or "")
        for row in ctx.messages
        if row.get("role") == "user"
    )
    assert _ARTICLE_BODY in user_text
    assert _TOOL_ROUND_HINT not in {
        str(row.get("content") or "") for row in ctx.messages
    }

    drafted = _SUMMARY
    refuse = _exactness_finish_refuse(
        drafted,
        exact_need=ctx.exact_need,
        ledger=EvidenceLedger(),
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None

    router = _RecordingRouter([[("token", drafted)]])
    bus = EventBus()
    run_loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        _registry(),
        SessionMemory(),
        "persona",
        _agent_config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, run_loop.run(_SUMMARIZE_ASK, "fast"))
    done = next(event for event in events if event.type == EventType.ASSISTANT_DONE)
    assert done.payload["text"].strip() == drafted
    assert "this needs a CAS result" not in str(done.payload["text"])
    sent = run_loop._last_sent_messages or []
    hint_rows = [
        row for row in sent if row.get("content") == _TOOL_ROUND_HINT
    ]
    assert hint_rows == []
    for batch in router.stream_messages:
        assert _TOOL_ROUND_HINT not in {
            str(row.get("content") or "") for row in batch
        }

    url_ctx = await prepare_turn(_loop(), _URL_ASK, "fast")
    assert url_ctx is not None
    assert url_ctx.wants_fresh_page is True
    url_instruction, url_body = split_user_ask(_URL_ASK)
    assert url_body == ""
    assert url_instruction == _URL_ASK

    cas_ctx = await prepare_turn(_loop(), _CAS_ASK, "fast")
    assert cas_ctx is not None
    assert cas_ctx.exact_need.needs_cas
    assert "symbolic" in cas_ctx.exact_need.kinds
    assert detect_exactness_need(_CAS_ASK).needs_cas
