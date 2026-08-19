"""Soak-regression tests for production tool-routing hardening."""

from __future__ import annotations

from datetime import datetime
from email import message_from_bytes
from pathlib import Path

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.agenda_complete import (
    complete_agenda_draft,
    fill_agenda_args,
    normalize_agenda_start,
    parse_agenda_utterance,
)
from arelis.core.email_complete import (
    complete_email_draft,
    fill_send_email_args,
    parse_email_utterance,
)
from arelis.core.memory import ChatMessage
from arelis.core.plan_nudge import select_plan
from arelis.core.sms_complete import (
    complete_sms_draft,
    fill_send_sms_args,
    normalize_sms_args,
)
from arelis.mail import build_message
from arelis.tools.base import ToolResult


def test_sms_message_alias_becomes_body() -> None:
    out = normalize_sms_args(
        {"to": "wife", "message": "I love you, Robin."}
    )
    assert out["body"] == "I love you, Robin."
    filled = fill_send_sms_args(
        {"to": "+15555550123", "message": "I love you"},
        None,
    )
    assert filled["body"] == "I love you"


def test_sms_multi_to_takes_first() -> None:
    out = normalize_sms_args({"to": "robin, wife", "body": "hi"})
    assert out["to"] == "robin"


def test_sms_yes_please_revives_complete_draft() -> None:
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin Hale",
            phone="5555550123",
            digits=normalize_phone("5555550123"),
            aliases=("wife", "robbie"),
        )
    }
    history = [
        ChatMessage(
            role="user",
            content="Send a text to my wife saying that I love her",
        ),
        ChatMessage(
            role="assistant",
            content="Would you like me to send her a text message?",
        ),
    ]
    draft = complete_sms_draft("Yes please", history=history, contacts=book)
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "wife"
    assert "love" in draft.body.lower()


def test_email_xlsx_not_analyze() -> None:
    from arelis.core.claims import detect_analyze_ask, detect_exactness_need
    from arelis.core.plan_nudge import select_plan
    from arelis.core.preflight import detect_intents

    raw = (
        "email this document to alex@example.com\n"
        "Q3-Budget_Draft_Final.xlsx"
    )
    assert not detect_analyze_ask(raw)
    assert "analyze" not in detect_exactness_need(raw).kinds
    kinds = [h.kind for h in detect_intents(raw)]
    assert "compose_email" in kinds
    assert "analyze" not in kinds
    plan = select_plan(raw, preflight_kinds=kinds)
    assert plan is not None
    assert plan.id == "compose_email"
    draft = complete_email_draft(raw)
    assert draft is not None
    assert draft.tool_to == "alex@example.com"
    assert "Q3-Budget_Draft_Final.xlsx" in draft.attach_path.replace("\\", "/")
    assert not draft.attach_path.lower().endswith(".png")


def test_email_path_followup_revives_attach() -> None:
    from arelis.core.claims import detect_analyze_ask

    history = [
        ChatMessage(
            role="user",
            content=(
                "email this document to alex@example.com\n"
                "Q3-Budget_Draft_Final.xlsx"
            ),
        ),
        ChatMessage(
            role="assistant",
            content="Attachment not found at /drops/…",
        ),
    ]
    follow = (
        r'the file is located at "C:\Users\you\Downloads\Q3-Budget_Draft_Final.xlsx"'
    )
    assert not detect_analyze_ask(follow)
    draft = complete_email_draft(follow, history=history)
    assert draft is not None
    assert draft.tool_to == "alex@example.com"
    assert "Downloads" in draft.attach_path.replace("/", "\\")
    assert draft.attach_path.lower().endswith(".xlsx")


