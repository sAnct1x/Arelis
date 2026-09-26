"""Pins that keep CI from becoming eight ruff emails and a six-hour hang.

The workflow is the product. A solar-lab commit that failed ruff used to fail
the 8-way test matrix, skip pytest, and leave the previous run on GitHub's
six-hour wall. These tests read the workflow file so putting ruff back inside
the matrix, dropping the job timeout, or importing windll at module level
fails on a laptop too, not only after push.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

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


def test_ci_runs_ruff_once_before_the_matrix() -> None:
    """One lint job. The 8-way pytest matrix waits on it. Ruff is not a step there."""
    text = CI_YML.read_text(encoding="utf-8")
    assert re.search(r"(?m)^  lint:", text), "CI lost the lint job"
    assert re.search(r"(?m)^    needs: lint", text), "test/installed must wait on lint"
    assert text.count("needs: lint") >= 2, "both test and installed must wait on lint"
    # The test job must not run ruff itself — that is the eight-email bug.
    test_block = text.split("\n  test:", 1)[1].split("\n  lock:", 1)[0]
    assert "ruff check" not in test_block.lower()


def test_ci_cancels_leftover_runs_and_cannot_sit_six_hours() -> None:
    text = CI_YML.read_text(encoding="utf-8")
    assert "cancel-in-progress: true" in text
    assert re.search(r"(?m)^    timeout-minutes: 25", text), "test job needs a ceiling"
    assert re.search(r"(?m)^    timeout-minutes: 5", text), "lint/lock need a ceiling"


def test_ci_ruff_pin_matches_pyproject() -> None:
    workflow = CI_YML.read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    wf_match = re.search(r'ruff==(\d+\.\d+\.\d+)', workflow)
    py_match = re.search(r'"ruff==(\d+\.\d+\.\d+)"', pyproject)
    assert wf_match and py_match, "ruff pin missing from ci.yml or pyproject.toml"
    assert wf_match.group(1) == py_match.group(1), (
        f"ci.yml installs ruff=={wf_match.group(1)}, "
        f"pyproject pins ruff=={py_match.group(1)}"
    )


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


def test_ci_matrix_is_the_two_claimed_interpreters() -> None:
    """Windows 3.14 is what we ship. Ubuntu 3.11 is the requires-python floor."""
    text = CI_YML.read_text(encoding="utf-8")
    test_block = text.split("\n  test:", 1)[1].split("\n  lock:", 1)[0]
    installed_block = text.split("\n  installed:", 1)[1]
    for block in (test_block, installed_block):
        assert "3.12" not in block
        assert "3.13" not in block
        assert '"3.14"' in block
        assert '"3.11"' in block
        assert "windows-latest" in block
        assert "ubuntu-latest" in block
    assert not re.search(r"(?m)^  coverage:", text)


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


def test_guard_coverage_runs_on_a_schedule() -> None:
    """mutate_guards is the proof the board can fail. Unrun, it proves nothing."""
    path = ROOT / ".github" / "workflows" / "guard-coverage.yml"
    assert path.exists(), "the weekly guard-coverage workflow is gone"
    text = path.read_text(encoding="utf-8")
    assert "schedule:" in text and "cron:" in text
    assert "scripts/mutate_guards.py" in text


def test_pytest_has_a_per_test_timeout() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "pytest-timeout" in text
    assert re.search(r"(?m)^timeout = \d+", text)


def test_linux_does_not_construct_the_webengine_host_unless_asked() -> None:
    """EarthGlobeHost on headless Linux can sit through the thread timeout.

    Deleting this skip to 'get the test back' is how a runner waits six hours.
    Windows still constructs the host. Opt in on Linux with ARELIS_GLOBE_HOST_TEST.
    """
    text = (ROOT / "tests" / "test_globe_stack.py").read_text(encoding="utf-8")
    assert "ARELIS_GLOBE_HOST_TEST" in text
    assert "EarthGlobeHost can hang headless Linux" in text
    assert "test_pytest_constructs_webengine_host" in text


def test_no_windows_only_import_at_module_level() -> None:
    """Linux ctypes has no windll. Collection must not die on import."""
    offenders: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(ROOT).as_posix()
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in _FORBIDDEN_MODULES or alias.name in _FORBIDDEN_MODULES:
                        offenders.append(f"{rel}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in _FORBIDDEN_MODULES or mod.split(".", 1)[0] in _FORBIDDEN_MODULES:
                    offenders.append(f"{rel}: from {mod} import …")
                if mod == "ctypes":
                    names = {alias.name for alias in node.names}
                    hit = names & _FORBIDDEN_CTYPES
                    if hit:
                        offenders.append(f"{rel}: from ctypes import {sorted(hit)}")
    assert not offenders, (
        "Windows-only names at module level abort Ubuntu collection:\n  "
        + "\n  ".join(offenders)
    )
