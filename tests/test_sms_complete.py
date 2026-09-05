"""SMS draft completion across turns."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import ChatMessage, SessionMemory
from arelis.core.sms_complete import (
    complete_sms_draft,
    fill_send_sms_args,
    parse_sms_utterance,
    resolve_sms_alias,
)
from arelis.tools.base import ToolRegistry, ToolResult


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "5551112222")
        raw_aliases = fields.get("aliases") or ()
        if isinstance(raw_aliases, str):
            raw_aliases = (raw_aliases,)
        out[alias] = Contact(
            alias=alias,
            name=str(fields.get("name") or ""),
            phone=phone,
            digits=normalize_phone(phone),
            aliases=tuple(str(a).lower() for a in raw_aliases),
        )
    return out


def test_parse_text_brian_with_body() -> None:
    draft = parse_sms_utterance("Text Brian: Running 10 minutes late")
    assert draft is not None
    assert draft.complete
    assert draft.to.lower().startswith("brian")
    assert "Running 10 minutes late" in draft.body


def test_parse_text_a_raw_number_and_tell_him() -> None:
    """A number the user typed is the recipient. Letter-only `to` hid send_sms."""
    draft = parse_sms_utterance(
        "chillin, chillin, i want you to text 5551112222 and tell him hes late"
    )
    assert draft is not None
    assert draft.complete
    assert "5551112222" in draft.to
    assert "late" in draft.body.lower()
    filled = fill_send_sms_args({}, draft)
    assert filled["to"] == "5551112222"
    assert "late" in filled["body"].lower()


def test_send_sms_stays_visible_when_they_gave_a_number() -> None:
    from arelis.core.preflight import detect_intents
    from arelis.core.tool_subset import filter_tool_names

    text = "i want you to text 5551112222 and tell him hey"
    kinds = {h.kind for h in detect_intents(text)}
    assert "sms_send" in kinds
    visible = filter_tool_names(
        {"send_sms", "inbound_sms", "contacts", "weather"},
        role="fast",
        text=text,
        enabled=False,
        skill_subset=False,
    )
    assert "send_sms" in visible


def test_parse_send_a_text_message_to_wife() -> None:
    draft = parse_sms_utterance("Send a text message to my wife")
    assert draft is not None
    assert draft.to.lower() == "wife"
    assert draft.body == ""
    book = _book(wife={"name": "Robbie", "aliases": ("wife", "robbie")})
    done = complete_sms_draft("Send a text message to my wife", contacts=book)
    assert done is not None
    assert done.tool_to == "wife"


def test_history_merges_body_after_text_x() -> None:
    history = [
        ChatMessage(role="user", content="Text Brian"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(brian={"name": "Brian Montgomery", "aliases": ["brian"]})
    draft = complete_sms_draft(
        "Running 10 minutes late",
        history=history,
        contacts=book,
    )
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "brian"
    assert draft.body == "Running 10 minutes late"
    assert draft.source == "history"


def test_strips_i_want_it_to_say_wrapper() -> None:
    history = [
        ChatMessage(role="user", content="text my wife and daughter"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(
        wife={"name": "Robbie", "aliases": ("wife", "robbie")},
        piper={"name": "Piper Hale", "aliases": ("daughter", "piper")},
    )
    draft = complete_sms_draft(
        "i want it to say everything will be okay",
        history=history,
        contacts=book,
    )
    assert draft is not None
    assert draft.complete
    assert draft.body == "everything will be okay"
    assert set(draft.resolved_aliases) == {"wife", "piper"}


def test_sms_body_strips_i_want_the_text_message_to() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    draft = complete_sms_draft(
        'send a text message to my wife, i want the text message to "i love you"',
        contacts=book,
    )
    assert draft is not None
    assert draft.complete
    assert draft.body == "i love you"


def test_unknown_name_with_body_asks_for_a_number_not_a_contact() -> None:
    draft = complete_sms_draft(
        "text Jordan and tell him the table is ready",
        contacts=_book(),
    )
    assert draft is not None
    assert not draft.complete
    assert "Jordan" in draft.missing
    from arelis.core.sms_complete import sms_preflight_nudge

    nudge = sms_preflight_nudge(draft)
    assert "number" in nudge.lower()
    assert "do not require" in nudge.lower()


def test_a_typed_number_after_an_unknown_name_completes_the_send() -> None:
    history = [
        ChatMessage(role="user", content="text Jordan and tell him the table is ready"),
        ChatMessage(role="assistant", content="What's Jordan's number?"),
    ]
    draft = complete_sms_draft(
        "5551112222",
        history=history,
        contacts=_book(),
    )
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "5551112222"
    assert "table is ready" in draft.body


def test_two_raw_numbers_are_a_complete_multi_send() -> None:
    draft = complete_sms_draft(
        "text 5551112222 and 5551113333 that I am on the way",
        contacts=_book(),
    )
    assert draft is not None
    assert draft.complete
    assert not draft.missing
    assert set(draft.resolved_aliases) == {"5551112222", "5551113333"}


def test_multi_recipient_incomplete_when_contact_missing() -> None:
    book = _book(wife={"name": "Robbie", "aliases": ("wife",)})
    draft = complete_sms_draft(
        "text my wife and daughter that everything will be okay",
        contacts=book,
    )
    assert draft is not None
    assert not draft.complete
    assert "daughter" in draft.missing
    assert draft.body == "everything will be okay"


def test_tell_him_body_peels_from_recipient() -> None:
    book = _book(
        brightly={
            "name": "Sam Brightly",
            "aliases": ("sam brightly", "sam brightley", "brightley"),
        },
        me={"name": "Sam Whitlock", "aliases": ("sam", "myself")},
    )
    draft = complete_sms_draft(
        "text Sam Brightley and tell him I love him",
        contacts=book,
    )
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "brightly"
    assert draft.body.lower() == "i love you"


def test_sam_brightley_does_not_resolve_to_me() -> None:
    book = _book(
        brightly={"name": "Sam Brightly", "aliases": ("sam brightly",)},
        me={"name": "Sam Whitlock", "aliases": ("sam", "myself")},
    )
    assert resolve_sms_alias("Sam Brightley", book) == "brightly"
    assert resolve_sms_alias("Sam Brightly", book) == "brightly"


def test_openx_com_does_not_become_sms_body() -> None:
    history = [
        ChatMessage(role="user", content="text Sam Brightley and tell him"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(
        brightly={"name": "Sam Brightly", "aliases": ("sam brightly", "sam brightley")},
        me={"name": "Sam Whitlock", "aliases": ("sam",)},
    )
    from arelis.core.sms_complete import looks_like_browser_or_url

    assert looks_like_browser_or_url("OpenX.com")
    assert looks_like_browser_or_url("open x.com")
    assert (
        complete_sms_draft("OpenX.com", history=history, contacts=book) is None
    )
    assert (
        complete_sms_draft("open x.com", history=history, contacts=book) is None
    )


def test_resolve_first_name_to_alias() -> None:
    book = _book(brian={"name": "Brian Montgomery", "aliases": ("brian",)})
    assert resolve_sms_alias("Brian", book) == "brian"
    assert resolve_sms_alias("Brian Montgomery", book) == "brian"


def test_fill_send_sms_args_from_draft() -> None:
    book = _book(wife={"name": "W", "aliases": ("wife",)})
    draft = complete_sms_draft(
        "text my wife that I'll be late",
        contacts=book,
    )
    assert draft and draft.complete
    filled = fill_send_sms_args({"to": "", "body": ""}, draft)
    assert filled["to"] == "wife"
    assert "late" in filled["body"].lower()


def test_text_message_to_wife_is_not_to_message() -> None:
    """STT often drops 'send a' and hears 'in a text message to my wife'."""
    book = _book(wife={"name": "Robin", "aliases": ("wife", "robbie")})
    spoken = (
        "in a text message to my wife and just tell her "
        "good nights, sweet dreams"
    )
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert draft.to.lower() == "wife"
    assert "message" not in draft.to.lower()
    assert "good night" in draft.body.lower()
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None
    assert done.complete
    assert done.tool_to == "wife"
    assert "sweet dreams" in done.body.lower()
    filled = fill_send_sms_args(
        {"to": "message", "body": "good nights, sweet dreams"},
        done,
        contacts=book,
    )
    assert filled["to"] == "wife"


def test_normalize_drops_channel_word_to() -> None:
    from arelis.core.sms_complete import normalize_sms_args

    out = normalize_sms_args({"to": "message", "body": "good night"})
    assert out.get("to") == ""
    assert out.get("body") == "good night"


def test_text_me_later_is_not_an_sms_draft() -> None:
    assert parse_sms_utterance("text me later about the optics run") is None
    assert complete_sms_draft("text me later about the optics run") is None


def test_write_a_text_file_is_not_sms() -> None:
    assert parse_sms_utterance("write a text file named note.txt") is None
    assert complete_sms_draft("write a temp file with hi") is None


def test_read_any_text_in_picture_is_not_sms() -> None:
    for spoken in (
        "read any text in that last picture",
        "read the text in this screenshot",
        "what text is in that image",
        "any text in the last picture",
    ):
        assert parse_sms_utterance(spoken) is None, spoken
        assert complete_sms_draft(spoken) is None, spoken


def test_remember_forget_and_tasks_do_not_become_sms_body() -> None:
    history = [
        ChatMessage(role="user", content="Text my wife"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(wife={"name": "M", "aliases": ("wife",)})
    for follow in (
        "Remember that my favorite test fruit is durian.",
        "Forget that my favorite test fruit is durian.",
        "List my tasks.",
        "Add a task titled operator-smoke-task.",
        "Add a goal titled Keep operator tests honest.",
        "Who is my wife in contacts?",
        "what is my wifes phone number?",
    ):
        assert complete_sms_draft(follow, history=history, contacts=book) is None


def test_contacts_phone_and_proceed_are_lookups() -> None:
    from arelis.core.sms_complete import (
        looks_like_contacts_followup,
        looks_like_contacts_utterance,
    )

    assert looks_like_contacts_utterance("Who is my wife in my contacts?")
    assert looks_like_contacts_utterance("what is my wifes phone number?")
    assert looks_like_contacts_utterance("What is her phone number?")
    from arelis.core.sms_complete import looks_like_contact_phone_ask

    assert looks_like_contact_phone_ask("what is her phone number?")
    assert looks_like_contact_phone_ask("what is my wifes phone number?")
    assert not looks_like_contact_phone_ask("Who is my wife in my contacts?")
    history = [
        ChatMessage(role="user", content="Who is my wife in my contacts?"),
        ChatMessage(role="assistant", content="I would need to call the tool."),
    ]
    assert looks_like_contacts_followup("proceed", history)
    assert not looks_like_contacts_followup("proceed")


def test_bare_yes_does_not_revive_sms_without_send_ask() -> None:
    history = [
        ChatMessage(
            role="user",
            content="Text my wife exactly: Arelis allow-deny test — please ignore.",
        ),
        ChatMessage(role="assistant", content="Stopped."),
    ]
    book = _book(wife={"name": "M", "aliases": ("wife",)})
    assert complete_sms_draft("yes", history=history, contacts=book) is None


def test_list_goals_does_not_become_sms_body() -> None:
    history = [
        ChatMessage(role="user", content="Text my wife"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(wife={"name": "M", "aliases": ("wife",)})
    assert (
        complete_sms_draft("list my goals", history=history, contacts=book) is None
    )


def test_analyze_followup_does_not_become_sms_body() -> None:
    history = [
        ChatMessage(role="user", content="Text my wife"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(wife={"name": "M", "aliases": ("wife",)})
    assert (
        complete_sms_draft(
            "summarize the csv at data/sales.csv",
            history=history,
            contacts=book,
        )
        is None
    )


def test_image_gen_does_not_become_sms_body() -> None:
    history = [
        ChatMessage(role="user", content="Text me"),
        ChatMessage(role="assistant", content="What should I say?"),
    ]
    book = _book(me={"name": "Me", "phone": "5550001111", "aliases": ("me",)})
    assert (
        complete_sms_draft(
            "Generate an image of cute puppies",
            history=history,
            contacts=book,
        )
        is None
    )
    assert parse_sms_utterance("text to image of cute puppies") is None


class _SmsStub:
    name = "send_sms"
    description = "sms"
    risk = "side_effect"
    parameters_schema = {
        "type": "object",
        "properties": {"to": {}, "body": {}},
        "required": ["to", "body"],
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(ok=True, output="queued", data=dict(kwargs))


class _Router:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
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
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item


async def _allow(*_a: Any, **_k: Any) -> str:
    return "allow"


@pytest.mark.asyncio
async def test_loop_nudges_when_model_skips_complete_sms(monkeypatch) -> None:
    """With pre-inject off, a model that only talks about texting gets nudged."""
    book = _book(brian={"name": "Brian", "aliases": ("brian",)})
    monkeypatch.setattr(
        "arelis.core.sms_complete.load_contacts", lambda: book
    )
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    tools = ToolRegistry()
    sms = _SmsStub()
    tools.register(sms)

    router = _Router(
        [
            [("token", "Sure, I can text Brian for you.")],
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "send_sms",
                                "arguments": {
                                    "to": "brian",
                                    "body": "Running late",
                                },
                            },
                        }
                    ],
                )
            ],
            [("token", "Confirm card is up.")],
        ]
    )
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": True,
                "sms_force_call": True,
                "sms_preinject": False,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("Text Brian: Running late", "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    starts = [e.payload.get("tool") for e in events if e.type == EventType.TOOL_START]
    assert starts == ["send_sms"]
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "SMS draft ready" in thinking
    assert sms.calls
    assert sms.calls[0]["to"] == "brian"


@pytest.mark.asyncio
async def test_a_complete_draft_raises_allow_before_any_model_round(
    monkeypatch,
) -> None:
    """The Allow card must not wait on the model.

    Tool-bearing rounds hold the answer back, so a spoken "text my wife …"
    showed an empty thread for as long as the 7B took to decide. Three live
    turns died there: the operator read blank as hung, pressed Esc to clear it,
    and the send was cancelled before its card existed.
    """
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    tools = ToolRegistry()
    sms = _SmsStub()
    tools.register(sms)
    asked: list[dict[str, Any]] = []

    async def confirm(confirm_id, tool, args, summary) -> str:
        asked.append({"tool": tool, "args": dict(args)})
        return "allow"

    # A single unused entry. A sent draft is confirmed deterministically, so a
    # healthy turn never reaches the router at all.
    router = _Router([[("token", "should never be asked")]])
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": True,
                "sms_force_call": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("Send a text to my wife telling her I love her", "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert [a["tool"] for a in asked] == ["send_sms"], "Allow must still be asked"
    assert asked[0]["args"]["to"] == "wife"
    assert "love" in asked[0]["args"]["body"].lower()
    assert sms.calls and sms.calls[0]["to"] == "wife"
    assert router.i == 0, "the model was asked before the Allow card"
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "pre-model" in thinking
    done = [e for e in events if e.type == EventType.ASSISTANT_DONE]
    assert done and "Sent your text" in str(done[-1].payload.get("text") or "")


@pytest.mark.asyncio
async def test_a_ready_send_says_why_send_sms_is_unavailable(monkeypatch) -> None:
    """Missing capability has two causes and they need different fixes."""
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    # send_sms is not registered at all — the Notify account is absent.
    tools = ToolRegistry()
    router = _Router([[("token", "I cannot text from here.")]])
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 2,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "intent_preflight": True,
                "sms_force_call": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("Send a text to my wife telling her I love her", "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    done = [e for e in events if e.type == EventType.ASSISTANT_DONE]
    assert done
    text = str(done[-1].payload.get("text") or "")
    assert "Settings → Notify" in text
    assert "scan the QR" in text
    assert router.i == 0


def test_greeting_does_not_revive_prior_sms_draft() -> None:
    from arelis.core.sms_complete import (
        complete_sms_draft,
        looks_like_greeting,
        looks_like_stale_sms_skip,
        sms_intent_this_turn,
    )

    assert looks_like_greeting("how are you today?")
    assert looks_like_stale_sms_skip("how are you today?")
    assert not sms_intent_this_turn("how are you today?")
    assert sms_intent_this_turn("Text wife: grocery run going?")
    assert sms_intent_this_turn(
        "chillin, chillin, i want you to text 5551112222 and tell him hey"
    )
    assert sms_intent_this_turn("text 555-111-2222 and tell him hey")
    history = [
        ChatMessage(role="user", content="Text wife: Hey, how's the grocery run going?"),
        ChatMessage(role="assistant", content="Okay — I did not send that."),
    ]
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    assert (
        complete_sms_draft("how are you today?", history=history, contacts=book)
        is None
    )


def test_sent_text_does_not_turn_the_next_ask_into_a_body() -> None:
    history = [
        ChatMessage(role="user", content="Text Brian that I am running late"),
        ChatMessage(role="assistant", content="Sent your text to Brian."),
    ]
    book = _book(brian={"name": "Brian Montgomery", "aliases": ["brian"]})
    assert (
        complete_sms_draft(
            "put dinner on my calendar Friday at 7",
            history=history,
            contacts=book,
        )
        is None
    )


def test_excellent_job_is_closing_chitchat() -> None:
    from arelis.core.sms_complete import looks_like_closing_chitchat

    assert looks_like_closing_chitchat("excellent job on the last two requests.")
    assert looks_like_closing_chitchat("Nope, that will be all")


def test_contacts_utterance_includes_my_contacts_and_her_phone() -> None:
    from arelis.core.sms_complete import looks_like_contacts_utterance

    assert looks_like_contacts_utterance("who is my wife in my contacts?")
    assert looks_like_contacts_utterance("what is her phone number?")
    assert not looks_like_contacts_utterance("what's the weather")


def test_send_a_text_and_have_it_say() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife", "robbie")})
    spoken = (
        "a conversation. Send a text to my wife and have it say "
        "Arelis test via conversation"
    )
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert "wife" in draft.to.lower()
    assert "have" not in draft.to.lower()
    assert "arelis test via conversation" in draft.body.lower()
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None and done.complete
    assert done.tool_to == "wife"


def test_senatics_message_is_send_a_text() -> None:
    """Sherpa heard 'send a text' as SENATIC'S and hid send_sms."""
    from arelis.core.sms_complete import sms_intent_this_turn
    from arelis.core.tool_subset import _without_unauthorized_sends

    book = _book(wife={"name": "Robin", "aliases": ("wife", "robbie")})
    spoken = "SENATIC'S MESSAGE TO MY WIFE TELLING HER I LOVE HER"
    assert sms_intent_this_turn(spoken)
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert "wife" in draft.to.lower()
    assert "love" in draft.body.lower()
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None and done.complete
    assert done.tool_to == "wife"
    kept = _without_unauthorized_sends({"send_sms", "calculator"}, spoken, set())
    assert "send_sms" in kept


