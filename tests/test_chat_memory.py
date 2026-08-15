"""Turn N+1 must still see turn N — conversation memory, not a prompt tweak."""

from __future__ import annotations

from typing import Any

import pytest

from arelis.contacts import Contact, web_search_targets_known_contact
from arelis.core.agent_loop import AgentLoop, _wants_project_context
from arelis.core.bus import EventBus
from arelis.core.context import DEFAULT_CHARS_PER_TOKEN
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry

TURN1_USER = (
    "if you could add any feature to yourself, literally anything at all, "
    "what would it be?"
)
TURN1_ASSISTANT = (
    "A real-time visualization interface for complex data and simulations."
)
TURN2_USER = "How would we go about approaching this?"


class _CaptureRouter:
    default_role = "fast"
    active_model = None
    models = {"fast": "mock"}

    def __init__(self) -> None:
        self.prompts: list[list[dict[str, Any]]] = []

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        del role, kwargs
        self.prompts.append(list(messages))
        yield ("token", "Let's sketch the visualization interface first.")


def _loop(memory: SessionMemory, *, speak: bool = True) -> tuple[AgentLoop, _CaptureRouter]:
    bus = EventBus()
    router = _CaptureRouter()
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        memory,
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 2,
                "skill_cards": False,
                "exactness": False,
                "numeric_gate": False,
                "evidence_gate": False,
                "chat_fast_path": True,
                "intent_preflight": False,
                "lessons": False,
                "history_max_messages": 24,
                "history_min_recent": 6,
                "tool_output_chars": 14000,
            },
            "ollama": {"num_ctx": 8192},
            "_speak_replies": speak,
        },
        request_confirm=lambda *_a, **_k: "allow",
        is_cancelled=lambda: False,
    )
    return loop, router


@pytest.mark.asyncio
async def test_conversation_followup_keeps_the_previous_turn() -> None:
    """Live failure: turn 2 asked what 'this' was and guessed interferometer."""
    memory = SessionMemory()
    memory.add("user", TURN1_USER)
    memory.add("assistant", TURN1_ASSISTANT)
    loop, _router = _loop(memory, speak=True)
    fat_system = [
        {"role": "system", "content": "You are Arelis. " + ("policy " * 400)},
        {"role": "system", "content": "Active project: interferometer. " * 20},
    ]
    # Budget already spent on the system prefix — old code kept only TURN2_USER.
    memory.add("user", TURN2_USER)
    messages = await loop._messages_for_turn(
        fat_system,
        budget=50,
        ratio=DEFAULT_CHARS_PER_TOKEN,
        role="fast",
        user_text=TURN2_USER,
    )
    blob = "\n".join(str(m.get("content") or "") for m in messages)
    assert TURN1_USER in blob
    assert "visualization interface" in blob
    assert TURN2_USER in blob
    # Working set still has turn 1 after the speak-mode drop path.
    assert any("visualization interface" in m.content for m in memory.messages)


@pytest.mark.asyncio
async def test_speak_drop_does_not_delete_the_tail_when_notices_sit_in_history() -> None:
    memory = SessionMemory()
    for i in range(8):
        memory.add("user", f"old user {i} " + ("x" * 80))
        memory.add("assistant", f"old reply {i} " + ("y" * 80))
    memory.add("notice", "Text from Robin Hale: emoji quoted outbound")
    memory.add("user", TURN1_USER)
    memory.add("assistant", TURN1_ASSISTANT)
    memory.add("user", TURN2_USER)
    loop, _router = _loop(memory, speak=True)
    await loop._messages_for_turn(
        [{"role": "system", "content": "You are Arelis."}],
        budget=80,
        ratio=DEFAULT_CHARS_PER_TOKEN,
        role="fast",
        user_text=TURN2_USER,
    )
    assert any(m.role == "notice" for m in memory.messages)
    assert any("visualization interface" in m.content for m in memory.messages)
    assert memory.messages[-1].content == TURN2_USER


def test_web_search_blocks_known_wife_contact() -> None:
    wife = Contact(
        alias="wife",
        name="Robin Hale",
        phone="5551112222",
        digits="5551112222",
        aliases=("robbie", "robin", "robin hale"),
    )
    book = {"wife": wife}
    assert web_search_targets_known_contact("Robin Hale", book) is wife
    assert web_search_targets_known_contact(
        "Robin Hale contact info", book
    ) is wife
    assert web_search_targets_known_contact("wife phone number", book) is wife
    assert (
        web_search_targets_known_contact(
            "visualization interface for simulations", book
        )
        is None
    )
    assert (
        web_search_targets_known_contact(
            "Robin Hale interferometer paper", book
        )
        is None
    )


def test_project_line_stays_off_chitchat_and_on_for_files() -> None:
    assert not _wants_project_context(
        role="fast", skill_ids=[], expected_tools=set()
    )
    assert _wants_project_context(
        role="code", skill_ids=[], expected_tools=set()
    )
    assert _wants_project_context(
        role="fast", skill_ids=["workspace"], expected_tools=set()
    )
    assert _wants_project_context(
        role="fast", skill_ids=[], expected_tools={"analyze"}
    )
