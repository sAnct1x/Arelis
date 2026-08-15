"""One version and one licence, stated in several places, all agreeing.

The version appears in `arelis/__init__.py`, in the packaging metadata, on
`arelis --version` and at the foot of the shortcuts sheet. The licence appears
in `__init__.py`, in `pyproject.toml` and as the full text in LICENSE. Facts
repeated in four places drift apart quietly, and the failure is not visible
until a user reports a bug against a version that was never released.

So none of them is allowed to hold its own copy: the tests below pin the single
source and check that every other surface reads from it.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import arelis

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"
LICENSE_FILE = PROJECT_ROOT / "LICENSE"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_packaging_reads_the_version_rather_than_repeating_it() -> None:
    """A second copy of the number is the thing that goes stale."""
    project = _pyproject()["project"]
    assert "version" in project.get("dynamic", []), (
        "pyproject.toml should declare version as dynamic. A literal version = "
        "\"…\" here is a second source of truth that nothing keeps in step with "
        "arelis/__init__.py."
    )
    assert "version" not in project, (
        "pyproject.toml declares version dynamic and also sets it literally. "
        "Build backends reject that, and it means the number is written twice."
    )

    attr = _pyproject()["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "arelis.__version__"


def test_the_version_is_a_number_a_release_can_use() -> None:
    """Not a strict PEP 440 parse — just enough that it can be ordered."""
    parts = arelis.__version__.split(".")
    assert len(parts) >= 2, f"{arelis.__version__!r} is not a dotted version"
    assert parts[0].isdigit() and parts[1].isdigit(), (
        f"{arelis.__version__!r} does not start with numeric major.minor, so "
        "an updater cannot tell whether it is newer than what is installed."
    )


def test_the_licence_is_stated_the_same_way_everywhere() -> None:
    declared = _pyproject()["project"]["license"]["text"]
    assert declared == arelis.__license__, (
        f"pyproject.toml says {declared!r} and arelis/__init__.py says "
        f"{arelis.__license__!r}. One of them is wrong, and a wrong licence is "
        "not a cosmetic defect."
    )

    classifiers = _pyproject()["project"]["classifiers"]
    assert any("Affero" in c for c in classifiers), (
        "No Affero classifier. Package indexes and licence scanners read the "
        "classifier, not the license field."
    )


def test_the_licence_file_is_the_full_agpl_text() -> None:
    """A named licence with the wrong text grants nothing anyone can rely on."""
    text = LICENSE_FILE.read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 19 November 2007" in text
    # Section 13 is the whole reason this is the Affero variant rather than the
    # GPL: it closes the network-use loophole. Its absence would mean the file
    # is actually the plain GPL under an Affero heading.
    assert "Remote Network Interaction" in text


def test_the_source_url_is_somewhere_a_person_can_go() -> None:
    """The AGPL only means anything if the source can actually be found."""
    assert arelis.__source_url__.startswith("https://"), (
        "The source URL must be a real https address. It is shown to users as "
        "their route to the source the licence entitles them to."
    )


def test_version_flag_reports_version_licence_and_source() -> None:
    """`arelis --version` is what someone runs before filing a bug."""
    result = subprocess.run(
        [sys.executable, "-m", "arelis.main", "--version"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert arelis.__version__ in out
    assert arelis.__license__ in out
    assert arelis.__source_url__ in out


def test_the_shortcuts_sheet_names_the_running_version() -> None:
    """The only route to this for someone who never opens a terminal."""
    pytest.importorskip("PySide6")
    from arelis.ui.shortcuts import about_line

    line = about_line()
    assert arelis.__version__ in line
    assert arelis.__license__ in line
    assert arelis.__source_url__ in line
