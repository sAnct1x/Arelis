"""Installer prune must not delete a PySide6.Qt* module the app imports.

build.py keeps QT_MODULES (must survive) and QT_DROP_PREFIXES (startswith prune).
A module added under arelis/ and forgotten in both places used to ship a tree that
imports QT_MODULES cleanly and then dies on solar_gl's QtOpenGL import at startup.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "win-installer"
ARELIS = ROOT / "arelis"

# Modules imported under arelis/ that the prune still deletes on purpose.
# Each is lazy or guarded, and the installed app cannot reach the path that
# needs them (Earth globe / Cesium is source-checkout only via
# world_stage_allowed()).
GUARDED_DROPPED: dict[str, str] = {
    "QtWebEngineCore": "lazy import in EarthGlobeHost; stage is source-checkout only",
    "QtWebEngineWidgets": "lazy/try in webengine_available and host; not in installer",
    "QtWebChannel": "lazy import in EarthGlobeHost._start_in_process only",
}


def _load_build():
    spec = importlib.util.spec_from_file_location("_inst_build", INSTALLER / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pyside_qt_modules() -> set[str]:
    found: set[str] = set()
    for path in ARELIS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith("PySide6.Qt"):
                        found.add(name.split(".", 2)[1])
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("PySide6.Qt"):
                    found.add(node.module.split(".", 2)[1])
                elif node.module == "PySide6":
                    for alias in node.names:
                        if alias.name.startswith("Qt"):
                            found.add(alias.name)
    return found


def _matched_by_drop(module: str, prefixes: tuple[str, ...]) -> bool:
    # Same startswith test prune_qt uses against entry.name (QtOpenGL.pyd, etc.).
    return module.startswith(prefixes) or f"{module}.pyd".startswith(prefixes)


def test_every_imported_qt_module_survives_or_is_allowlisted() -> None:
    build = _load_build()
    keep = set(build.QT_MODULES)
    prefixes = tuple(build.QT_DROP_PREFIXES)
    imported = _pyside_qt_modules()
    assert imported, "expected PySide6.Qt* imports under arelis/"

    bad: list[str] = []
    for module in sorted(imported):
        if module in keep:
            continue
        if not _matched_by_drop(module, prefixes):
            continue
        if module in GUARDED_DROPPED:
            continue
        bad.append(module)
    assert not bad, "imported PySide6 modules are pruned and not allowlisted: " + ", ".join(bad)


def test_allowlist_entries_are_still_dropped() -> None:
    build = _load_build()
    prefixes = tuple(build.QT_DROP_PREFIXES)
    for module, reason in GUARDED_DROPPED.items():
        assert reason, f"{module} needs a one-line reason"
        assert _matched_by_drop(module, prefixes), (
            f"{module} is allowlisted but no longer matched by QT_DROP_PREFIXES"
        )


def test_qtopengl_is_kept_and_not_pruned() -> None:
    build = _load_build()
    assert "QtOpenGL" in build.QT_MODULES
    prefixes = tuple(build.QT_DROP_PREFIXES)
    assert not _matched_by_drop("QtOpenGL", prefixes)
    # Explicit Widgets name must not take QtOpenGL.pyd with it.
    assert "QtOpenGL.pyd".startswith(prefixes) is False
    assert _matched_by_drop("QtOpenGLWidgets", prefixes)


def test_no_other_prefix_eats_a_required_module() -> None:
    build = _load_build()
    keep = set(build.QT_MODULES)
    prefixes = tuple(build.QT_DROP_PREFIXES)
    for module in sorted(keep):
        assert not _matched_by_drop(module, prefixes), (
            f"QT_MODULES entry {module} is matched by QT_DROP_PREFIXES"
        )


@pytest.mark.parametrize("module", sorted(GUARDED_DROPPED))
def test_allowlisted_module_is_actually_imported(module: str) -> None:
    assert module in _pyside_qt_modules(), (
        f"{module} is allowlisted but no longer imported under arelis/"
    )
