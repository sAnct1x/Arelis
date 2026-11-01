"""Installer prune must not delete a PySide6.Qt* module the app imports.

build.py keeps QT_MODULES (must survive) and QT_DROP_PREFIXES (startswith prune).
A module added under arelis/ and forgotten in both places used to ship a tree that
imports QT_MODULES cleanly and then dies on solar_gl's QtOpenGL import at startup.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "win-installer"
ARELIS = ROOT / "arelis"

# Modules imported under arelis/ that the prune still deletes on purpose. None now:
# the Quick 3D avatar's QtQuick3D, QtQuickWidgets and QtQml ship in QT_MODULES.
GUARDED_DROPPED: dict[str, str] = {}


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


def test_installer_ships_the_committed_qq3d_model_by_default() -> None:
    # Fresh installs had no Quick 3D model because nothing shipped it. It is now committed
    # in arelis/assets/qq3d, so every tree carries it and plain build.py ships it.
    import tomllib
    from pathlib import PurePosixPath

    build = _load_build()
    model = ARELIS / build.QQ3D_IN_SITE.relative_to("arelis")
    assert (model / build.QQ3D_LOOK).is_file()
    files = [p for p in model.rglob("*") if p.is_file()]
    assert not [p for p in files if p.suffix == ".glb"]
    assert max(p.stat().st_size for p in files) < 100 * 1024 * 1024  # GitHub's per-file cap
    # Every model file is package data, so the wheel (and so the tree) holds all of it.
    globs = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"][
        "setuptools"
    ]["package-data"]["arelis"]
    rels = [PurePosixPath(p.relative_to(ARELIS).as_posix()) for p in files]
    assert not [r for r in rels if not any(r.match(g) for g in globs)]
    # The tree check passes on a checkout-shaped site (arelis/ beside it) and needs the model.
    build.check_avatar_assets(ROOT)

    # arelis.iss moves it out of {app} into the data folder, kept on a plain uninstall.
    iss = (INSTALLER / "arelis.iss").read_text(encoding="utf-8")
    assert 'Excludes: "\\Lib\\site-packages\\arelis\\assets\\qq3d"' in iss
    assert (
        'Source: "{#SourceTree}\\Lib\\site-packages\\arelis\\assets\\qq3d\\*"; '
        'DestDir: "{localappdata}\\Arelis\\avatar\\qq3d"'
    ) in iss
    assert "uninsneveruninstall" in iss.split("assets\\qq3d\\*", 1)[1].splitlines()[0]
    assert "#ifdef Qq3dTree" not in iss
    # No flag, no staged folder: CI and local builds are the same plain command.
    workflow = (INSTALLER.parent / ".github" / "workflows" / "windows-installer.yml").read_text(
        encoding="utf-8"
    )
    assert "run: python win-installer/build.py\n" in workflow
    assert "--qq3d-dir" not in (INSTALLER / "build.py").read_text(encoding="utf-8")