def test_email_attached_file_mid_sentence() -> None:
    raw = (
        "I have attached a file to this chat. "
        "Email the attached file to alex@example.com\n"
        "Q3-Budget_Draft_Final-2.xlsx"
    )
    from arelis.core.claims import detect_analyze_ask
    from arelis.core.plan_nudge import select_plan
    from arelis.core.preflight import detect_intents

    assert not detect_analyze_ask(raw)
    kinds = [h.kind for h in detect_intents(raw)]
    assert "compose_email" in kinds
    assert "analyze" not in kinds
    assert select_plan(raw, preflight_kinds=kinds).id == "compose_email"
    draft = complete_email_draft(raw)
    assert draft is not None
    assert draft.tool_to == "alex@example.com"
    assert "Q3-Budget_Draft_Final-2.xlsx" in draft.attach_path


def test_compose_email_plan_not_inbox() -> None:
    plan = select_plan(
        "email a file to you@gmail.com",
        preflight_kinds=["compose_email"],
    )
    assert plan is not None
    assert plan.id == "compose_email"
    assert "send_email" in plan.steps
    assert "inbox" not in plan.steps
    assert plan.skip_progress is True


def test_agenda_delete_anniversary_calendar_event() -> None:
    from arelis.core.agenda_complete import looks_like_calendar_delete
    from arelis.core.preflight import detect_intents

    raw = "Delete that anniversary calendar event you just created"
    assert looks_like_calendar_delete(raw)
    kinds = [h.kind for h in detect_intents(raw)]
    assert "agenda_delete" in kinds
    plan = select_plan(raw, preflight_kinds=kinds)
    assert plan is not None
    assert plan.id == "agenda_delete"


def test_agenda_read_preflight_and_plan() -> None:
    from arelis.core.preflight import detect_intents

    raw = "What's on my calendar?"
    kinds = [h.kind for h in detect_intents(raw)]
    assert "agenda_read" in kinds
    plan = select_plan(raw, preflight_kinds=kinds)
    assert plan is not None
    assert plan.id == "agenda"
    assert "never invent meetings" in plan.message.lower()


def test_email_that_image_with_subject_and_history_path() -> None:
    history = [
        ChatMessage(
            role="assistant",
            content=(
                "Generated image.\n"
                "Saved: outputs/images/soak/soak_demo.png\n"
                "Call vision with this path to describe it."
            ),
        )
    ]
    raw = (
        "Email that image to you@gmail.com with subject Farmhouse photo"
    )
    draft = complete_email_draft(raw, history=history)
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "you@gmail.com"
    assert draft.subject == "Farmhouse photo"
    assert "soak_demo.png" in draft.attach_path.replace("\\", "/")
    args = fill_send_email_args({}, draft)
    assert args["attach"].endswith("soak_demo.png")
    assert args["subject"] == "Farmhouse photo"


def test_email_file_to_literal_address_with_path() -> None:
    raw = (
        'Can you email a file to you@gmail.com ? '
        r'"C:\Users\you\Downloads\q3-budget.pdf"'
    )
    draft = parse_email_utterance(raw)
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "you@gmail.com"
    assert "q3-budget.pdf" in draft.attach_path.replace("/", "\\")
    args = fill_send_email_args({}, draft)
    assert args["to"] == "you@gmail.com"
    assert args["attach"].endswith("q3-budget.pdf")


def test_email_literal_not_stolen_by_robin_history() -> None:
    history = [
        ChatMessage(role="user", content="text my wife that I love her"),
        ChatMessage(role="assistant", content="Sent."),
        ChatMessage(
            role="user",
            content="Can you email a file to you@gmail.com?",
        ),
    ]
    draft = complete_email_draft(
        'email it to you@gmail.com',
        history=history,
    )
    assert draft is not None
    assert draft.tool_to == "you@gmail.com"
    assert "robin" not in draft.to.lower()


def test_mail_build_message_attaches_pdf(tmp_path: Path) -> None:
    pdf = tmp_path / "q3-budget.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    msg = build_message(
        sender="me@example.com",
        from_name="Arelis",
        to="you@example.com",
        subject="q3-budget.pdf",
        body="Please see the attached file.",
        attachments=[pdf],
    )
    raw = msg.as_bytes()
    parsed = message_from_bytes(raw)
    names = []
    for part in parsed.walk():
        fn = part.get_filename()
        if fn:
            names.append(fn)
    assert "q3-budget.pdf" in names


