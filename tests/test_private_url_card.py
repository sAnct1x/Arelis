"""A web address that carries private text asks before it is opened.

On main the fetch goes out with no card. These tests are the ones that fail
there. A normal page, a link copied whole, and a token the user typed stay
quiet, and those guards pass on main too.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.evidence import EvidenceLedger
from arelis.core.orchestrator_confirm import OrchestratorConfirm
from arelis.core.turn_confirm import RUN, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.core.turn_execute import execute_call
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.ui.theme import apply_theme

_ACCOUNT = "ACCT-778899"
_OTHER = "REF-100200"
_MAIL = "https://track.example/click?id=ACCT-778899"
_CLINIC = "meet me at the clinic"


class _Tool:
    def __init__(self, name: str, risk: str) -> None:
        self.name = name
        self.risk = risk
        self.description = name
        self.parameters_schema = {"type": "object", "properties": {}}


class _Loop:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.tools = ToolRegistry()
        self.tools.register(_Tool("web_fetch", "read"))
        self.tools.register(_Tool("scrape", "read"))
        self.tools.register(_Tool("browser", "side_effect"))
        self.tools.register(_Tool("web_search", "read"))
        self._expected_tools: set[str] = set()
        self._trace: list[str] = []
        self._timer = None
        self._look = None
        self.tools_used: set[str] = set()
        self.confirm_writes = True
        self.confirm_image = True
        self.confirm_send = True
        self.confirm_browser = True
        self.confirm_desktop = True
        self.confirm_vision = True
        self.confirm_run = True
        self.ask_is_grant = True
        self._private_url_note = ""
        self.confirmations: list[tuple[str, dict, str]] = []
        self._decision = "allow"

    def _tool_message(self, name: str, content: str) -> dict[str, str]:
        return {"role": "tool", "tool_name": name, "content": content}

    async def request_confirm(
        self, confirm_id: str, tool: str, args: dict, summary: str
    ) -> str:
        del confirm_id
        self.confirmations.append((tool, dict(args), self._private_url_note))
        return self._decision

    async def _confirm_wait_heartbeat(self, name: str, started: float) -> None:
        del name, started
        await asyncio.Event().wait()


def _remember(ctx: TurnContext, tool: str, args: dict, output: str) -> None:
    marks = getattr(ctx, "private_marks", None)
    record = getattr(marks, "record", None)
    if callable(record):
        record(tool, args, output)


async def _read_inbox(ctx: TurnContext, output: str) -> None:
    """The card has to see what the inbox tool actually returned."""

    class _Bus:
        async def publish(self, event: object) -> None:
            del event

    class _Run:
        def __init__(self) -> None:
            self.bus = _Bus()
            self.max_rounds = 3
            self._look = None
            self._timer = None
            self.tools_used: set[str] = set()
            self._trace: list[str] = []
            self._receipts: list[dict] = []
            self.memory = SimpleNamespace(sink=None, messages=[])
            self.tool_output_chars = 8000
            self._expected_tools: set[str] = set()
            self._fail_replan_used = False
            self.tools = SimpleNamespace(get=lambda _name: None)

        def _tool_message(self, name: str, out: str) -> dict[str, str]:
            return {"role": "tool", "name": name, "content": out}

    scratch = SimpleNamespace(
        text=ctx.text,
        agent_cfg={"tool_summary_inject": False},
        available_all=set(),
        available=set(),
        visible=set(),
        tool_names=set(),
        sources=[],
        ledger=EvidenceLedger(),
        fail_counts={},
        web_search_ok=set(),
        page_ok=set(),
        sms_sent=set(),
        agenda_created=set(),
        weather_ok_places=set(),
        weather_days_retried=set(),
        exact_need=ctx.exact_need,
        offer_tools=False,
        ollama_tools=[],
        messages=[],
        sms_draft=None,
        email_draft=None,
    )
    await execute_call(
        _Run(),
        ctx,
        scratch,
        "inbox",
        {"action": "read"},
        summary="inbox",
        call_fp="inbox-read",
        round_i=1,
        call_i=0,
        fanout_results={0: (1, ToolResult(ok=True, output=output, data={}))},
    )


async def _ask(
    ctx: TurnContext,
    name: str,
    args: dict,
    *,
    loop: _Loop | None = None,
) -> _Loop:
    loop = loop or _Loop()
    action, _summary, _fp = await confirm_call(
        loop,
        ctx,
        name,
        args,
        text=ctx.text,
        fail_counts={},
        skip_counts={},
        messages=[],
        drop_wander=lambda _name: None,
    )
    loop.last_action = action  # type: ignore[attr-defined]
    return loop


async def test_private_text_in_fetch_url_asks() -> None:
    """An account number from email, pasted into a fetch, asks first.

    Allowing it covers that host for the rest of the turn. Another host
    still asks. Allowing writes for the turn does not skip the card.
    """
    ctx = TurnContext(text="what is in my inbox", role="fast")
    ctx.allow_writes_this_turn = True
    await _read_inbox(ctx, f"Invoice {_ACCOUNT} is due. Also see {_OTHER}.")
    loop = await _ask(
        ctx,
        "web_fetch",
        {"url": f"https://x.example/?d={_ACCOUNT}", "method": "GET"},
    )
    assert loop.confirmations, "the fetch went out with no card"
    note = loop.confirmations[0][2]
    assert "your email" in note
    assert _ACCOUNT not in note
    assert loop.last_action == RUN

    again = await _ask(
        ctx,
        "web_fetch",
        {"url": f"https://x.example/other?d={_OTHER}"},
        loop=loop,
    )
    assert len(again.confirmations) == 1

    other = await _ask(
        ctx,
        "web_fetch",
        {"url": f"https://y.example/?d={_OTHER}"},
        loop=loop,
    )
    assert len(other.confirmations) == 2
    assert "your email" in other.confirmations[1][2]


async def test_private_phrase_in_path_and_subdomain_asks() -> None:
    """Four words from a note, in a host label or a path, ask first."""
    ctx = TurnContext(text="open the clinic page", role="fast")
    ctx.allow_writes_this_turn = True
    _remember(ctx, "notes", {"action": "read"}, f"Reminder: {_CLINIC} tomorrow.")
    host = await _ask(
        ctx,
        "browser",
        {"action": "open", "url": "https://meet-me-at-the-clinic.x.example/"},
    )
    assert host.confirmations, "the browser opened with no card"
    assert "your memory" in host.confirmations[0][2]
    path = await _ask(
        ctx,
        "browser",
        {"action": "navigate", "url": "https://x.example/meet-me-at-the-clinic"},
    )
    assert path.confirmations, "the path opened with no card"
    assert "your memory" in path.confirmations[0][2]


async def test_normal_search_stays_card_free() -> None:
    """A page that does not repeat the private text stays quiet."""
    ctx = TurnContext(text="what is saturn", role="fast")
    _remember(ctx, "inbox", {"action": "read"}, f"Invoice {_ACCOUNT} is due.")
    _remember(ctx, "notes", {"action": "read"}, "We will be together soon enough friend.")
    wiki = await _ask(
        ctx,
        "web_fetch",
        {"url": "https://en.wikipedia.org/wiki/Saturn"},
    )
    assert not wiki.confirmations
    word = await _ask(ctx, "web_fetch", {"url": "https://x.example/together"})
    assert not word.confirmations
    search = await _ask(
        ctx,
        "web_search",
        {"query": f"lookup {_ACCOUNT}"},
    )
    assert not search.confirmations
    # The window confirm is off, so a card here would be the private-text
    # check firing on a search or a map, which it must not.
    quiet = _Loop()
    quiet.confirm_browser = False
    browser_search = await _ask(
        ctx,
        "browser",
        {"action": "search", "url": f"https://www.google.com/search?q={_ACCOUNT}"},
        loop=quiet,
    )
    assert not browser_search.confirmations
    maps = _Loop()
    maps.confirm_browser = False
    await _ask(
        ctx,
        "browser",
        {"action": "maps", "url": f"https://maps.example/dir?q={_ACCOUNT}"},
        loop=maps,
    )
    assert not maps.confirmations


async def test_link_copied_from_email_stays_card_free() -> None:
    """A tracking link copied whole from the mail is the link, not a leak."""
    ctx = TurnContext(text="open the link in that mail", role="fast")
    _remember(
        ctx,
        "inbox",
        {"action": "read"},
        f"Click here: {_MAIL}\nAccount {_ACCOUNT}",
    )
    loop = await _ask(ctx, "web_fetch", {"url": _MAIL})
    assert not loop.confirmations


async def test_user_typed_token_stays_card_free() -> None:
    """A code the user typed this turn is theirs to look up."""
    ctx = TurnContext(text=f"look up {_ACCOUNT} for me", role="fast")
    _remember(ctx, "inbox", {"action": "read"}, f"The code is {_ACCOUNT}.")
    loop = await _ask(
        ctx,
        "web_fetch",
        {"url": f"https://x.example/?d={_ACCOUNT}"},
    )
    assert not loop.confirmations


async def test_encoded_token_still_asks() -> None:
    """Percent-encoding and plus signs do not hide the private text."""
    ctx = TurnContext(text="check the page", role="fast")
    _remember(ctx, "inbox", {"action": "read"}, f"Invoice {_ACCOUNT} is due.")
    _remember(ctx, "notes", {"action": "read"}, _CLINIC)
    loop = _Loop()
    loop._decision = "skip"
    encoded = await _ask(
        ctx,
        "web_fetch",
        {"url": "https://x.example/?d=%41CCT-778899"},
        loop=loop,
    )
    assert encoded.confirmations, "the encoded account number did not ask"
    assert "your email" in encoded.confirmations[0][2]
    doubled = await _ask(
        ctx,
        "web_fetch",
        {"url": "https://z.example/?d=%2541CCT-778899"},
        loop=loop,
    )
    assert len(doubled.confirmations) == 2
    phrase = await _ask(
        ctx,
        "scrape",
        {"url": "https://y.example/meet+me+at+the+clinic"},
        loop=loop,
    )
    assert len(phrase.confirmations) == 3
    assert "your memory" in phrase.confirmations[-1][2]


async def test_private_url_card_has_no_batch_or_persist() -> None:
    """This card is one host, this time. No rest-of-turn, no don't-ask-again."""

    class _Card(OrchestratorConfirm):
        def __init__(self, loop: _Loop) -> None:
            self.bus = EventBus()
            self._confirm_waiters: dict[str, asyncio.Future[str]] = {}
            self._confirm_latest: str | None = None
            self._confirm_live: dict[str, dict] = {}
            self._agent_loop = loop
            self.tools = loop.tools
            self.config = {"agent": {"confirm_timeout_s": 2}}
            self.events: list[object] = []

            async def _publish(event: object) -> None:
                self.events.append(event)

            self.bus.publish = _publish  # type: ignore[method-assign]

    ctx = TurnContext(text="open the clinic page", role="fast")
    _remember(ctx, "notes", {"action": "read"}, _CLINIC)
    loop = _Loop()
    card = _Card(loop)
    loop.request_confirm = card._request_confirm  # type: ignore[method-assign]
    task = asyncio.create_task(
        confirm_call(
            loop,
            ctx,
            "browser",
            {"action": "open", "url": "https://meet-me-at-the-clinic.x.example/"},
            text=ctx.text,
            fail_counts={},
            skip_counts={},
            messages=[],
            drop_wander=lambda _name: None,
        )
    )
    for _ in range(50):
        if card.events:
            break
        await asyncio.sleep(0)
    else:
        task.cancel()
        raise AssertionError("no card was published")
    event = card.events[0]
    assert getattr(event, "type", None) == EventType.TOOL_CONFIRM
    payload = event.payload
    assert payload["batch_ok"] is False
    assert payload["persist_ok"] is False
    assert payload["persist_label"] == ""
    assert "your memory" in payload["note"]
    waiter = card._confirm_waiters.get(str(payload["id"]))
    assert waiter is not None
    waiter.set_result("skip")
    action, _summary, _fp = await task
    assert action != RUN


async def test_private_url_asks_in_filament() -> None:
    """Filament still asks, out loud, when the address carries private text."""
    ctx = TurnContext(text="what is in my inbox", role="fast")
    _remember(ctx, "inbox", {"action": "read"}, f"Invoice {_ACCOUNT} is due.")
    try:
        apply_theme("filament")
        loop = await _ask(
            ctx,
            "web_fetch",
            {"url": f"https://x.example/?d={_ACCOUNT}"},
        )
    finally:
        apply_theme("sodium")
    assert loop.confirmations, "filament opened the address with no card"
    assert "your email" in loop.confirmations[0][2]
