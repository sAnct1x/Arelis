"""A non-Python file in the package ships only if package-data names it.

Arelis had no icon. Not a wrong icon or a low-resolution one — none, in the
window, the tray and the taskbar, on every installed copy. The file existed, was
committed, and was loaded by four call sites that all checked ``is_file()`` first
and silently did nothing when it came back false. It sat in ``assets/`` at the
repository root, outside the package, and no glob in ``[tool.setuptools.package-data]``
mentioned it.

Both halves of that are invisible from a checkout, which is the point. Running
from source, the file is exactly where the code looks, so the feature appears to
work perfectly and no test can fail. The bug only exists in an artefact nobody
had built yet.

So this checks the rule rather than the icon. Every non-Python file inside the
package must be covered by a declared glob, which turns "somebody added a font
and forgot pyproject.toml" from a silent absence in a shipped build into a failure
here. It is the same lesson as ``tests/test_user_data_dir.py``, pointed the other
way: that one is about state escaping the package, this one is about assets never
making it in.
"""

from __future__ import annotations

import tomllib
from pathlib import PurePosixPath

from arelis import paths

PROJECT_ROOT = paths.INSTALL_PARENT
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# Generated, never committed, and not something an install needs.
_IGNORED_DIRS = frozenset({"__pycache__"})
_IGNORED_SUFFIXES = frozenset({".pyc", ".pyo"})


def _declared_globs() -> list[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    package_data = data["tool"]["setuptools"]["package-data"]
    return list(package_data["arelis"])


def _shipped_data_files() -> list[PurePosixPath]:
    """Package-relative paths of every file an install would need but not import."""
    found = []
    for path in sorted(paths.PACKAGE_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix == ".py" or path.suffix in _IGNORED_SUFFIXES:
            continue
        found.append(PurePosixPath(path.relative_to(paths.PACKAGE_ROOT).as_posix()))
    return found


def test_every_non_python_file_in_the_package_is_declared() -> None:
    """The rule the icon broke.

    ``PurePath.match`` rather than ``fnmatch`` on purpose: fnmatch lets ``*``
    cross a directory separator, so ``ui/fonts/*`` would appear to cover
    ``ui/fonts/sub/deep.ttf``, which setuptools does not ship. A guard that is
    more permissive than the packaging tool it checks would report success for
    exactly the files that go missing.
    """
    globs = _declared_globs()
    undeclared = [
        str(rel) for rel in _shipped_data_files()
        if not any(rel.match(pattern) for pattern in globs)
    ]
    assert not undeclared, (
        "These files live in the package but no package-data glob covers them, so "
        "they are absent from any installed copy while a checkout works fine. Add "
        "a glob to [tool.setuptools.package-data] in pyproject.toml:\n"
        + "\n".join(f"  arelis/{name}" for name in undeclared)
    )


def test_the_app_icon_is_inside_the_package() -> None:
    """The specific file, because it is the one that was wrong.

    Being outside the package was the root cause: no package-data entry could
    have rescued it, since setuptools only ships what is under a package
    directory. Moving it in is what makes the rule above able to protect it.
    """
    icon = paths.app_icon_path()
    assert icon.is_file(), f"the app icon is missing from the package: {icon}"
    assert icon.is_relative_to(paths.PACKAGE_ROOT)


def test_nothing_reads_the_icon_from_outside_the_package() -> None:
    """Four call sites read this path, and every one failed softly.

    Each guarded the load with is_file() and fell back to no icon, so the missing
    file produced no log line, no exception and no visible complaint — just an
    application with a blank icon and nothing to explain why. A single resolver
    means the next reader finds one definition instead of four copies to keep in
    step.
    """
    hits = []
    for path in sorted(paths.PACKAGE_ROOT.rglob("*.py")):
        if path.name == "paths.py":
            continue
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "arelis.ico" in line:
                rel = path.relative_to(paths.PACKAGE_ROOT).as_posix()
                hits.append(f"  arelis/{rel}:{line_no}")
    assert not hits, (
        "Name the icon through arelis.paths.app_icon_path() rather than rebuilding "
        "the path, so there is one place to be wrong:\n" + "\n".join(hits)
    )


def test_the_shipped_asset_directory_holds_only_what_it_should() -> None:
    """A guard against the easy over-correction.

    ``assets/*`` is a wildcard, and the tempting next step after this fix is to
    drop other things beside the icon. Anything mutable put here would be written
    inside the install directory — unwritable for a standard user, wiped by the
    next update — which is the defect the path migration existed to remove.
    """
    assets = paths.PACKAGE_ROOT / "assets"
    names = sorted(p.name for p in assets.iterdir() if p.is_file())
    assert names == ["arelis.ico", "arelis.png"], (
        "arelis/assets/ is for shipped, read-only images. Mutable state belongs "
        f"under arelis.paths.state_dir(). Found: {names}"
    )


def test_an_installed_copy_can_start_sentinel(tmp_path) -> None:
    """Sentinel used to start only from a checkout.

    The wheel shipped ``arelis*`` and nothing else, so an installed copy had no
    ``sentinel`` package, ``_sentinel_root()`` returned None and launch logged
    "Sentinel did not start". psutil was not in the installer extra or the lock
    either. This lays out site-packages the way the declared packaging would
    and asks the real ``_sentinel_root`` to find it. Dropping the ``sentinel``
    package or its data from pyproject, psutil from the installer extra or the
    lock, or the installed fallback in ``_sentinel_root``, fails this test.
    """
    import importlib.util
    import shutil
    import sys

    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    setuptools_cfg = data["tool"]["setuptools"]
    find = setuptools_cfg["packages"]["find"]
    assert "sentinel" in find["where"] and "sentinel" in find["include"]
    globs = list(setuptools_cfg["package-data"].get("sentinel", []))

    source = PROJECT_ROOT / "sentinel" / "sentinel"
    site = tmp_path / "site-packages"
    for path in source.rglob("*"):
        if not path.is_file() or any(p in _IGNORED_DIRS for p in path.parts):
            continue
        rel = PurePosixPath(path.relative_to(source).as_posix())
        if path.suffix != ".py" and not any(rel.match(g) for g in globs):
            continue
        dest = site / "sentinel" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    for needed in ("__main__.py", "config/default.yaml", "ui/overseer/index.html"):
        assert (site / "sentinel" / needed).is_file(), f"not shipped: sentinel/{needed}"

    (site / "arelis").mkdir()
    control = site / "arelis" / "sentinel_control.py"
    shutil.copyfile(paths.PACKAGE_ROOT / "sentinel_control.py", control)
    spec = importlib.util.spec_from_file_location("_installed_sentinel_control", control)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._sentinel_root() == site

    lock_spec = importlib.util.spec_from_file_location(
        "_win_lock", PROJECT_ROOT / "win-installer" / "lock.py"
    )
    assert lock_spec is not None and lock_spec.loader is not None
    lock = importlib.util.module_from_spec(lock_spec)
    sys.modules.setdefault("_win_lock", lock)
    lock_spec.loader.exec_module(lock)
    assert "psutil" in lock.declared_dependencies()
    assert "psutil" in lock.read_lock()