def test_agenda_august_13th_uses_current_year() -> None:
    fixed = datetime(2026, 8, 11, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    draft = parse_agenda_utterance(
        "Create a calendar event on August 13th at 7am. It is my anniversary"
    )
    assert draft is not None
    assert draft.complete
    assert "Anniversary" in draft.summary or "anniversary" in draft.summary.lower()
    start = datetime.fromisoformat(draft.start)
    assert start.year == 2026
    assert start.month == 8
    assert start.day == 13
    assert start.hour == 7

    clamped = normalize_agenda_start(
        "2023-08-13T07:00:00-04:00", now=fixed
    )
    assert datetime.fromisoformat(clamped).year == 2026


def test_agenda_rewrites_today_to_create() -> None:
    draft = complete_agenda_draft(
        "Create a calendar event on August 13th at 7am. It is my anniversary"
    )
    assert draft is not None and draft.complete
    out = fill_agenda_args({"action": "today", "provider": "google"}, draft)
    assert out["action"] == "create"
    assert out["summary"] == draft.summary
    assert out["provider"] == "google"
    assert "2023" not in out["start"]


def test_agenda_yes_please_revives_draft() -> None:
    history = [
        ChatMessage(
            role="user",
            content=(
                "Create a calendar event on August 13th at 7am. "
                "It is my anniversary"
            ),
        ),
        ChatMessage(
            role="assistant",
            content="Would you like me to proceed with creating this event?",
        ),
    ]
    draft = complete_agenda_draft("Yes, please", history=history)
    assert draft is not None
    assert draft.complete
    assert datetime.fromisoformat(draft.start).day == 13


def test_weather_and_agenda_create_plans_skip_progress() -> None:
    weather = select_plan("What's the weather today?", preflight_kinds=["weather"])
    assert weather is not None
    assert weather.id == "weather"
    assert weather.skip_progress is True
    agenda = select_plan(
        "Create a calendar event tomorrow at 4pm",
        preflight_kinds=["agenda_create"],
    )
    assert agenda is not None
    assert agenda.id == "agenda_create"
    assert agenda.skip_progress is True


def test_hide_daily_wander_drops_web_search_on_weather() -> None:
    from arelis.core.agent_loop import _hide_daily_wander

    out = _hide_daily_wander(
        {"weather", "web_search", "scrape", "send_sms"},
        {"weather"},
    )
    assert "weather" in out
    assert "web_search" not in out
    assert "scrape" not in out
    assert "send_sms" not in out


def test_hide_daily_wander_drops_sms_on_agenda() -> None:
    from arelis.core.agent_loop import _hide_daily_wander

    out = _hide_daily_wander(
        {"agenda", "send_sms", "send_email", "browser"},
        {"agenda"},
    )
    assert "agenda" in out
    assert "send_sms" not in out
    assert "send_email" not in out
    assert "browser" not in out


def test_hide_daily_wander_drops_browser_on_sms() -> None:
    from arelis.core.agent_loop import _hide_daily_wander

    out = _hide_daily_wander(
        {"send_sms", "browser", "web_search", "scrape", "contacts", "image"},
        {"send_sms"},
    )
    assert "send_sms" in out
    assert "browser" not in out
    assert "web_search" not in out
    assert "scrape" not in out
    assert "image" not in out


def test_hide_daily_wander_drops_browser_on_tasks() -> None:
    from arelis.core.agent_loop import _hide_daily_wander

    out = _hide_daily_wander(
        {"tasks", "browser", "scrape", "web_fetch", "weather", "web_search"},
        {"tasks"},
    )
    assert "tasks" in out
    assert "browser" not in out
    assert "weather" not in out
    assert "web_search" not in out
    out_sms = _hide_daily_wander(
        {"tasks", "send_sms", "browser"},
        {"tasks"},
    )
    assert "send_sms" not in out_sms


def test_hide_daily_wander_drops_web_search_on_browser() -> None:
    from arelis.core.agent_loop import _hide_daily_wander

    out = _hide_daily_wander(
        {"browser", "web_search", "scrape", "web_fetch", "research_report", "weather"},
        {"browser"},
    )
    assert "browser" in out
    assert "web_search" not in out
    assert "scrape" not in out
    assert "web_fetch" not in out
    assert "research_report" not in out


# ---------------------------------------------------------------------------
# AgentLoop: first wrong tool injects the daily tool (clunk board)
# ---------------------------------------------------------------------------


class _Stub:
    def __init__(self, name: str, *, risk: str = "read") -> None:
        self.name = name
        self.description = name
        self.risk = risk
        self.parameters_schema: dict = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
        self.calls: list[dict] = []

    async def run(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(ok=True, output=f"{self.name} ok", data=dict(kwargs))


class _ScriptRouter:
    def __init__(self, script: list[list[tuple[str, object]]]) -> None:
        self.script = script
        self.i = 0
        self.active_model = "mock"
        self.default_role = "fast"

    def model_for(self, role=None) -> str:
        return "mock"

    async def ensure_role(self, role, *, force: bool = False) -> str:
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item


def _native(name: str, args: dict | None = None) -> dict:
    return {
        "type": "function",
        "function": {"name": name, "arguments": args or {}},
    }


async def _allow(*_a: object, **_k: object) -> str:
    return "allow"


async def _run_clunk(
    user: str,
    tools: list[_Stub],
    script: list[list[tuple[str, object]]],
    agent_overrides: dict[str, object] | None = None,
) -> tuple[list[str], str]:
    import asyncio

    from arelis.core.agent_loop import AgentLoop
    from arelis.core.bus import EventBus
    from arelis.core.events import Event, EventType
    from arelis.core.memory import SessionMemory
    from arelis.tools.base import ToolRegistry

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    loop = AgentLoop(
        bus,
        _ScriptRouter(script),  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "json_fallback": True,
                "skill_cards": True,
                "skill_tool_subset": True,
                "intent_preflight": True,
                "weather_force_call": True,
                "sms_force_call": True,
                "email_force_call": True,
                "agenda_force_call": True,
                "confirm_send": True,
                "confirm_writes": True,
                "turn_telemetry": False,
                "chat_fast_path": False,
                **(agent_overrides or {}),
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run(user, "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    starts = [
        str(e.payload.get("tool") or "")
        for e in events
        if e.type == EventType.TOOL_START
    ]
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    return starts, thinking


@pytest.mark.asyncio
async def test_weather_web_search_injects_weather_same_turn() -> None:
    weather = _Stub("weather")
    search = _Stub("web_search")
    starts, thinking = await _run_clunk(
        "What's the weather like outside?",
        [weather, search],
        [
            [("tool_calls", [_native("web_search", {"query": "Springfield forecast"})])],
            [("token", "Overcast, 68F.")],
        ],
    )
    assert starts == ["weather"]
    assert search.calls == []
    assert weather.calls
    assert "inject  weather from intent" in thinking


@pytest.mark.asyncio
async def test_named_city_weather_search_injects_place() -> None:
    weather = _Stub("weather")
    search = _Stub("web_search")
    starts, thinking = await _run_clunk(
        "web search Metropolis Illinois weather tomorrow",
        [weather, search],
        [
            [("tool_calls", [_native("web_search", {"query": "Metropolis Illinois weather"})])],
            [("token", "Rain tomorrow in Metropolis, high 81.")],
        ],
    )
    assert starts == ["weather"]
    assert search.calls == []
    assert weather.calls
    args = weather.calls[0]
    assert "metropolis" in str(args.get("place") or "").lower()
    assert int(args.get("days") or 0) >= 2
    assert "inject  weather from intent" in thinking


@pytest.mark.asyncio
async def test_two_city_weather_keeps_the_second_place() -> None:
    weather = _Stub("weather")
    starts, thinking = await _run_clunk(
        "What's the weather in Springfield Illinois and Metropolis Illinois?",
        [weather],
        [
            [
                (
                    "tool_calls",
                    [_native("weather", {"place": "Metropolis, Illinois", "days": 3})],
                )
            ],
            [
                (
                    "tool_calls",
                    [_native("weather", {"place": "Springfield, Illinois", "days": 3})],
                )
            ],
            [("token", "Both look mild.")],
        ],
    )
    assert len(weather.calls) == 2
    blob = " ".join(str(c.get("place") or "") for c in weather.calls).lower()
    assert "springfield" in blob
    assert "metropolis" in blob
    assert "Unknown tool" not in thinking
    assert starts.count("weather") == 2


@pytest.mark.asyncio
async def test_delete_named_weather_briefing_does_not_inject_weather() -> None:
    schedule = _Stub("schedule", risk="write")
    weather = _Stub("weather")
    starts, thinking = await _run_clunk(
        "please delete the second briefing named Morning Weather Briefing",
        [schedule, weather],
        [
            [
                (
                    "tool_calls",
                    [
                        _native(
                            "schedule",
                            {"action": "delete", "id": "morning-weather-briefing"},
                        )
                    ],
                )
            ],
            [("token", "Deleted Morning Weather Briefing.")],
        ],
    )
    assert starts == ["schedule"]
    assert weather.calls == []
    assert "inject  weather" not in thinking
    assert "weather ask" not in thinking
    browser = _Stub("browser")
    search = _Stub("web_search")
    scrape = _Stub("scrape")
    starts, thinking = await _run_clunk(
        "Search for interferometry videos and tell me the top three results.",
        [browser, search, scrape],
        [
            [
                (
                    "tool_calls",
                    [_native("web_search", {"query": "interferometry videos"})],
                )
            ],
            [("token", "Here are three videos from the YouTube tab.")],
        ],
        {"scrape_after_search": True},
    )
    assert starts == ["browser"]
    assert search.calls == []
    assert scrape.calls == []
    assert browser.calls
    assert browser.calls[0].get("action") == "search"
    assert "youtube" in str(browser.calls[0].get("site") or "").lower()
    assert "tell me" not in str(browser.calls[0].get("query") or "").lower()
    assert "inject  browser from intent" in thinking


@pytest.mark.asyncio
async def test_sms_web_search_injects_on_first_redirect(monkeypatch) -> None:
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin Hale",
            phone="5555550123",
            digits=normalize_phone("5555550123"),
            aliases=("wife", "robbie"),
        )
    }
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )
    sms = _Stub("send_sms", risk="side_effect")
    search = _Stub("web_search")
    starts, thinking = await _run_clunk(
        "Text my wife saying dinner is at 7",
        [sms, search],
        [
            [
                (
                    "tool_calls",
                    [_native("web_search", {"query": "Robin Hale phone"})],
                )
            ],
            [("token", "Confirm card is up.")],
        ],
        # Preinject now raises the card before the first model round, so with it
        # on this turn never reaches the redirect. Turning it off is the only way
        # to keep testing the redirect that catches a mid-turn wander.
        {"sms_preinject": False},
    )
    assert starts == ["send_sms"]
    assert search.calls == []
    assert sms.calls
    assert "inject  send_sms from draft" in thinking
    assert sms.calls[0].get("to") == "wife"


