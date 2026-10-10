"""A muted outbound host is a failed tool call, not a dead turn.

The house watch raises EgressMutedError from the httpx hook once a host has
been asked too often. Catalog and solar used to let that exception leave the
tool, and the turn died with the mid-turn error.
"""

from __future__ import annotations

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.guard.watch import _is_house_host, attach_watch, get_watch, reset_watch
from arelis.tools.base import ToolRegistry
from arelis.tools.catalog import CatalogTool
from arelis.tools.solar_tool import SolarTool
from tests.hardening_helpers import _collect, _config, _ScriptedRouter

PAUSED = (
    "That site has been paused for now because Arelis asked it too many times, "
    "so try again later."
)
_EM = "\u2014"
_EN = "\u2013"


def _install_mute(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Force the live httpx hook to raise EgressMutedError. Do not retry."""
    import httpx

    reset_watch()
    watch = get_watch()
    if not getattr(httpx.AsyncClient, "_arelis_watch", False) or not getattr(
        httpx.Client, "_arelis_watch", False
    ):
        watch._httpx_installed = False
    attach_watch(EventBus(), {"agent": {"watch": {"enabled": True}}})
    hits = {"n": 0}

    def allow(host: str) -> bool:
        if _is_house_host(host):
            return True
        hits["n"] += 1
        return False

    monkeypatch.setattr(watch, "allow_egress", allow)
    return hits


def _assert_plain(text: str) -> None:
    assert text == PAUSED
    assert _EM not in text
    assert _EN not in text
    lowered = text.lower()
    assert "egress" not in lowered
    assert "jpl" not in lowered
    assert "http" not in lowered
    assert ".py" not in lowered
    assert "config" not in lowered


@pytest.fixture
def muted_outbound(monkeypatch: pytest.MonkeyPatch):
    hits = _install_mute(monkeypatch)
    try:
        yield hits
    finally:
        reset_watch()


@pytest.mark.asyncio
async def test_catalog_lookup_returns_a_pause_when_the_guard_mutes(
    muted_outbound: dict[str, int],
) -> None:
    result = await CatalogTool().run(
        action="horizons", target="Mars", date="2026-10-01"
    )
    assert result.ok is False
    _assert_plain(result.output)
    assert muted_outbound["n"] == 1


@pytest.mark.asyncio
async def test_solar_load_returns_a_pause_when_the_guard_mutes(
    muted_outbound: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.physics.runtime import set_system

    monkeypatch.setattr("arelis.tools.solar_tool.world_stage_allowed", lambda: True)
    monkeypatch.setattr("arelis.tools.solar_tool.rebound_available", lambda: True)
    set_system(None)
    try:
        result = await SolarTool().run(
            action="load", date="2026-10-01", tracers=0, refresh=True
        )
    finally:
        set_system(None)
    assert result.ok is False
    _assert_plain(result.output)
    assert muted_outbound["n"] == 1


@pytest.mark.asyncio
async def test_muted_catalog_still_finishes_the_turn(
    muted_outbound: dict[str, int],
) -> None:
    """The orchestrator used to publish the mid-turn error and stop."""
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(CatalogTool())
    call = {
        "type": "function",
        "function": {
            "name": "catalog",
            "arguments": {
                "action": "horizons",
                "target": "Mars",
                "date": "2026-10-01",
            },
        },
    }
    router = _ScriptedRouter(
        [
            [("tool_calls", [call])],
            [("token", PAUSED)],
        ]
    )
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 4
    cfg["agent"]["confirm_timeout_s"] = 1
    Orchestrator(bus, router, tools, cfg, SessionMemory())  # type: ignore[arg-type]
    events = await _collect(
        bus,
        bus.publish(
            Event(
                EventType.USER_MESSAGE,
                {"text": "ask horizons where Mars is"},
            )
        ),
    )
    errors = [
        str((event.payload or {}).get("message") or "")
        for event in events
        if event.type == EventType.ERROR
    ]
    assert not any("went wrong mid-turn" in message for message in errors)
    done = [event for event in events if event.type == EventType.ASSISTANT_DONE]
    assert done, "the turn should finish with a reply"
    reply = str(done[-1].payload.get("text") or "")
    assert "went wrong mid-turn" not in reply
    assert reply.strip()
    results = [
        event
        for event in events
        if event.type == EventType.TOOL_RESULT
        and (event.payload or {}).get("tool") == "catalog"
    ]
    assert results
    assert results[0].payload.get("ok") is False
    assert PAUSED in str(results[0].payload.get("output") or "")
    assert muted_outbound["n"] >= 1


def test_map_download_stops_when_the_guard_mutes(
    muted_outbound: dict[str, int], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.physics import maps as maps_mod

    monkeypatch.setattr(maps_mod, "maps_dir", lambda: tmp_path)
    maps_mod.forget_ready()
    before = muted_outbound["n"]
    saved, errors = maps_mod.download_maps()
    assert PAUSED in errors
    assert muted_outbound["n"] == before + 1
    assert "Earth" not in saved


@pytest.mark.asyncio
async def test_agenda_ics_returns_a_pause_when_the_guard_mutes(
    muted_outbound: dict[str, int], tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.tools.agenda import AgendaTool

    monkeypatch.setattr(
        "arelis.briefing.ics_sync.load_ics_url",
        lambda path=None: "https://ssd.jpl.nasa.gov/calendar.ics",
    )
    tool = AgendaTool({"tools": {"briefing": {"calendar_path": str(tmp_path / "cal.ics")}}})
    before = muted_outbound["n"]
    result = await tool.run(action="sync", provider="ics")
    assert result.ok is False
    _assert_plain(result.output)
    assert muted_outbound["n"] == before + 1
