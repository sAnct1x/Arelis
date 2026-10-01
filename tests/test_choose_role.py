"""Routing classification telemetry (Wave 0 / Wave 2)."""

from __future__ import annotations

from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.tools.base import ToolRegistry


class _StubRouter:
    default_role = "fast"
    active_model = "stub"


def _orch() -> Orchestrator:
    return Orchestrator(
        EventBus(),
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {"workspace": {"roots": ["."]}, "_persona_path": "persona.md"},
        SessionMemory(),
    )


def test_chip_research_wins() -> None:
    role, reason = _orch().classify_role("hello", "research")
    assert role == "research"
    assert reason == "chip"


def test_file_loop_stays_fast() -> None:
    role, reason = _orch().classify_role("please edit the python file and lint it")
    assert role == "fast"
    assert reason == "file_loop"


def test_tool_loop_routes_fast() -> None:
    role, reason = _orch().classify_role("search the web for lithium prices")
    assert role == "fast"
    assert reason == "tool_loop"


def test_research_hint() -> None:
    role, reason = _orch().classify_role(
        "Investigate recent battery recycling and write a report"
    )
    assert role == "research"
    assert reason == "research_hint"


def test_deeply_research_is_a_research_hint() -> None:
    role, reason = _orch().classify_role(
        "i want you to deeply research the best piezoelectric material"
    )
    assert role == "research"
    assert reason == "research_hint"


def test_short_factual_stays_on_fast() -> None:
    """H2: bare 'research' / look-up stays 7b+tools, not silent 14b."""
    role, reason = _orch().classify_role("research cyclospora outbreaks briefly")
    assert role == "fast"
    assert reason == "tool_loop"


def test_fast_chip_does_not_pin_deep_language() -> None:
    """The composer defaults to fast. That is not a pin — 'deeply research'
    still routes. Bare look-ups stay on fast (H2)."""
    role, reason = _orch().classify_role(
        "Investigate and write a report on fusion", "fast"
    )
    assert role == "research"
    assert reason == "research_hint"
    role, reason = _orch().classify_role(
        "i want you to deeply research the best piezoelectric material",
        "fast",
    )
    assert role == "research"
    assert reason == "research_hint"


def test_default_role() -> None:
    role, reason = _orch().classify_role("hey how are you")
    assert role == "fast"
    assert reason == "default"


def test_derive_stays_on_fast() -> None:
    """A homework derivation is not a 32-round research loop."""
    role, reason = _orch().classify_role(
        "derive the equation for F=ma. show me how it was derived to begin with."
    )
    assert role == "fast"
    assert reason != "research_hint"


def test_sourced_pdf_on_the_fast_chip_is_research() -> None:
    """Search, open the sources, write the file. The default chip is not a pin."""
    text = (
        "Research what the lab measured. "
        "Write the result as a PDF I can open. Put the report in the file. "
        "Search the web, then open the papers."
    )
    role, reason = _orch().classify_role(text, "fast")
    assert role == "research"
    assert reason == "research_hint"


def test_pdf_without_a_search_stays_on_the_fast_chip() -> None:
    role, reason = _orch().classify_role("Write the result as a PDF I can open.", "fast")
    assert role == "fast"
    assert reason == "chip"


def test_weather_is_tool_loop() -> None:
    role, reason = _orch().classify_role("what's the weather today")
    assert role == "fast"
    assert reason == "tool_loop"


def test_switch_roles_sentence_is_the_chip() -> None:
    from arelis.core.orchestrator_shared import match_role_switch

    spoken = "switch roles to research, then I got a good prompt for you to look into"
    assert match_role_switch(spoken) == (
        "research",
        "I got a good prompt for you to look into",
    )
    assert match_role_switch("switch to research") == ("research", "")
    assert match_role_switch("set the role to fast") == ("fast", "")
    assert match_role_switch("switch to research the muon papers") is None
    assert match_role_switch("make it a research room") is None


async def test_switch_roles_sentence_sets_the_chip() -> None:
    from arelis.core.events import Event, EventType

    router = _StubRouter()

    def same_chat_weights(_a: str, _b: str) -> bool:
        return True

    router.same_chat_weights = same_chat_weights  # type: ignore[attr-defined]
    orch = Orchestrator(
        EventBus(),
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        {"workspace": {"roots": ["."]}, "_persona_path": "persona.md"},
        SessionMemory(),
    )
    await orch.on_user_message(
        Event(
            EventType.USER_MESSAGE,
            {
                "text": (
                    "switch roles to research, then I got a good prompt "
                    "for you to look into"
                )
            },
        )
    )
    queued = []
    while not orch.bus._queue.empty():
        queued.append(orch.bus._queue.get_nowait())
    assert orch.router.default_role == "research"
    assert any(
        event.type == EventType.ASSISTANT_DONE
        and "Role set to `research`" in str(event.payload.get("text") or "")
        for event in queued
    )
    assert orch._turn_task is None


def test_comms_bypasses_coder_sticky() -> None:
    from arelis.core.orchestrator import comms_bypasses_sticky

    assert comms_bypasses_sticky("text my wife that I'll be late")
    assert comms_bypasses_sticky(
        "send an email to bob@example.com about dinner: see you at 7"
    )
    assert not comms_bypasses_sticky("how are you tonight")
    assert not comms_bypasses_sticky("please edit the python file and lint it")