@pytest.mark.asyncio
async def test_complete_draft_preinjects_before_the_model(monkeypatch) -> None:
    """The default path for a complete draft: Allow goes up before the model.

    Same outcome as the redirect — web_search never runs and the draft keeps its
    recipient — reached one round earlier, which is the point of cf9ece4.
    """
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin Hale",
            phone="5555550123",
            digits=normalize_phone("5555550123"),
            aliases=("wife", "robbie"),
        )
    }
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )
    sms = _Stub("send_sms", risk="side_effect")
    search = _Stub("web_search")
    starts, thinking = await _run_clunk(
        "Text my wife saying dinner is at 7",
        [sms, search],
        [
            [
                (
                    "tool_calls",
                    [_native("web_search", {"query": "Robin Hale phone"})],
                )
            ],
            [("token", "Confirm card is up.")],
        ],
    )
    assert starts == ["send_sms"]
    assert search.calls == []
    assert sms.calls
    assert sms.calls[0].get("to") == "wife"
    assert "pre-model" in thinking


@pytest.mark.asyncio
async def test_sms_contacts_runs_when_recipient_missing(monkeypatch) -> None:
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin Hale",
            phone="5555550123",
            digits=normalize_phone("5555550123"),
            aliases=("wife", "robbie"),
        )
    }
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    sms = _Stub("send_sms", risk="side_effect")
    contacts = _Stub("contacts")
    starts, thinking = await _run_clunk(
        "text my wife and daughter that everything will be okay",
        [sms, contacts],
        [
            [("tool_calls", [_native("contacts", {"action": "list"})])],
            [("token", "I need daughter's number.")],
        ],
    )
    assert "contacts" in starts
    assert "send_sms" not in starts
    assert "redirect  contacts → sms" not in thinking
    assert contacts.calls


