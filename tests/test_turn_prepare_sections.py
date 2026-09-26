from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import arelis.core.prompt_sections as sections
import arelis.core.turn_prepare as subject


def test_operating_and_delivery_sections_keep_the_volatile_tail_last(monkeypatch) -> None:
    class Store:
        pass

    monkeypatch.setattr(sections, "_wants_project_context", lambda **_: True)
    monkeypatch.setattr(sections, "standing_profile_prompt_line", lambda **_: "PROFILE")
    monkeypatch.setattr(sections, "contacts_prompt_line", lambda: "CONTACTS")
    monkeypatch.setattr(sections, "MemoryStore", Store)
    monkeypatch.setattr(sections, "episodes_prompt_line", lambda *_a, **_k: "EPISODES")
    monkeypatch.setattr(sections, "world_state_prompt_line", lambda *_a, **_k: "WORLD")
    monkeypatch.setattr(sections, "now_line", lambda: "NOW")

    import arelis.talk_language as talk_language

    monkeypatch.setattr(talk_language, "reply_instruction", lambda _lang: "LANGUAGE")
    room = SimpleNamespace(prompt_block=lambda: "ROOM")
    workspace = SimpleNamespace(prompt_line=lambda: "WORKSPACE")
    location = SimpleNamespace(prompt_line=lambda: "LOCATION")
    loop = SimpleNamespace(
        config={
            "_workspace": workspace,
            "_location": location,
            "_reply_language": "test",
        },
        _expected_tools=set(),
        _active_facts_line=lambda: "FACTS",
        memory=SimpleNamespace(sink=Store()),
    )
    messages = [
        {"role": "system", "content": "PERSONA"},
        {"role": "system", "content": "POLICY"},
    ]

    sections.append_operating_context(
        messages,
        loop,
        role="fast",
        model="model",
        skill_ids=[],
        active_room=room,
    )
    sections.append_delivery_context(messages, loop, speak=True)

    contents = [message["content"] for message in messages]
    assert contents[:2] == ["PERSONA", "POLICY"]
    assert contents[2:10] == [
        "WORKSPACE",
        "ROOM",
        "LOCATION",
        "PROFILE",
        "CONTACTS",
        "FACTS",
        "EPISODES",
        "WORLD",
    ]
    assert contents[-2:] == ["LANGUAGE", "NOW"]
    assert "conversation mode" in contents[-3]


@pytest.mark.asyncio
async def test_prepare_turn_wires_sections_expected_tools_budget_and_history(monkeypatch) -> None:
    start = subject._TurnStart(
        model="model",
        speak=False,
        agent_cfg={},
        ratio=4.0,
        research_mode=False,
        available_all={"weather"},
        active_room=None,
        available={"weather"},
        visible={"weather"},
    )
    loop = SimpleNamespace(
        persona="PERSONA",
        config={"ollama": {"num_ctx": 4096}},
        memory=SimpleNamespace(messages=[]),
        _expected_tools=set(),
        _timer=None,
        _active_plan=None,
        tool_output_chars=100,
    )
    captured: dict[str, object] = {}

    async def messages_for_turn(messages, budget, ratio, role, *, user_text):
        captured["history_args"] = (budget, ratio, role, user_text)
        return [*messages, {"role": "user", "content": user_text}]

    loop._messages_for_turn = messages_for_turn
    loop.tools = SimpleNamespace(
        ollama_tools=lambda visible: [{"name": sorted(visible)[0]}],
    )

    async def begin(*_args, **_kwargs):
        return start

    monkeypatch.setattr(subject, "_begin_turn", begin)
    monkeypatch.setattr(
        subject,
        "_reconstruct_turn_drafts",
        lambda *_: subject._TurnDrafts(None, None, None, False),
    )
    monkeypatch.setattr(
        subject,
        "static_system_prefix",
        lambda _persona: [
            {"role": "system", "content": "PERSONA"},
            {"role": "system", "content": "POLICY"},
        ],
    )
    monkeypatch.setattr(
        subject,
        "append_stopped_turn_note",
        lambda messages, _ask: messages.append({"role": "system", "content": "STOPPED"}),
    )

    def preflight(messages, loop, *_args, **_kwargs):
        loop._expected_tools.add("weather")
        messages.append({"role": "system", "content": "PREFLIGHT"})
        return ["weather"]

    monkeypatch.setattr(subject, "append_preflight_guidance", preflight)
    monkeypatch.setattr(subject, "select_skill_ids_detailed", lambda *_a, **_k: ([], False))
    monkeypatch.setattr(subject, "looks_like_closing_chitchat", lambda _text: False)
    monkeypatch.setattr(
        subject,
        "append_turn_goal",
        lambda messages, *_a, **_k: (
            messages.append({"role": "system", "content": "GOAL"})
            or SimpleNamespace(kind="weather")
        ),
    )

    def apply_expected(loop, available, **_kwargs):
        assert loop._expected_tools == {"weather"}
        return available, available

    monkeypatch.setattr(subject, "apply_expected", apply_expected)
    monkeypatch.setattr(subject, "choose_active_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(subject, "disconnected_integration_reply", lambda **_: None)
    monkeypatch.setattr(
        subject,
        "append_plan_and_lessons",
        lambda messages, *_a, **_k: messages.append({"role": "system", "content": "PLAN_LESSONS"}),
    )
    monkeypatch.setattr(
        subject,
        "append_operating_context",
        lambda messages, *_a, **_k: messages.append({"role": "system", "content": "OPERATING"}),
    )
    monkeypatch.setattr(
        subject,
        "append_delivery_context",
        lambda messages, *_a, **_k: messages.append({"role": "system", "content": "DELIVERY"}),
    )
    monkeypatch.setattr(
        subject,
        "detect_exactness_need",
        lambda _text: SimpleNamespace(
            needs_web_evidence=False,
            needs_weather=False,
        ),
    )
    monkeypatch.setattr(subject, "apply_research_web_need", lambda need, **_: need)
    monkeypatch.setattr(subject, "wants_fresh_page_ask", lambda _text: False)
    monkeypatch.setattr(subject, "should_offer_tools", lambda **_: True)
    monkeypatch.setattr(subject, "turn_expects_tool_round", lambda **_: True)

    def budget(num_ctx, **kwargs):
        captured["budget_args"] = (num_ctx, kwargs)
        return 1234

    monkeypatch.setattr(subject, "context_budget", budget)
    ctx = await subject.prepare_turn(loop, "hello", "fast", stopped_ask="old")

    assert ctx is not None
    assert [message["content"] for message in ctx.messages] == [
        "PERSONA",
        "POLICY",
        "STOPPED",
        "PREFLIGHT",
        "GOAL",
        "PLAN_LESSONS",
        "OPERATING",
        "DELIVERY",
        "hello",
    ]
    assert captured["history_args"] == (1234, 4.0, "fast", "hello")
    num_ctx, kwargs = captured["budget_args"]
    assert num_ctx == 4096
    assert kwargs["schema_chars"] == len(json.dumps([{"name": "weather"}]))
