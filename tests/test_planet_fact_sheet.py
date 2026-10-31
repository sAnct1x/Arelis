"""Planet and Mars-moon facts come from a pinned NASA table, not model memory.

Covers #122 (Phobos/Deimos) and #123 (largest planet / Jupiter vs Earth).
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
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
    ('which planet is the largest in our solar system?', "what's the biggest planet?"),
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
@pytest.mark.parametrize(
    "text",
    ('how many moons does Mars have?', 'how long does it take Phobos to go around Mars?'),
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


# --- solar tool body action ---


# --- review follow-ups: exact wording, wider triggers, skip list, negation ---


# Each of these would hit a trigger if the skip list or the negation check
# were gone, so they prove those guards still work.
_GUARDED_NEGATIVES = ('is Bruno Mars bigger than Earth Wind and Fire?', 'Mars bar diameter')


@pytest.mark.parametrize("text", _GUARDED_NEGATIVES)
def test_lookalike_names_and_negated_asks_get_no_block(text: str) -> None:
    from arelis.physics import fact_sheet as fs

    raw_hit = fs._PLANET_SIZE_ASK.search(text) or fs._MARS_MOONS_ASK.search(text)
    assert raw_hit, f"control {text!r} no longer exercises a guard"
    assert fs.reference_facts_message(text) is None


@pytest.mark.asyncio
async def test_solar_body_exact_directions_and_mass_line() -> None:
    from arelis.physics.runtime import set_system

    set_system(None)
    phobos = (await SolarTool().run(action="body", name="Phobos")).output
    deimos = (await SolarTool().run(action="body", name="Deimos")).output
    jupiter = (await SolarTool().run(action="body", name="Jupiter")).output
    assert "rises in the west and sets in the east about twice a day" in phobos.splitlines()
    assert "rises in the east and sets in the west, slowly" in deimos.splitlines()
    assert "inner moon of Mars; size about 26 x 23 x 18 km" in phobos.splitlines()
    assert "outer moon of Mars; size about 16 x 12 x 10 km" in deimos.splitlines()
    assert not any("inner moon" in line for line in deimos.splitlines())
    assert "317.8 times Earth's mass (NASA ratio)" in jupiter.splitlines()
    assert "mean radius 69911.0 km" in jupiter.splitlines()
