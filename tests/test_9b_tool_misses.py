"""Bench misses: named-city weather, saved place, constants, git, read-back.

These prompts are ordinary asks. They must not depend on the exact bench wording.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

from arelis.core.failure_copy import chat_followup_from_tool
from arelis.core.tool_surface import apply_expected
from arelis.core.turn_scratch import (
    close_tools_after_progress,
    closing_call_ok,
    closing_tool_names,
)
from arelis.memory.store import MemoryStore
from arelis.rooms import RoomStore
from arelis.tools import build_tool_registry
from arelis.tools.git_info import GitInfoTool
from arelis.tools.units import UnitsTool
from arelis.tools.weather import extract_weather_place, place_query_for_geocode


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path, message: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    (path / "note.txt").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", message)


def _registry(tmp_path: Path, profile: Path):
    config = {
        "location": {
            "enabled": False,
            "profile_path": str(profile),
            "use_system": False,
            "network": {"enabled": False},
        },
        "tools": {
            "email": {"enabled": False},
            "sms": {"enabled": False},
        },
        "agent": {},
        "workspace": {"roots": [str(tmp_path)]},
        "_rooms": RoomStore(tmp_path / "rooms.yaml"),
    }
    return build_tool_registry(
        config,
        memory_store=MemoryStore(tmp_path / "memory.db"),
        attended=True,
    )


def test_named_city_forecast_keeps_weather_when_place_lookup_is_off(tmp_path: Path) -> None:
    """A saved place being turned off must not hide the forecast for a named city."""
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "location:\n  city: Springfield\n  region: Illinois\n  country: US\n"
        "  latitude: 39.7817\n  longitude: -89.6501\n  timezone: America/Chicago\n",
        encoding="utf-8",
    )
    names = set(_registry(tmp_path, profile).names())
    assert "weather" in names
    assert "user_location" in names


def test_saved_place_still_answers_with_the_profile_city(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "location:\n  city: Springfield\n  region: Illinois\n  country: US\n",
        encoding="utf-8",
    )
    registry = _registry(tmp_path, profile)
    result = asyncio.run(registry.get("user_location").run())
    assert result.ok
    assert "Springfield" in result.output


def test_speed_of_light_followup_states_the_number() -> None:
    result = asyncio.run(UnitsTool().run(action="constant", name="c"))
    assert result.ok, result.output
    line = chat_followup_from_tool(
        "units",
        result.output,
        ask="What is the speed of light in m/s?",
    )
    assert "299,792,458" in line or "299792458" in line
    assert "could not put it into words" not in line.lower()


def test_profile_city_ask_does_not_offer_the_planet(tmp_path: Path) -> None:
    del tmp_path
    visible = {"earth", "browser", "user_location", "weather", "web_search", "memory"}
    loop = SimpleNamespace(
        _expected_tools=set(),
        memory=SimpleNamespace(messages=[]),
        _look=None,
    )
    offered, _shown = apply_expected(
        loop,
        set(visible),
        text="What city is my profile location set to?",
        available_all=set(visible),
    )
    assert "user_location" in offered
    assert "earth" not in offered
    assert "browser" not in offered


def test_git_log_uses_the_only_repo_one_folder_down(tmp_path: Path) -> None:
    desk = tmp_path / "desk"
    desk.mkdir()
    (desk / "work").mkdir()
    _init_repo(desk / "notes", "silent excepts")
    tool = GitInfoTool([str(desk)])
    result = asyncio.run(tool.run(action="log", n=2))
    assert result.ok, result.output
    assert "silent excepts" in result.output


def test_git_log_names_the_folders_it_can_see(tmp_path: Path) -> None:
    desk = tmp_path / "desk"
    (desk / "work").mkdir(parents=True)
    (desk / "outputs").mkdir()
    tool = GitInfoTool([str(desk)])
    result = asyncio.run(tool.run(action="log", n=2))
    assert result.ok is False
    assert "work" in result.output
    assert "outputs" in result.output


def test_wrap_up_still_allows_the_file_read() -> None:
    ask = (
        "Write a Python script work/sq.py that prints the square of 12, "
        "then run it, then read work/sq.py back and show me its contents."
    )
    trace = ["workspace write work/sq.py", "run_script work/sq.py"]
    keep = closing_tool_names(
        ask, trace, have_document=True, have_workspace=True
    )
    assert "workspace" in keep
    assert closing_call_ok("workspace", {"action": "read", "path": "work/sq.py"}, ask, trace)
    assert not closing_call_ok("workspace", {"action": "write"}, ask, trace)
    assert "workspace" not in closing_tool_names(
        ask,
        [*trace, "workspace read work/sq.py"],
        have_document=True,
        have_workspace=True,
    )


def test_named_state_is_a_geocode_query_the_gazetteer_accepts() -> None:
    place = extract_weather_place(
        "What's the weather forecast for Springfield, Illinois today?"
    )
    assert place_query_for_geocode(place) == "Springfield, Illinois"


def test_read_back_keeps_tools_after_the_script_ran() -> None:
    ask = (
        "Write a Python script work/sq.py that prints the square of 12, "
        "run it, then read the file back and show me its contents."
    )
    trace = ["workspace write work/sq.py", "run_script work/sq.py"]
    assert (
        close_tools_after_progress(
            missing_kinds=set(),
            owed=[],
            text=ask,
            trace=trace,
        )
        is False
    )
    assert (
        close_tools_after_progress(
            missing_kinds=set(),
            owed=[],
            text=ask,
            trace=[*trace, "workspace read work/sq.py"],
        )
        is True
    )
