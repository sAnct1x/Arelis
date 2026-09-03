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


def test_mypy_is_pinned_in_dev_and_is_not_a_ci_gate() -> None:
    """mypy exists so the error count is a number, not so CI fails on it.

    A floating extra would make today's baseline meaningless tomorrow. A
    failing mypy job would block work that is not a type-fix. The types
    job reports; continue-on-error keeps it off the merge gate.
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
    types_block = workflow.split("\n  types:", 1)[1]
    types_block = types_block.split("\n  test:", 1)[0]
    assert "continue-on-error: true" in types_block
    assert "python -m mypy" in types_block
    test_block = workflow.split("\n  test:", 1)[1].split("\n  lock:", 1)[0]
    installed_block = workflow.split("\n  installed:", 1)[1]
    assert "mypy" not in test_block.lower()
    assert "mypy" not in installed_block.lower()


def test_coverage_report_is_informational() -> None:
    """Earth/spatial coverage is a number in CI, not a failing threshold."""
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    workflow = CI_YML.read_text(encoding="utf-8")
    assert "pytest-cov" in pyproject
    assert re.search(r"(?m)^  coverage:", workflow)
    cov_block = workflow.split("\n  coverage:", 1)[1].split("\n  test:", 1)[0]
    assert "continue-on-error: true" in cov_block
    assert "--cov=arelis.earth" in cov_block
    assert "--cov=arelis.spatial" in cov_block
    assert "--cov-fail-under" not in workflow
    test_block = workflow.split("\n  test:", 1)[1].split("\n  lock:", 1)[0]
    assert "--cov" not in test_block


def test_pytest_has_a_per_test_timeout() -> None:
    text = PYPROJECT.read_text(encoding="utf-8")
    assert "pytest-timeout" in text
    assert re.search(r"(?m)^timeout = \d+", text)


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