class _FailSms(_Stub):
    async def run(self, **kwargs: object) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(
            ok=False,
            output="[fail:send_sms] Missing recipient.",
            data=dict(kwargs),
        )


@pytest.mark.asyncio
async def test_sms_contacts_after_failed_send_does_not_reinject(
    monkeypatch,
) -> None:
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin Hale",
            phone="5555550123",
            digits=normalize_phone("5555550123"),
            aliases=("wife", "robbie"),
        )
    }
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    sms = _FailSms("send_sms", risk="side_effect")
    contacts = _Stub("contacts")
    starts, thinking = await _run_clunk(
        "Text my wife saying dinner is at 7",
        [sms, contacts],
        [
            [
                (
                    "tool_calls",
                    [_native("send_sms", {"to": "wife", "body": "dinner is at 7"})],
                )
            ],
            [("tool_calls", [_native("contacts", {"action": "list"})])],
            [("token", "Need a number.")],
        ],
    )
    assert starts[0] == "send_sms"
    assert "contacts" in starts
    assert thinking.count("inject  send_sms from draft") == 0
    assert contacts.calls


@pytest.mark.asyncio
async def test_email_analyze_injects_send_email() -> None:
    email = _Stub("send_email", risk="side_effect")
    analyze = _Stub("analyze")
    starts, thinking = await _run_clunk(
        "send an email to you@gmail.com subject: test, body: "
        "this is a test email disregard we are measuring latency",
        [email, analyze],
        [
            [("tool_calls", [_native("analyze", {"path": "C:\\\\tmp\\\\x.xlsx"})])],
            [("token", "Confirm card is up.")],
        ],
    )
    assert "send_email" in starts
    assert "analyze" not in starts
    assert analyze.calls == []
    assert "inject  send_email from draft" in thinking