def test_telling_her_is_sms_body() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    spoken = "I'm going to send a text message to my wife telling her I love her"
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert "wife" in draft.to.lower()
    assert draft.body.lower() == "i love you"
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None and done.complete
    assert done.body.lower() == "i love you"


def test_tell_her_i_love_her_is_i_love_you() -> None:
    """Third-person 'tell her I love her' is what the daughter should hear."""
    book = _book(baby={"name": "Piper Hale", "aliases": ("daughter", "baby", "piper")})
    spoken = "text my daughter and tell her i love her"
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert "daughter" in draft.to.lower()
    assert draft.body.lower() == "i love you"
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None and done.complete
    assert done.tool_to == "baby"
    assert done.body == "i love you"
    filled = fill_send_sms_args({"to": "baby", "body": "i love her"}, done, contacts=book)
    assert filled["body"] == "i love you"
    # Possessive: do not flip "her cooking" into "you cooking".
    cooking = parse_sms_utterance("text my daughter and tell her I love her cooking")
    assert cooking is not None
    assert cooking.body.lower() == "i love her cooking"
    saying = parse_sms_utterance("Send a text to my wife saying that I love her")
    assert saying is not None
    assert saying.body.lower() == "i love you"


def test_voice_preamble_text_wife_and_say() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife", "robbie")})
    spoken = (
        "I'm going to give you a new test. Text my wife and say, "
        "hey, grocery test, please ignore"
    )
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert "wife" in draft.to.lower()
    assert "say" not in draft.to.lower()
    assert "grocery test" in draft.body.lower()
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None and done.complete
    assert done.tool_to == "wife"


