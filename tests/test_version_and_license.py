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


def test_the_licence_file_is_the_full_agpl_text() -> None:
    """A named licence with the wrong text grants nothing anyone can rely on."""
    raw = LICENSE_FILE.read_bytes()
    text = raw.decode("utf-8")
    flat = " ".join(text.split())
    assert len(raw) >= 30_000
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 19 November 2007" in text
    assert "0. Definitions." in text
    assert "13. Remote Network Interaction; Use with the GNU General Public License." in text
    assert (
        "your modified version must prominently offer all users "
        "interacting with it remotely through a computer network"
    ) in flat
    assert "15. Disclaimer of Warranty." in text
    assert "END OF TERMS AND CONDITIONS" in text
    assert "How to Apply These Terms to Your New Programs" in text


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


