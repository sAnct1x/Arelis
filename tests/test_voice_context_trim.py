"""Follow-up turns must not re-prefill stable session context.

Profile, contacts, facts, location, the spoken policy, and the theme change
rarely. They used to sit after history, so every voice (and typed) follow-up
reprocessed hundreds of tokens of the same text. They now pin ahead of
history. Only this-turn lines (lessons, world state, the clock) trail it.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import arelis.core.agent_loop as agent_loop_mod
import arelis.core.prompt_sections as sections
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.context import message_tokens
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import prepare_turn
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.ui import theme_tokens


class _Clock(datetime):
    when = datetime(2026, 11, 10, 15, 37)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.when
        return cls.when.replace(tzinfo=tz)


class _Router:
    active_model = "probe-model"

    def model_for(self, role=None):
        del role
        return self.active_model


class _Tool:
    description = "probe"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, **kwargs):
        del kwargs
        return ToolResult(ok=True, output="ok")


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("weather", "web_search", "calculator"):
        registry.register(_Tool(name))  # type: ignore[arg-type]
    return registry


def _flatten(messages: list[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        parts.append(f"{message.get('role')}\n{content}\n")
    return "".join(parts)


def _tokens(messages: list[dict]) -> int:
    return sum(message_tokens(message) for message in messages)


def _after_last_assistant(messages: list[dict]) -> list[dict]:
    last = None
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            last = index
    if last is None:
        return list(messages)
    return list(messages[last + 1 :])


@pytest.mark.asyncio
async def test_follow_up_turn_reprocesses_only_the_volatile_tail(monkeypatch) -> None:
    """A second spoken turn keeps the session prefix and stays under 300 tokens."""
    monkeypatch.setattr(agent_loop_mod, "datetime", _Clock)
    profile = {
        "text": (
            "Standing profile (hand-edited in data/profile.yaml; treat as durable, "
            "not guesses. Location/timezone may also appear on a separate line.):\n"
            "- Name: Alex Rivers\n"
            "- Work: Independent researcher, local AI and astronomy\n"
            "- Units: imperial, SI when a paper uses it\n"
            "- Answer style: direct, short when speaking"
        )
    }
    monkeypatch.setattr(
        sections,
        "standing_profile_prompt_line",
        lambda **_: profile["text"],
    )
    monkeypatch.setattr(
        sections,
        "contacts_prompt_line",
        lambda *_, **__: (
            "Contacts, known people: sam (Sam); jordan (Jordan). "
            "These aliases may be passed to tools when the user names them."
        ),
    )
    class Store:
        def on_message(self, role, content, note=""):
            del role, content, note

        def on_summary(self, text):
            del text

        def on_pending_fact(self, text):
            del text

    monkeypatch.setattr(sections, "MemoryStore", Store)
    monkeypatch.setattr(
        sections,
        "episodes_prompt_line",
        lambda *_a, **_k: (
            "Recent episodes (explicit summaries the user stored; not a full history):\n"
            "- Set up the Arelis dev checkout and llama-server on port 8080.\n"
            "- Asked for a catalog look at Saturn and later a parsec conversion."
        ),
    )

    location = SimpleNamespace(
        prompt_line=lambda: (
            "The user is in Columbus, Ohio, United States in timezone America/New_York. "
            "Use that for anything place-sensitive, such as weather or local time, "
            "instead of asking, unless the user names somewhere else."
        )
    )
    facts = (
        "Things you know about the user (approved facts; treat as durable, "
        "not guesses, and not a substitute for asking when unsure):\n"
        "- Prefers short spoken answers.\n"
        "- Lives in Columbus, Ohio.\n"
        "- Works on local AI and astronomy projects."
    )
    config = {
        "agent": {
            "chat_fast_path": False,
            "lessons": True,
            "max_rounds": 4,
            "json_fallback": False,
        },
        "llamacpp": {"default_cap": 32768},
        "_speak_replies": True,
        "_location": location,
        "_persona_path": "does-not-exist.md",
    }
    loop = AgentLoop(
        EventBus(),
        _Router(),  # type: ignore[arg-type]
        _registry(),
        SessionMemory(),
        "PERSONA",
        config,
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )
    loop.memory.sink = sections.MemoryStore()
    monkeypatch.setattr(loop, "_active_facts_line", lambda: facts)

    first = await prepare_turn(loop, "What's the capital of France?", "fast")
    assert first is not None
    loop.memory.add("assistant", "Paris.")
    second = await prepare_turn(loop, "Tell me a very short story.", "fast")
    assert second is not None

    first_flat = _flatten(first.messages)
    second_flat = _flatten(second.messages)
    # The second prompt extends the first through the cached assistant reply.
    assert second_flat.startswith(first_flat + "assistant\nParis.\n")

    stable = (
        "Standing profile",
        "Contacts, known people",
        "Things you know about the user",
        "Recent episodes",
        "The user is in Columbus",
        "You are speaking aloud",
        "The screen theme right now",
    )
    # Pinned ahead of the first user line, on both turns.
    for messages in (first.messages, second.messages):
        user_at = next(
            i for i, message in enumerate(messages) if message.get("role") == "user"
        )
        prefix = _flatten(messages[:user_at])
        for marker in stable:
            assert marker in prefix

    # The newly prefilled suffix is the previous answer plus this turn's
    # volatile tail and the new ask. The stable lines must not be in that
    # newly prefilled tail (they already sat in the cached prefix).
    new_suffix = _after_last_assistant(second.messages)
    suffix_text = _flatten(new_suffix)
    for marker in stable:
        assert marker not in suffix_text
    assert "Right now it is" in suffix_text
    assert "World state:" in suffix_text
    assert "Lessons from past failures" in suffix_text
    assert "Tell me a very short story." in suffix_text

    # The bound that matters: the new tail plus the new ask, not the
    # already-generated assistant row.
    last_user = next(
        i
        for i in range(len(second.messages) - 1, -1, -1)
        if second.messages[i].get("role") == "user"
    )
    last_asst = next(
        i
        for i in range(last_user - 1, -1, -1)
        if second.messages[i].get("role") == "assistant"
    )
    volatile = second.messages[last_asst + 1 : last_user + 1]
    volatile_tokens = _tokens(volatile)
    assert volatile_tokens < 300, volatile_tokens

    # The pinned prefix itself must be byte-identical while those facts stay put.
    first_user = next(
        i for i, message in enumerate(first.messages) if message.get("role") == "user"
    )
    second_first_user = next(
        i for i, message in enumerate(second.messages) if message.get("role") == "user"
    )
    assert first.messages[:first_user] == second.messages[:second_first_user]

    # A mid-session profile edit or theme switch must land in this turn's
    # prefix, and must not leave the old lines in history or the tail.
    old_theme = theme_tokens.active_theme()
    new_theme = "filament" if old_theme != "filament" else "sodium"
    monkeypatch.setattr(theme_tokens, "_ACTIVE_THEME", new_theme)
    profile["text"] = profile["text"].replace("Alex Rivers", "Blake Stone")
    loop.memory.add("assistant", "Once there was a fox.")
    third = await prepare_turn(loop, "What theme is this?", "fast")
    assert third is not None

    third_user = next(
        i for i, message in enumerate(third.messages) if message.get("role") == "user"
    )
    third_prefix = _flatten(third.messages[:third_user])
    assert "Blake Stone" in third_prefix
    assert "Alex Rivers" not in third_prefix
    assert f"The screen theme right now is {theme_tokens.theme_spoken_name()}." in third_prefix
    assert f"The screen theme right now is {theme_tokens.theme_spoken_name(old_theme)}." not in _flatten(third.messages)
    # History and the new ask are still on this turn.
    third_flat = _flatten(third.messages)
    assert "What's the capital of France?" in third_flat
    assert "Paris." in third_flat
    assert "Tell me a very short story." in third_flat
    assert "Once there was a fox." in third_flat
    assert "What theme is this?" in third_flat
    new_suffix = _after_last_assistant(third.messages)
    suffix_text = _flatten(new_suffix)
    for marker in ("Standing profile", "The screen theme right now"):
        assert marker not in suffix_text