def test_yes_comma_please_confirms_sms_draft() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    history = [
        ChatMessage(
            role="user",
            content="Text my wife and say, hey, grocery test, please ignore",
        ),
        ChatMessage(
            role="assistant",
            content="Would you like me to proceed with sending this message?",
        ),
    ]
    done = complete_sms_draft("Yes, please", history=history, contacts=book)
    assert done is not None and done.complete
    assert done.tool_to == "wife"
    assert "grocery test" in done.body.lower()


def test_look_and_calendar_are_stale_sms_skips() -> None:
    from arelis.core.sms_complete import looks_like_stale_sms_skip

    assert looks_like_stale_sms_skip("Look at this image with vision")
    assert looks_like_stale_sms_skip("Summarize the file I just attached.")
    assert looks_like_stale_sms_skip("What's the git status of this repo?")
    assert looks_like_stale_sms_skip("Just describe it to me please")
    assert looks_like_stale_sms_skip("describe that")
    assert not looks_like_stale_sms_skip(
        "text my wife: Arelis allow-deny test - please ignore"
    )


def test_markdown_text_fence_apart_is_not_sms() -> None:
    """SymPy dumps use ```text\\napart: … — that is not send_sms(to=apart)."""
    from arelis.core.sms_complete import sms_intent_this_turn

    blob = (
        "I'm showing you\n"
        "```python\nimport sympy as sp\nprint(sp.apart(f))\n```\n\n"
        "```text\n"
        "apart: 1 + 8/(x - 2) + 16/(x - 2)**2\n"
        "```\n"
    )
    assert parse_sms_utterance(blob) is None
    assert not sms_intent_this_turn(blob)
    assert parse_sms_utterance("Text Brian: Running 10 minutes late") is not None


def test_add_text_overlay_on_a_picture_is_not_sms() -> None:
    """'add text right in the middle that says Arelis' used to inject send_sms."""
    from arelis.core.sms_complete import (
        looks_like_image_edit,
        looks_like_stale_sms_skip,
        sms_intent_this_turn,
    )

    spoken = (
        "I want you to now edit the picture you just created, and I want you "
        "to add text right in the middle that says Arelis, centered perfectly"
    )
    assert looks_like_image_edit(spoken)
    assert looks_like_stale_sms_skip(spoken)
    assert parse_sms_utterance(spoken) is None
    assert not sms_intent_this_turn(spoken)
    assert parse_sms_utterance("Text Brian: Running 10 minutes late") is not None
    assert parse_sms_utterance("add text message to my wife saying hello") is not None
