"""Location off must not share country, time zone, or any other place."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from arelis.core.prompt_sections import append_delivery_context
from arelis.location import build_location
from arelis.tools.user_location import UserLocationTool


def _zone_and_offset() -> tuple[str, str]:
    here = datetime.now().astimezone()
    return here.strftime("%Z") or "local time", here.strftime("%z")


def _clock_line(messages: list[dict[str, str]]) -> str:
    clocks = [
        str(item.get("content") or "")
        for item in messages
        if str(item.get("content") or "").startswith("Right now it is")
    ]
    assert clocks, "clock line missing from the prompt"
    return clocks[-1]


def _delivery_messages(*, location_enabled: bool) -> list[dict[str, str]]:
    loop = SimpleNamespace(config={"location": {"enabled": location_enabled}})
    messages: list[dict[str, str]] = []
    append_delivery_context(messages, loop, speak=False)
    return messages


def _prepare_messages(monkeypatch, *, location_enabled: bool) -> list[dict[str, str]]:
    from arelis.core import turn_prepare as subject

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
    captured: dict[str, object] = {}
    loop = SimpleNamespace(
        persona="PERSONA",
        config={
            "llamacpp": {"default_cap": 4096},
            "location": {"enabled": location_enabled},
        },
        memory=SimpleNamespace(messages=[]),
        _expected_tools=set(),
        _timer=None,
        _active_plan=None,
        tool_output_chars=100,
        tools=SimpleNamespace(
            chat_tools=lambda names=None, *, param_hints=False: [{"name": "weather"}],
        ),
    )
    async def messages_for_turn(messages, budget, ratio, role, *, user_text, turn_tail=None):
        del budget, ratio, role, turn_tail
        tail = list(captured.get("block") or [])
        return [*messages, *tail, {"role": "user", "content": user_text}]

    loop.memory.remember_turn_block = lambda block: captured.update(block=list(block))
    loop._messages_for_turn = messages_for_turn

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
        lambda _persona: [{"role": "system", "content": "PERSONA"}],
    )
    monkeypatch.setattr(subject, "append_stopped_turn_note", lambda *_a, **_k: None)
    monkeypatch.setattr(subject, "append_preflight_guidance", lambda *_a, **_k: [])
    monkeypatch.setattr(subject, "select_skill_ids_detailed", lambda *_a, **_k: ([], False))
    monkeypatch.setattr(subject, "looks_like_closing_chitchat", lambda _text: False)
    monkeypatch.setattr(
        subject,
        "append_turn_goal",
        lambda *_a, **_k: SimpleNamespace(kind="none"),
    )
    monkeypatch.setattr(
        subject,
        "apply_expected",
        lambda _loop, available, **_k: (available, available),
    )
    monkeypatch.setattr(subject, "disconnected_integration_reply", lambda **_: None)
    monkeypatch.setattr(subject, "append_plan_and_lessons", lambda *_a, **_k: None)
    monkeypatch.setattr(subject, "append_operating_context", lambda *_a, **_k: None)
    monkeypatch.setattr(subject, "detect_exactness_need", lambda *_a, **_k: SimpleNamespace(
        needs_web_evidence=False,
        needs_weather=False,
    ))
    monkeypatch.setattr(subject, "apply_research_web_need", lambda need, **_: need)
    monkeypatch.setattr(subject, "wants_fresh_page_ask", lambda _text: False)
    monkeypatch.setattr(subject, "should_offer_tools", lambda **_: False)
    monkeypatch.setattr(subject, "turn_expects_tool_round", lambda **_: False)
    monkeypatch.setattr(subject, "context_budget", lambda *_a, **_k: 1234)
    ctx = asyncio.run(subject.prepare_turn(loop, "what time zone am I in?", "fast"))
    assert ctx is not None
    return list(ctx.messages)


def _assert_clock_hides_zone(clock: str) -> None:
    zone, offset = _zone_and_offset()
    low = clock.lower()
    assert "(" not in clock
    assert ")" not in clock
    assert zone.lower() not in low
    if offset:
        assert offset not in clock
        assert offset.replace("+", "") not in clock
    assert "local time" not in low
    assert "utc" not in low
    assert "gmt" not in low
    assert "edt" not in low
    assert "est" not in low


def _assert_clock_names_zone(clock: str) -> None:
    zone, _offset = _zone_and_offset()
    assert f"({zone})" in clock


def test_location_off_shares_no_country_or_timezone(tmp_path: Path, monkeypatch) -> None:
    """location.enabled false shares no place, and the clock names no zone.

    The tool leak was SystemProvider still filling country and time zone
    after location was turned off. The clock leak was now_line putting
    strftime %Z in the system prompt. This goes through append_delivery_context
    and prepare_turn, so a bare now_line() call fails.
    """
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "location:\n"
        "  city: Springfield\n"
        "  region: Illinois\n"
        "  country: US\n"
        "  timezone: America/Chicago\n",
        encoding="utf-8",
    )
    resolver = build_location(
        {
            "location": {
                "enabled": False,
                "profile_path": str(profile),
                "network": {"enabled": False},
            }
        }
    )
    result = asyncio.run(UserLocationTool(resolver).run())
    assert result.ok
    low = result.output.lower()
    assert "location is off" in low
    assert "springfield" not in low
    assert "chicago" not in low
    assert "country:" not in low
    assert "timezone:" not in low
    assert "utc_offset:" not in low
    assert not result.data.get("country")
    assert not result.data.get("timezone")
    assert not result.data.get("utc_offset")
    assert not result.data.get("city")

    off_delivery = _clock_line(_delivery_messages(location_enabled=False))
    on_delivery = _clock_line(_delivery_messages(location_enabled=True))
    _assert_clock_hides_zone(off_delivery)
    _assert_clock_names_zone(on_delivery)

    off_prepare = _clock_line(_prepare_messages(monkeypatch, location_enabled=False))
    on_prepare = _clock_line(_prepare_messages(monkeypatch, location_enabled=True))
    _assert_clock_hides_zone(off_prepare)
    _assert_clock_names_zone(on_prepare)