@pytest.mark.asyncio
async def test_agenda_web_search_injects_create() -> None:
    agenda = _Stub("agenda", risk="side_effect")
    search = _Stub("web_search")
    starts, thinking = await _run_clunk(
        "Create a calendar event tomorrow at 4pm titled Clunk board test",
        [agenda, search],
        [
            [("tool_calls", [_native("web_search", {"query": "calendar app steps"})])],
            [("token", "Confirm card is up.")],
        ],
    )
    assert starts == ["agenda"]
    assert search.calls == []
    assert "inject  agenda create from draft" in thinking
    assert str(agenda.calls[0].get("action") or "") == "create"


def test_normalize_ollama_messages_parses_string_arguments() -> None:
    from arelis.core.agent_loop import _normalize_ollama_messages

    raw = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "tasks",
                        "arguments": '{"action": "list"}',
                    },
                }
            ],
        }
    ]
    out = _normalize_ollama_messages(raw)
    args = out[0]["tool_calls"][0]["function"]["arguments"]
    assert args == {"action": "list"}


def test_flatten_latex_integral() -> None:
    from arelis.ui.markdown import flatten_latex

    out = flatten_latex(
        r"The integral of \( x^2 \) is \[\int x^2 \, dx = \frac{x^3}{3} + C\]"
    )
    assert r"\(" not in out
    assert r"\[" not in out
    assert "x²" in out or "x^2" in out
    assert "∫" in out
