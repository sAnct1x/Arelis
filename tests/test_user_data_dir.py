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
import os
import sys
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


def test_no_module_builds_a_mutable_path_from_the_install_directory() -> None:
    """A static rule, because the runtime one cannot see code that never ran.

    Thirty-odd modules were migrated by hand. The ones covered by a test are
    proven; the risk is the next module somebody adds, reaching for the nearest
    example and reintroducing the original defect in a file no test imports. The
    four directory names below are the mutable ones, and none of them may be
    joined onto the install parent anywhere in the package.
    """
    package_files = sorted(paths.PACKAGE_ROOT.rglob("*.py"))
    assert package_files, "found no package sources to check"

    forbidden = [
        f'{anchor} / "{name}"'
        for anchor in ("PROJECT_ROOT", "INSTALL_PARENT")
        for name in ("data", "logs", "outputs", "models")
    ]
    hits = []
    for path in package_files:
        if path.name == "paths.py":
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if any(pattern in line for pattern in forbidden):
                rel = path.relative_to(paths.PACKAGE_ROOT).as_posix()
                hits.append(f"  arelis/{rel}:{line_no}")
    assert not hits, (
        "A mutable directory is being built from the install location. Use "
        "arelis.paths.state_dir(), logs_dir(), outputs_dir() or models_dir():\n"
        + "\n".join(hits)
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


def test_the_guard_catches_the_defect_it_was_written_for() -> None:
    """A guard nobody has seen fail is a guard nobody knows works.

    This is the code that was in arelis/ui/app.py, kept verbatim as the fixture
    rather than a paraphrase, because the point is that this exact shape got past
    the previous check. Two statements, an anchor of Path(__file__) rather than a
    named constant, and a directory name that is not one of the four mutable ones.
    """
    defect = (
        "font_dir = Path(__file__).resolve().parents[1] / '_qt_fonts'\n"
        "font_dir.mkdir(exist_ok=True)\n"
    )
    assert package_anchored_writes(defect, "arelis/ui/app.py")

    # And the read it must not be confused with: the shipped icon and the shipped
    # config are package-relative on purpose, and opening them is correct.
    reads = (
        'icon = PACKAGE_ROOT / "assets" / "arelis.ico"\n'
        'text = (PACKAGE_ROOT / "config" / "default.yaml").read_text()\n'
        'handle = (PACKAGE_ROOT / "persona" / "core.md").open("r")\n'
    )
    assert not package_anchored_writes(reads, "arelis/example.py")


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


def test_playwright_downloads_land_under_the_data_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Several hundred megabytes of browser belongs where a user can find it.

    Not a correctness fix -- Playwright's own default is already per-user and
    writable -- but a download this large in a directory nobody associates with
    Arelis is the kind of thing discovered years later by someone hunting for disk
    space.
    """
    from arelis.browser.launch import browsers_path, pin_browsers_path

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    pin_browsers_path()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers_path())
    assert browsers_path().is_relative_to(tmp_path)
    assert not browsers_path().is_relative_to(paths.PACKAGE_ROOT)


def test_a_chosen_browsers_path_is_not_overruled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Somebody who pointed this at another drive had a reason."""
    from arelis.browser.launch import pin_browsers_path

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", r"D:\browsers")
    pin_browsers_path()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == r"D:\browsers"


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


def test_the_override_wins_over_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A test that touched a real profile directory would be a test that lost data."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "elsewhere"))
    assert paths.user_data_dir() == tmp_path / "elsewhere"


def test_resolve_model_path_reuses_installed_weights(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A checkout with an empty models/ folder still speaks from the published copy."""
    checkout = tmp_path / "checkout"
    published = tmp_path / "published"
    voice = published / "models" / "piper" / "jenny.onnx"
    voice.parent.mkdir(parents=True)
    voice.write_bytes(b"onnx")
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(checkout))
    monkeypatch.setattr(paths, "published_data_dir", lambda: published)
    found = paths.resolve_model_path("models/piper/jenny.onnx")
    assert found == voice.resolve()
    missing = paths.resolve_model_path("models/piper/missing.onnx")
    assert missing == (checkout / "models" / "piper" / "missing.onnx").resolve()


def test_an_empty_override_is_ignored_rather_than_obeyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset variable and one set to nothing are the same intention.

    Shell scripts export empty strings by accident constantly. Treating that as
    "write to the current directory" would scatter state wherever Arelis was
    launched from.
    """
    monkeypatch.setenv(paths.DATA_DIR_ENV, "   ")
    assert paths.user_data_dir() != Path("   ")
    assert paths.user_data_dir().is_absolute()


def test_a_checkout_keeps_its_own_data_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A developer's history must not move because production paths changed.

    This repository has months of real contacts, memory and settings in its own
    data/. If the migration had redirected a checkout to %LOCALAPPDATA% it would
    have looked, on the machine where it was written, exactly like every one of
    those records being deleted.
    """
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    assert paths.is_source_checkout(), "these tests run from a checkout"
    assert paths.user_data_dir() == paths.INSTALL_PARENT
    assert paths.state_dir() == paths.INSTALL_PARENT / "data"


def test_an_install_is_told_apart_from_a_checkout_by_two_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """pyproject.toml alone was not enough to decide this.

    Someone can pip install Arelis into a virtualenv inside their own project,
    which has a pyproject.toml of its own. Treating that as a checkout would send
    their contacts into an unrelated source tree, and later into that project's
    git status. tests/ is not packaged into a wheel, so requiring both makes the
    check safe in the direction that matters.
    """
    fake_install = tmp_path / "site-packages" / "arelis"
    fake_install.mkdir(parents=True)
    (tmp_path / "site-packages" / "pyproject.toml").write_text("", encoding="utf-8")

    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    assert not paths.is_source_checkout()


# --------------------------------------------------------------- first run


def test_nothing_needs_to_exist_before_the_first_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """There is no installer yet, and there should not need to be one.

    Directories are created on demand. A user who deletes a folder to reclaim
    disk space should get it back on next launch rather than a stack trace, and
    onboarding will later depend on this same path working from nothing.
    """
    root = tmp_path / "never-created"
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(root))
    assert not root.exists()
    for resolve in MUTABLE_RESOLVERS:
        created = paths.ensure(resolve())
        assert created.is_dir()


def test_ensure_is_safe_to_call_on_a_directory_that_already_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Called on every launch, so the second launch must not be an error."""
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    assert paths.ensure(paths.state_dir()) == paths.state_dir()
    assert paths.ensure(paths.state_dir()).is_dir()


# --------------------------------------------------------- the workspace root


def test_the_default_workspace_is_a_named_folder_not_the_whole_of_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Blast radius. The workspace is what a language model may delete within.

    Defaulting it to Documents would hand a model write access to everything a
    person owns on first launch, and one bad tool call would be unrecoverable and
    entirely our fault. "." was worse still: it resolved to the install
    directory, so the model's sandbox was the program.
    """
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home" / "Documents").mkdir(parents=True)

    root = paths.default_workspace_root()
    assert root == tmp_path / "home" / "Documents" / "Arelis"
    assert root != tmp_path / "home" / "Documents"
    assert root.name == "Arelis"


def test_a_redirected_documents_folder_still_yields_a_usable_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OneDrive moves Documents, and the literal path stops existing.

    Creating Arelis/ under a Documents directory that is not the real one puts
    the user's files somewhere they will never look for them. Falling back to the
    profile root is visible and correct.
    """
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True)

    assert not (tmp_path / "home" / "Documents").exists()
    assert paths.default_workspace_root() == tmp_path / "home" / "Arelis"


def test_a_checkout_still_treats_the_repository_as_its_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise every workspace-relative test in this suite changes meaning."""
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    assert paths.default_workspace_root() == paths.INSTALL_PARENT


# ------------------------------------------------------------------ platform


@pytest.mark.skipif(sys.platform != "win32", reason="Windows resolution rules")
def test_windows_uses_local_appdata_and_not_the_roaming_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """APPDATA roams to a domain server at logon; this data must not.

    A conversation database beside gigabytes of model weights is the payload that
    makes roaming profiles fail, and none of it is meant to follow a user between
    machines anyway.
    """
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    resolved = paths.user_data_dir()
    assert resolved == tmp_path / "Local" / "Arelis"
    assert "Roaming" not in str(resolved)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows resolution rules")
def test_a_missing_local_appdata_still_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Service and stripped environments lose it, and refusing to start is worse."""
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(paths, "INSTALL_PARENT", tmp_path / "site-packages")
    monkeypatch.setenv("LOCALAPPDATA", "")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    assert paths.user_data_dir() == tmp_path / "home" / "AppData" / "Local" / "Arelis"
