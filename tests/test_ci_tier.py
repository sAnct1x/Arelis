"""The pull-request tier picker. Push stays on the full suite."""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.ci_tier import AREA_IMPORTS, area_tests, decide, write_github_output

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


def test_docs_only_skips_pytest() -> None:
    tier = decide(["README.md", "docs/earth.md", "LICENSE", "assets/icon.png"])
    assert tier.kind == "docs"
    assert tier.reason == "docs"
    assert tier.skip_pytest is True
    assert tier.tests == ()


def test_single_area_runs_only_that_areas_tests() -> None:
    tier = decide(["arelis/earth/land.py"])
    assert tier.kind == "area"
    assert tier.area == "earth"
    assert tier.skip_pytest is False
    assert "tests/test_earth.py" in tier.tests
    assert tier.tests
    assert "tests/test_browser_launch.py" not in tier.tests


def test_core_runs_the_full_suite() -> None:
    tier = decide(["arelis/core/agent_loop.py"])
    assert tier.kind == "full"
    assert tier.reason == "core"
    assert tier.skip_pytest is False
    assert tier.tests == ()


def test_unknown_path_runs_the_full_suite() -> None:
    tier = decide(["vendor/leftpad.py"])
    assert tier.kind == "full"
    assert tier.reason == "unknown"
    assert tier.skip_pytest is False


def test_prompt_markdown_is_not_docs() -> None:
    tier = decide(["arelis/persona/arelis.md"])
    assert tier.kind == "full"
    assert tier.reason == "prompts"


def test_docs_beside_one_area_stay_that_area() -> None:
    tier = decide(["README.md", "arelis/voice/wake.py"])
    assert tier.kind == "area"
    assert tier.area == "voice"
    assert "tests/test_wake.py" in tier.tests


def test_two_areas_run_the_full_suite() -> None:
    tier = decide(["arelis/earth/land.py", "arelis/browser/session.py"])
    assert tier.kind == "full"
    assert tier.reason == "mixed"


def test_push_to_main_is_full_even_for_docs() -> None:
    tier = decide(["README.md"], event="push", ref="refs/heads/main")
    assert tier.kind == "full"
    assert tier.reason == "main"
    assert tier.skip_pytest is False


def test_push_to_a_non_main_branch_is_full() -> None:
    tier = decide(["README.md"], event="push", ref="refs/heads/feature")
    assert tier.kind == "full"
    assert tier.reason == "push"
    assert tier.skip_pytest is False


def test_empty_file_list_is_full() -> None:
    tier = decide([])
    assert tier.kind == "full"
    assert tier.reason == "unknown"
    assert tier.skip_pytest is False


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


def test_conftest_and_fixtures_are_full() -> None:
    conftest = decide(["tests/conftest.py"])
    nested = decide(["tests/earth/conftest.py"])
    fixture = decide(["tests/fixtures/sample.json"])
    assert conftest.kind == "full" and conftest.reason == "ci"
    assert nested.kind == "full" and nested.reason == "ci"
    assert fixture.kind == "full" and fixture.reason == "ci"


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


def test_every_test_that_imports_an_area_is_in_that_areas_list() -> None:
    listed = {name: set(area_tests(name, ROOT)) for name, _roots in AREA_IMPORTS}
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        modules = _modules(path)
        rel = path.relative_to(ROOT).as_posix()
        serial = "pytest.mark.serial" in path.read_text(encoding="utf-8")
        for name, roots in AREA_IMPORTS:
            imported = any(
                mod == root or mod.startswith(root + ".") for root in roots for mod in modules
            )
            if not imported:
                continue
            assert rel in listed[name], f"{rel} imports {name} and is missing from the list"
            if serial:
                assert rel in listed[name]


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
