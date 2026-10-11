"""Lines a person can see about running from source stay plain."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from arelis import update
from arelis.companion_pack import (
    ExpectedCompanion,
    landing_html,
)
from arelis.companion_pack import status as companion_status
from arelis.core.desk_guide import DESK_GUIDE
from arelis.login_start import install_login_start, remove_login_start
from arelis.main import _INSTALL_LOGIN_HELP, _PURGE_HELP, _REMOVE_LOGIN_HELP
from arelis.physics.engine import NBody
from arelis.tools.earth_tool import EarthTool
from arelis.tools.solar_tool import SolarTool
from arelis.tools.transcribe import _VIDEO_REFUSED
from arelis.ui.spatial_hands import _HANDS_MISSING
from arelis.ui.window_chrome import _FILAMENT_DETAIL
from arelis.ui.world_host import _PLATE_ONLY


def _assert_plain(label: str, text: str) -> None:
    lowered = text.lower()
    assert "source checkout" not in lowered, f"{label}: {text}"
    assert "git pull" not in lowered, f"{label}: {text}"
    assert "-" not in text, f"{label}: {text}"
    assert "\u2013" not in text and "\u2014" not in text, f"{label}: {text}"
    assert "\\" not in text and "/" not in text, f"{label}: {text}"
    assert ".py" not in text and "pip install" not in lowered, f"{label}: {text}"


def test_source_lines_have_no_dashes_or_checkout_jargon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("arelis.tools.solar_tool.world_stage_allowed", lambda: False)
    solar = SolarTool()
    maps, blocked, load_blocked = asyncio.run(
        _solar_blocked(solar)
    )
    monkeypatch.setattr("arelis.tools.solar_tool.world_stage_allowed", lambda: True)
    monkeypatch.setattr("arelis.tools.solar_tool.rebound_available", lambda: False)
    rebound = asyncio.run(solar.run(action="load"))

    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: False)
    earth = EarthTool()
    earth_status, earth_enter = asyncio.run(_earth_blocked(earth))

    monkeypatch.setattr("arelis.physics.engine.rebound_available", lambda: False)
    with pytest.raises(RuntimeError) as caught:
        NBody.from_particles([])

    monkeypatch.setattr("arelis.ui.idle_host.note_engagement", lambda _window: None)
    monkeypatch.setattr("arelis.ui.world_host.world_available", lambda: False)
    from arelis.ui.world_host import toggle_world

    class _Think:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def append(self, text: str, kind: str | None = None) -> None:
            self.lines.append(text)

    class _Act:
        def setChecked(self, _value: bool) -> None:
            return None

    class _Win:
        def __init__(self) -> None:
            self.thinking = _Think()
            self.act_world = _Act()

    window = _Win()
    toggle_world(window, True)
    assert window.thinking.lines == [_PLATE_ONLY]

    monkeypatch.setattr("arelis.companion_pack.find_apk", lambda: None)
    monkeypatch.setattr("arelis.companion_pack.find_gemma", lambda: None)
    monkeypatch.setattr(
        "arelis.companion_pack.expected_companion",
        lambda gradle=None: ExpectedCompanion(6, "0.3.3", "gradle"),
    )
    hint = companion_status().hint()
    html = landing_html(pair="x", ticket="A1|x", apk=None, arelis_version="0.2.9")
    visible = re.sub(r"<[^>]+>", " ", html.split("<body>", 1)[1].split("</body>", 1)[0])
    assert "build_companion" not in html

    monkeypatch.setattr("arelis.tools.diagnostics.PROJECT_ROOT", tmp_path)
    from arelis.tools.diagnostics import _run_suite

    missing_tests = _run_suite({})

    monkeypatch.setattr("arelis.login_start.sys.platform", "linux")
    linux_on = install_login_start()
    linux_off = remove_login_start()

    monkeypatch.setattr(update, "is_source_checkout", lambda: True)
    update_lines = []
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(update.sys, "platform", platform)
        _supported, why = update.updates_supported()
        update_lines.append(why)

    lines = {
        "maps": maps.output,
        "solar": blocked.output,
        "load": load_blocked.output,
        "rebound": rebound.output,
        "earth status": earth_status.output,
        "earth enter": earth_enter.output,
        "orbit library": str(caught.value),
        "plate": _PLATE_ONLY,
        "hands": _HANDS_MISSING,
        "video": _VIDEO_REFUSED,
        "hint": hint,
        "phone page": " ".join(visible.split()),
        "filament": _FILAMENT_DETAIL,
        "desk": DESK_GUIDE,
        "diagnostics": missing_tests.output,
        "linux login on": linux_on,
        "linux login off": linux_off,
        "login help": _INSTALL_LOGIN_HELP,
        "remove login help": _REMOVE_LOGIN_HELP,
        "purge help": _PURGE_HELP,
    }
    for why in update_lines:
        lines[f"update {why}"] = why
    for label, text in lines.items():
        _assert_plain(label, text)
    assert "running from source" in maps.output
    assert "installed app" in maps.output
    assert "Chat and planet position lookups still work." in blocked.output


async def _solar_blocked(solar: SolarTool):
    return (
        await solar.run(action="fetch_maps"),
        await solar.run(action="pause"),
        await solar.run(action="load"),
    )


async def _earth_blocked(earth: EarthTool):
    return await earth.run(action="status"), await earth.run(action="enter")
