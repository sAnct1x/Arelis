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
