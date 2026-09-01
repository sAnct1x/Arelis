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


def test_weather_is_tool_loop() -> None:
    role, reason = _orch().classify_role("what's the weather today")
    assert role == "fast"
    assert reason == "tool_loop"


def test_comms_bypasses_coder_sticky() -> None:
    from arelis.core.orchestrator import comms_bypasses_sticky

    assert comms_bypasses_sticky("text my wife that I'll be late")
    assert comms_bypasses_sticky(
        "send an email to bob@example.com about dinner: see you at 7"
    )
    assert not comms_bypasses_sticky("how are you tonight")
    assert not comms_bypasses_sticky("please edit the python file and lint it")
