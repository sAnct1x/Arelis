"""Planet and Mars-moon facts come from a pinned NASA table, not model memory.

Covers #122 (Phobos/Deimos) and #123 (largest planet / Jupiter vs Earth).
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.prompt_sections import append_preflight_guidance
from arelis.tools.base import ToolRegistry
from arelis.tools.solar_tool import SolarTool
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter


class _CapturingRouter(_ScriptedRouter):
    """Records every messages list handed to the model."""

    def __init__(self) -> None:
        super().__init__([[("token", "ok")]])
        self.seen: list[list[dict[str, Any]]] = []

    async def stream(self, role, messages, **kwargs):
        self.seen.append([dict(m) for m in messages])
        async for item in super().stream(role, messages, **kwargs):
            yield item


def _fact_loop(router: _CapturingRouter, *, native: bool = False) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(SolarTool())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["intent_preflight"] = True
    if native:
        cfg["agent"]["native_tool_calling"] = True
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    return bus, loop


def _joined_system(messages: list[dict[str, Any]]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "system")


async def _messages_for(text: str, *, native: bool = False) -> str:
    router = _CapturingRouter()
    bus, loop = _fact_loop(router, native=native)
    await _collect(bus, loop.run(text, "fast"))
    assert router.seen, f"model never got messages for {text!r}"
    return _joined_system(router.seen[0])


def _mock_loop() -> Any:
    return type(
        "Loop",
        (),
        {
            "_expected_tools": set(),
            "_timer": None,
            "memory": type("M", (), {"messages": []})(),
        },
    )()


# --- table pins (NASA numbers from the brief, Oct 5 2026) ---


def test_fact_sheet_matches_nasa_planetary_table() -> None:
    from arelis.physics import fact_sheet as fs

    assert fs.EQUATORIAL_DIAMETER_KM["Mercury"] == 4879
    assert fs.EQUATORIAL_DIAMETER_KM["Venus"] == 12104
    assert fs.EQUATORIAL_DIAMETER_KM["Earth"] == 12756
    assert fs.EQUATORIAL_DIAMETER_KM["Moon"] == 3475
    assert fs.EQUATORIAL_DIAMETER_KM["Mars"] == 6792
    assert fs.EQUATORIAL_DIAMETER_KM["Jupiter"] == 142984
    assert fs.EQUATORIAL_DIAMETER_KM["Saturn"] == 120536
    assert fs.EQUATORIAL_DIAMETER_KM["Uranus"] == 51118
    assert fs.EQUATORIAL_DIAMETER_KM["Neptune"] == 49528

    assert fs.DIAMETER_RATIO_TO_EARTH["Mercury"] == 0.383
    assert fs.DIAMETER_RATIO_TO_EARTH["Venus"] == 0.949
    assert fs.DIAMETER_RATIO_TO_EARTH["Moon"] == 0.2724
    assert fs.DIAMETER_RATIO_TO_EARTH["Mars"] == 0.532
    assert fs.DIAMETER_RATIO_TO_EARTH["Jupiter"] == 11.21
    assert fs.DIAMETER_RATIO_TO_EARTH["Saturn"] == 9.45
    assert fs.DIAMETER_RATIO_TO_EARTH["Uranus"] == 4.01
    assert fs.DIAMETER_RATIO_TO_EARTH["Neptune"] == 3.88

    assert fs.MASS_RATIO_TO_EARTH["Jupiter"] == 317.8
    assert fs.MASS_RATIO_TO_EARTH["Saturn"] == 95.2
    assert fs.MASS_RATIO_TO_EARTH["Uranus"] == 14.5
    assert fs.MASS_RATIO_TO_EARTH["Neptune"] == 17.1
    assert fs.MASS_RATIO_TO_EARTH["Mars"] == 0.107
    assert fs.MASS_RATIO_TO_EARTH["Venus"] == 0.815
    assert fs.MASS_RATIO_TO_EARTH["Mercury"] == 0.0553

    assert fs.JUPITER_VOLUME_RATIO_TO_EARTH == 1321.33
    assert fs.LARGEST_PLANET == "Jupiter"
    assert fs.MARS_MOON_COUNT == 2
    assert fs.MARS_DAY_HOURS == 24.6597

    assert fs.PHOBOS["mean_distance_km"] == 9378
    assert fs.PHOBOS["orbit_period_days"] == 0.31891
    assert fs.PHOBOS["axis_radii_km"] == (13.0, 11.4, 9.1)
    assert fs.DEIMOS["mean_distance_km"] == 23459
    assert fs.DEIMOS["orbit_period_days"] == 1.26244
    assert fs.DEIMOS["axis_radii_km"] == (7.8, 6.0, 5.1)


# --- messages handed to the model ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    (
        "which planet is the largest in our solar system?",
        "what's the biggest planet?",
        "how big is Jupiter compared to Earth?",
    ),
)
async def test_planet_size_ask_gets_jupiter_width_facts(text: str) -> None:
    blob = await _messages_for(text)
    low = blob.lower()
    assert "reference facts from nasa" in low
    assert "largest planet: jupiter" in low
    assert "about 11 times wider than earth" in low
    assert "142,984 km" in blob
    assert "twice" not in low


@pytest.mark.asyncio
async def test_other_planet_size_ask_gets_that_planets_numbers() -> None:
    blob = await _messages_for("how big is Saturn compared to Earth?")
    assert "Saturn equatorial diameter 120,536 km, 9.45 times Earth's diameter." in blob
    assert "Earth equatorial diameter 12,756 km." in blob


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    (
        "how many moons does Mars have?",
        "how long does it take Phobos to go around Mars?",
        "tell me about the moons of Mars",
        "which way does Phobos cross the sky?",
    ),
)
async def test_mars_moon_ask_gets_phobos_deimos_facts(text: str) -> None:
    blob = await _messages_for(text)
    low = blob.lower()
    assert "reference facts from nasa" in low
    assert "phobos (inner" in low
    assert "deimos (outer" in low
    phobos = next(line for line in low.splitlines() if line.startswith("phobos"))
    deimos = next(line for line in low.splitlines() if line.startswith("deimos"))
    assert "about 7 hours 39 minutes" in phobos
    assert "rises in the west and sets in the east about twice a day" in phobos
    assert "about 30 hours 18 minutes" in deimos
    assert "longer than a mars day" in deimos
    assert "rises in the east and sets in the west" in deimos
    assert "a mars day is about 24 hours 40 minutes" in low


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    (
        "which planet is the largest in our solar system?",
        "tell me about the moons of Mars",
    ),
)
async def test_fact_block_also_lands_with_native_tool_calling(text: str) -> None:
    blob = await _messages_for(text, native=True)
    assert "Reference facts from NASA" in blob


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    (
        "I'm going to a Bruno Mars concert",
        "a Mars bar",
        "the Mars rover landed",
        "what's the weather on Saturn street",
        "my phone's moon icon",
    ),
)
async def test_unrelated_prompts_get_no_planet_fact_block(text: str) -> None:
    blob = await _messages_for(text)
    assert "Reference facts from NASA" not in blob


def test_append_preflight_puts_facts_before_native_early_return() -> None:
    """Native mode skips intent nudges but still gets the NASA fact block."""
    messages: list[dict[str, str]] = []
    kinds = append_preflight_guidance(
        messages,
        _mock_loop(),
        "which planet is the largest in our solar system?",
        {"native_tool_calling": True},
        see_no_sms_redirect=frozenset(),
    )
    assert kinds == []
    blob = "\n".join(m["content"] for m in messages)
    assert "Reference facts from NASA" in blob
    assert "11" in blob


# --- solar tool body action ---


@pytest.mark.asyncio
async def test_solar_body_phobos_includes_orbit_and_rise_set() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    result = await SolarTool().run(action="body", name="Phobos")
    assert result.ok, result.output
    low = result.output.lower()
    assert "7 hours 39" in low or "7 h 39" in low
    assert "9378" in result.output or "9,378" in result.output
    assert "west" in low and "east" in low
    assert "twice" in low


@pytest.mark.asyncio
async def test_solar_body_deimos_includes_orbit_and_rise_set() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    result = await SolarTool().run(action="body", name="Deimos")
    assert result.ok, result.output
    low = result.output.lower()
    assert "30 hours 18" in low or "30 h 18" in low
    assert "23459" in result.output or "23,459" in result.output
    assert "east" in low and "west" in low
    assert "longer" in low


@pytest.mark.asyncio
async def test_solar_body_jupiter_includes_diameter_and_earth_width() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    result = await SolarTool().run(action="body", name="Jupiter")
    assert result.ok, result.output
    low = result.output.lower()
    assert "142,984 km" in result.output
    assert "11.21 times earth's diameter" in low
