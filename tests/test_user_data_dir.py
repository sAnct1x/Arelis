"""User data must live outside the installed program, per account.

Every mutable path in Arelis used to be derived from the directory above the
package. That is the repository in a checkout, which is why nothing ever looked
wrong, and it is ``site-packages`` once installed -- inside Program Files on
Windows. Three separate failures were waiting there: a standard user cannot write
to it, an update replaces it wholesale, and every account on the machine shares
it. Saving a contact would have failed, or succeeded and then vanished at the next
version, or shown one person another person's records.

These tests pin the resolution rules rather than any one directory, because the
answer differs per platform and per account and the property that matters is the
shape: never inside the package, never shared between users, and created on
demand rather than assumed to exist.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from arelis import paths

MUTABLE_RESOLVERS = (
    paths.user_data_dir,
    paths.state_dir,
    paths.logs_dir,
    paths.outputs_dir,
    paths.models_dir,
    paths.cache_dir,
)


# ------------------------------------------------- nothing writes into the code


def test_no_mutable_directory_falls_inside_the_installed_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The defect in one assertion, stated as a property rather than a path.

    Asserting the literal %LOCALAPPDATA% location would pass on the developer's
    machine and prove nothing about anyone else's. What has to hold everywhere is
    that no directory Arelis writes to is inside the directory Arelis was
    installed into.
    """
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    package = paths.PACKAGE_ROOT.resolve()
    for resolve in MUTABLE_RESOLVERS:
        resolved = resolve().resolve()
        assert package != resolved
        assert package not in resolved.parents, (
            f"{resolve.__name__}() resolved inside the package directory, which "
            "an update will replace and a standard user cannot write to"
        )


# ------------------------------------------- nothing writes into the code, part two

# The test above pins the original defect and misses a whole family around it. It
# matches four directory names joined onto two anchor names, so a write into the
# package escapes it by being called something else or by starting somewhere else,
# and one did: arelis/ui/app.py created a "_qt_fonts" directory from
# Path(__file__).resolve().parents[1] on every launch of the window. Wrong on both
# counts, invisible in a checkout, and gitignored, so nothing ever pointed at it.
#
# What follows checks the property instead of the spelling: no path built from the
# package's own location is written to. Anchor names are still enumerated, because
# they are ours and few, but the operation is matched by what it does.

PACKAGE_ANCHORS = frozenset({"PACKAGE_ROOT", "INSTALL_PARENT", "PROJECT_ROOT"})

WRITE_METHODS = frozenset(
    {
        "mkdir",
        "touch",
        "write_text",
        "write_bytes",
        "unlink",
        "rmdir",
        "rename",
        "replace",
        "symlink_to",
        "hardlink_to",
        "chmod",
    }
)


