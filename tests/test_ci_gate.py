"""Pins that keep CI from becoming eight ruff emails and a six-hour hang.

The workflow is the product. A solar-lab commit that failed ruff used to fail
the 8-way test matrix, skip pytest, and leave the previous run on GitHub's
six-hour wall. These tests read the workflow file so putting ruff back inside
the matrix, dropping the job timeout, or importing windll at module level
fails on a laptop too, not only after push.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE = ROOT / "arelis"

# ctypes / Win32 names that exist only on Windows. Importing them at module
# level aborts pytest collection on Ubuntu before a single test runs.
_FORBIDDEN_CTYPES = frozenset({"windll", "wintypes"})
_FORBIDDEN_MODULES = frozenset(
    {"winreg", "msvcrt", "win32api", "win32con", "win32gui", "pythoncom"}
)


# Same block on every workflow that push or pull_request can start.
# A pull request groups on the PR number. A main push groups on the commit
# SHA, so queued main runs are never cancelled. Nightly and tool choice
# are schedule-only and keep their own group.
_PUSH_PR_CONCURRENCY = (
    "concurrency:\n"
    "  group: ${{ github.workflow }}-${{ github.ref == 'refs/heads/main' && github.sha || github.event.pull_request.number || github.ref }}\n"
    "  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}\n"
)


def _trigger_block(text: str) -> str:
    match = re.search(
        r"(?m)^on:\n(.*?)(?=^(?:jobs|permissions|concurrency|env):)",
        text,
        re.S,
    )
    return match.group(1) if match else ""


def _push_or_pull_request(text: str) -> bool:
    block = _trigger_block(text)
    return bool(re.search(r"(?m)^  (push|pull_request):", block))


def test_push_and_pull_request_workflows_share_one_concurrency_group() -> None:
    workflows = ROOT / ".github" / "workflows"
    push_pr = []
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if _push_or_pull_request(text):
            push_pr.append(path.name)
            assert _PUSH_PR_CONCURRENCY in text, path.name
            assert "github.head_ref" not in text, path.name
    assert "ci.yml" in push_pr
    assert "nightly-live.yml" not in push_pr
    assert "tool-choice.yml" not in push_pr
    for name in ("nightly-live.yml", "tool-choice.yml"):
        text = (workflows / name).read_text(encoding="utf-8")
        assert "github.head_ref" not in text
        assert not _push_or_pull_request(text)


def test_mypy_reports_on_the_repo_and_gates_only_the_clean_packages() -> None:
    """Two mypy steps with opposite jobs, and neither may take the other's.

    Repo-wide mypy reports a number. It cannot fail CI, because a thousand
    pre-existing errors would block work that is not a type-fix — that is
    what `|| true` buys. The strict step is the opposite: packages listed
    in `mypy_strict_packages.txt` are already clean, and a clean package
    that is allowed to regress is not clean. It must have no `|| true`.

    `continue-on-error: true` on the job would swallow the strict step, so
    its absence is load-bearing now rather than a leftover.
    """
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    workflow = CI_YML.read_text(encoding="utf-8")
    pin = re.search(r'"mypy==(\d+\.\d+\.\d+)"', pyproject)
    assert pin, "dev extra must pin mypy==x.y.z the same way it pins ruff"
    assert "[tool.mypy]" in pyproject, "permissive mypy config lives in pyproject.toml"
    assert "ignore_missing_imports = true" in pyproject
    wf_pin = re.search(r'mypy==(\d+\.\d+\.\d+)', workflow)
    assert wf_pin, "types job must install the same mypy pin"
    assert wf_pin.group(1) == pin.group(1)
    assert re.search(r"(?m)^  types:", workflow), "CI lost the types report job"
    # Bound at the next top-level job, not at `test:` — `eval:` sits between
    # them, and swallowing it would check another job's error handling here.
    after = workflow.split("\n  types:", 1)[1]
    next_job = re.search(r"(?m)^  [a-z][a-z0-9_-]*:$", after)
    types_block = after[: next_job.start()] if next_job else after
    assert "continue-on-error: true" not in types_block, (
        "continue-on-error on the types job would swallow the strict gate"
    )

    runs = re.findall(r"(?m)^        run: (python -m mypy .*)$", types_block)
    report = [r for r in runs if "mypy_strict_packages.txt" not in r]
    strict = [r for r in runs if "mypy_strict_packages.txt" in r]
    assert len(report) == 1, f"expected one repo-wide mypy report step, got {runs}"
    assert len(strict) == 1, f"expected one strict-gate mypy step, got {runs}"
    assert "|| true" in report[0], "the repo-wide report must never fail CI"
    assert "|| true" not in strict[0], "a gate that cannot fail is not a gate"

    test_block = workflow.split("\n  test:", 1)[1].split("\n  lock:", 1)[0]
    installed_block = workflow.split("\n  installed:", 1)[1]
    assert "mypy" not in test_block.lower()
    assert "mypy" not in installed_block.lower()


def test_macos_cell_may_fail_without_opening_the_gate() -> None:
    """macOS is informational. Windows and Ubuntu still fail the workflow."""
    loaded = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    jobs = loaded["jobs"]
    for name in ("test", "installed"):
        job = jobs[name]
        assert job["continue-on-error"] == "${{ matrix.experimental == true }}"
        include = job["strategy"]["matrix"]["include"]
        by_os = {row["os"]: row for row in include}
        assert set(by_os) == {"windows-latest", "ubuntu-latest", "macos-latest"}
        mac = by_os["macos-latest"]
        assert mac["python-version"] == "3.14"
        assert mac["experimental"] is True
        assert "experimental" not in by_os["windows-latest"]
        assert "experimental" not in by_os["ubuntu-latest"]
        assert by_os["windows-latest"]["python-version"] == "3.14"
        assert by_os["ubuntu-latest"]["python-version"] == "3.11"


def test_ci_runs_the_eval_boards_as_a_gate() -> None:
    """The boards ran nowhere for months; that is how they rotted.

    Blocking rather than continue-on-error, and separate from the 2,000-test
    matrix so a routing regression reads as "eval failed" instead of one red
    dot among two thousand.
    """
    text = CI_YML.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  eval:", text), "CI lost the eval board job"
    block = text.split("\n  eval:", 1)[1].split("\n  test:", 1)[0]
    assert "continue-on-error" not in block, "the eval board must be a gate"
    for path in (
        "tests/test_eval_board.py",
        "tests/test_eval_stub_schemas.py",
        "tests/test_tool_schema_quality.py",
    ):
        assert path in block, f"eval job stopped running {path}"


def test_pytest_has_a_per_test_timeout() -> None:
    loaded = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev = loaded["project"]["optional-dependencies"]["dev"]
    assert any(item.startswith("pytest-timeout") for item in dev)
    timeout = loaded["tool"]["pytest"]["ini_options"]["timeout"]
    assert isinstance(timeout, int) and timeout > 0


