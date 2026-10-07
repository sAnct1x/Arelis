"""The SHA pin check fails on tags and passes on this repo's workflows."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pinned_actions.py"
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_a_tag_pin_fails(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v4\n",
        encoding="utf-8",
    )
    done = _run(str(tmp_path))
    assert done.returncode != 0
    assert ".github/workflows/ci.yml:" in done.stdout


def test_a_sha_pin_with_a_comment_passes(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"jobs:\n  x:\n    steps:\n      - uses: actions/checkout@{SHA} # v7.0.1\n",
        encoding="utf-8",
    )
    done = _run(str(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_local_action_is_ignored(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n  x:\n    steps:\n      - uses: ./tools/local-action\n",
        encoding="utf-8",
    )
    done = _run(str(tmp_path))
    assert done.returncode == 0, done.stdout + done.stderr


def test_repo_workflows_are_pinned() -> None:
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_lint_job_runs_the_pin_check() -> None:
    text = CI_YML.read_text(encoding="utf-8")
    lint = text.split("\n  lint:", 1)[1].split("\n  types:", 1)[0]
    lock = text.split("\n  lock:", 1)[1].split("\n  installed:", 1)[0]
    assert "Actions are pinned by SHA" in lint
    assert "python scripts/check_pinned_actions.py" in lint
    ruff_at = lint.index("- name: Ruff")
    pin_at = lint.index("- name: Actions are pinned by SHA")
    assert ruff_at < pin_at
    assert "check_pinned_actions" not in lock