def _is_dunder_file_path(node: ast.AST) -> bool:
    """``Path(__file__)`` -- the anchor the first version of this guard forgot."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Path"
        and any(isinstance(arg, ast.Name) and arg.id == "__file__" for arg in node.args)
    )


def _anchored_at_package(node: ast.AST) -> bool:
    """True when an expression is built from where the package itself lives.

    Walks left and down to whatever the expression is ultimately rooted in, so
    that ``PACKAGE_ROOT / "a" / "b"`` and
    ``Path(__file__).resolve().parents[1] / "c"`` both answer the same way. The
    node types are the four ways a path expression grows: joining, attribute
    access, a call, and indexing into ``.parents``.
    """
    seen = 0
    while seen < 64:  # A malformed nest must not spin forever in a test.
        seen += 1
        if _is_dunder_file_path(node):
            return True
        if isinstance(node, ast.Name):
            return node.id in PACKAGE_ANCHORS
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            node = node.left
        elif isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Subscript):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            return False
    return False


def _opens_for_writing(call: ast.Call) -> bool:
    """``.open()`` is only a write when the mode says so."""
    modes = [arg for arg in call.args if isinstance(arg, ast.Constant)]
    modes += [
        kw.value
        for kw in call.keywords
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant)
    ]
    return any(
        isinstance(mode.value, str) and any(ch in mode.value for ch in "wax+")
        for mode in modes
    )


def package_anchored_writes(source: str, filename: str) -> list[str]:
    """Every write in one module that lands on a package-relative path.

    Names assigned a package-anchored path are tracked, because the defect this
    exists for was two statements rather than one: the path was bound to a local
    and the mkdir happened on the local. A single-expression check reads the first
    line and approves it.
    """
    tree = ast.parse(source, filename=filename)

    anchored_names: set[str] = set()
    for node in ast.walk(tree):
        value = getattr(node, "value", None)
        if value is None or not _anchored_at_package(value):
            continue
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                anchored_names.add(target.id)

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method == "open":
            if not _opens_for_writing(node):
                continue
        elif method not in WRITE_METHODS:
            continue
        receiver = node.func.value
        if _anchored_at_package(receiver) or (
            isinstance(receiver, ast.Name) and receiver.id in anchored_names
        ):
            findings.append(f"  {filename}:{node.lineno}: .{method}() on a package path")
    return findings


def test_no_module_writes_to_a_path_built_from_the_package_location() -> None:
    """Read-only assets live beside the code; anything written does not."""
    hits: list[str] = []
    for path in sorted(paths.PACKAGE_ROOT.rglob("*.py")):
        if path.name == "paths.py":
            continue
        rel = f"arelis/{path.relative_to(paths.PACKAGE_ROOT).as_posix()}"
        hits.extend(package_anchored_writes(path.read_text(encoding="utf-8"), rel))
    assert not hits, (
        "Something writes into the installed package. Once installed that "
        "directory may be read-only, and an update replaces it wholesale. Use "
        "arelis.paths.state_dir(), logs_dir(), outputs_dir(), models_dir() or "
        "cache_dir():\n" + "\n".join(hits)
    )


# ------------------------------------- the two directories that were in the package


def test_the_qt_font_directory_is_not_inside_the_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Created on every launch of the window, and it used to land in arelis/.

    Qt's basic font database warns about a font directory that is not there, so an
    empty one is made and pointed at. That mkdir was unguarded and ran before the
    QApplication existed, which means on an install where the package is read-only
    the failure is not a missing font — it is a program that never draws a window.
    """
    from arelis.ui.theme import qt_font_directory

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    resolved = qt_font_directory()

    assert resolved.is_dir(), "Qt warns unless the directory it is given exists"
    assert not resolved.is_relative_to(paths.PACKAGE_ROOT)
    assert resolved.is_relative_to(tmp_path)
    assert not list(resolved.iterdir()), (
        "the fonts are registered from the package with addApplicationFont; this "
        "directory exists to be found, not to be read"
    )


# ----------------------------------------------------- one user, then two


def test_two_accounts_get_state_that_does_not_overlap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """This is what stands in place of an account system, so it gets a test.

    Arelis has no logins and no notion of a user, by design: Windows already
    separates accounts and reimplementing that would add a password to protect
    data the operating system was already protecting. The claim that therefore
    needs proving is that two accounts resolve to two unrelated trees, with
    neither reachable from the other by walking upwards -- a nested pair would
    leak one user's contacts into the other's backup or index.

    What this cannot test, and what is therefore an assumption rather than a
    guarantee we make: that Windows denies one account read access to another's
    LOCALAPPDATA. That is the operating system's promise, it holds by default for
    separate profiles, and it is the reason this design is sound. A machine where
    two people share one Windows login is a machine where they share everything,
    and no code here can change that.
    """
    first = tmp_path / "alice" / "AppData" / "Local" / "Arelis"
    second = tmp_path / "bob" / "AppData" / "Local" / "Arelis"

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(first))
    alice = {fn.__name__: fn() for fn in MUTABLE_RESOLVERS}

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(second))
    bob = {fn.__name__: fn() for fn in MUTABLE_RESOLVERS}

    for name in alice:
        assert alice[name] != bob[name], f"{name} is shared between two accounts"
        assert alice[name] not in bob[name].parents
        assert bob[name] not in alice[name].parents

    # And the files actually land apart, not merely the paths.
    for who in (alice, bob):
        paths.ensure(who["state_dir"])
        (who["state_dir"] / "contacts.yaml").write_text("contacts: {}\n", encoding="utf-8")
    assert (alice["state_dir"] / "contacts.yaml").read_text(encoding="utf-8") == (
        "contacts: {}\n"
    )
    assert len(list((tmp_path / "alice").rglob("contacts.yaml"))) == 1
    assert len(list((tmp_path / "bob").rglob("contacts.yaml"))) == 1


# ------------------------------------------------------------- resolution order


# --------------------------------------------------------------- first run


# --------------------------------------------------------- the workspace root


# ------------------------------------------------------------------ platform


