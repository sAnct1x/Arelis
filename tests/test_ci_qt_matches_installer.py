"""The CI test job must install the Qt the Windows installer ships.

pyproject allows PySide6>=6.6, so an unpinned `pip install -e ".[dev]"`
follows PyPI. The installer lock is the version we actually ship. This
test reads the workflow as YAML and checks the test job's install step
builds a constraints file from that lock and passes it to pip.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"
LOCK = ROOT / "win-installer" / "requirements-win-amd64-cp314.txt"
_SCRIPT = ROOT / "scripts" / "qt_constraints_from_installer_lock.py"

_QT_NAMES = (
    "PySide6",
    "PySide6_Addons",
    "PySide6_Essentials",
    "shiboken6",
)


def _workflow() -> dict:
    loaded = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _test_job() -> dict:
    job = _workflow()["jobs"]["test"]
    assert isinstance(job, dict)
    return job


def _install_step() -> dict:
    steps = _test_job()["steps"]
    assert isinstance(steps, list)
    for step in steps:
        if step.get("name") == "Install package":
            assert isinstance(step, dict)
            return step
    raise AssertionError("test job has no Install package step")


def _script_lines(run: str) -> list[str]:
    return [line.strip() for line in run.splitlines() if line.strip()]


def _load_extractor():
    spec = importlib.util.spec_from_file_location("qt_constraints_from_installer_lock", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_matrix_cells_share_one_constrained_install() -> None:
    """Windows, Ubuntu, and the macOS cell all run the same install.

    The macOS cell is informational. It still has to install the shipped Qt,
    not whatever PyPI currently calls latest.
    """
    job = _test_job()
    include = job["strategy"]["matrix"]["include"]
    oss = {row["os"] for row in include}
    assert oss == {"windows-latest", "ubuntu-latest", "macos-latest"}

    step = _install_step()
    assert "if" not in step, "a per-OS install would let one cell float to PyPI"
    lines = _script_lines(str(step.get("run") or ""))

    extractors = [line for line in lines if "qt_constraints_from_installer_lock.py" in line]
    assert len(extractors) == 1, lines
    assert "--out" in extractors[0], extractors[0]

    installs = [line for line in lines if "pip install" in line]
    assert len(installs) == 1, lines
    install = installs[0]
    assert '-e ".[dev]"' in install, install
    assert "-c " in install, install
    constraint = install.split("-c ", 1)[1].split()[0]
    assert constraint in extractors[0], (extractors[0], install)


def test_extractor_pins_match_the_installer_lock() -> None:
    module = _load_extractor()
    pins = module.pins_from_lock(LOCK.read_text(encoding="utf-8"))
    assert [pin.split("==", 1)[0] for pin in pins] == list(_QT_NAMES)
    assert pins == [f"{name}==6.11.2" for name in _QT_NAMES]
    assert all("--hash" not in pin for pin in pins)
    assert module.LOCK_RELATIVE.as_posix() == "win-installer/requirements-win-amd64-cp314.txt"
