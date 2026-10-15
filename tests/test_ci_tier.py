"""The pull-request tier picker. Push to main stays on the full suite."""

from __future__ import annotations

from pathlib import Path

from scripts.ci_tier import decide, write_github_output


def test_docs_only_skips_pytest() -> None:
    tier = decide(["README.md", "docs/earth.md", "arelis/assets/icon.png"])
    assert tier.kind == "docs"
    assert tier.reason == "docs"
    assert tier.skip_pytest is True
    assert tier.tests == ()


def test_single_area_runs_only_that_areas_tests() -> None:
    tier = decide(["arelis/earth/land.py", "tests/test_earth.py"])
    assert tier.kind == "area"
    assert tier.area == "earth"
    assert tier.skip_pytest is False
    assert "tests/test_earth.py" in tier.tests
    assert tier.tests
    assert all(path.startswith("tests/test_earth") for path in tier.tests)
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
    assert listed
    assert all(line.startswith("tests/test_memory") for line in listed)
