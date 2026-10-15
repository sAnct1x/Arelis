"""The pull-request tier picker. Push stays on the full suite."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.ci_tier import decide, write_github_output

ROOT = Path(__file__).resolve().parents[1]


def _modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_single_area_runs_only_that_areas_tests() -> None:
    tier = decide(["arelis/earth/land.py"])
    assert tier.kind == "area"
    assert tier.area == "earth"
    assert tier.skip_pytest is False
    assert "tests/test_earth.py" in tier.tests
    assert tier.tests
    assert "tests/test_browser_launch.py" not in tier.tests


def test_sms_send_and_confirm_are_full() -> None:
    sms = decide(["arelis/sms.py"])
    send = decide(["arelis/tools/email_send.py"])
    confirm = decide(["arelis/presence/confirm_exec.py"])
    assert sms.kind == "full" and sms.reason == "safety"
    assert send.kind == "full" and send.reason == "safety"
    assert confirm.kind == "full" and confirm.reason == "safety"


def test_packaged_fonts_and_assets_are_full() -> None:
    fonts = decide(["arelis/ui/fonts/Inter.ttf"])
    assets = decide(["arelis/assets/icon.png"])
    assert fonts.kind == "full" and fonts.reason == "packaged"
    assert assets.kind == "full" and assets.reason == "packaged"
    assert decide(["arelis/ui/fonts/OFL.md"]).reason == "packaged"


def test_area_lists_include_the_importers_the_globs_missed() -> None:
    physics = decide(["arelis/physics/clocks.py"])
    calendar = decide(["arelis/calendar/service.py"])
    memory = decide(["arelis/memory/store.py"])
    assert physics.area == "physics"
    assert "tests/test_world_physics.py" in physics.tests
    assert calendar.area == "calendar"
    assert "tests/test_issue129_calendar_booking.py" in calendar.tests
    assert memory.area == "memory"
    assert "tests/test_live_pass_memory.py" in memory.tests


def test_area_github_output_lists_only_that_areas_tests(tmp_path: Path) -> None:
    tier = decide(["arelis/memory/store.py"])
    output = tmp_path / "github.txt"
    paths = tmp_path / "paths.txt"
    write_github_output(tier, output, paths)
    text = output.read_text(encoding="utf-8")
    assert "tier=area\n" in text
    assert "reason=area\n" in text
    assert "area=memory\n" in text
    assert "skip_pytest=false\n" in text
    listed = [line for line in paths.read_text(encoding="utf-8").splitlines() if line]
    assert "tests/test_live_pass_memory.py" in listed
    assert "tests/test_memory_store.py" in listed
    assert "tests/test_browser_launch.py" not in listed
