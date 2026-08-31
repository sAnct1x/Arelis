"""The sandbox a language model gets must never be the program itself.

``workspace.roots`` shipped as ``["."]`` and relative entries resolved against
the directory holding the package. From a checkout that is the repository, so it
read as obviously correct. Installed, it is site-packages — inside Program Files
— which means the set of paths a model was permitted to create, edit and delete
within was Arelis's own code.

Two failure modes, and the harmless-looking one is arguably worse. A standard
user cannot write there, so file tools would fail with permission errors that
look like bugs in Arelis. An administrator can, so on those machines the tools
would work, and a single bad tool call would edit or delete part of the
installation, with the damage indistinguishable from corruption.

The tests below pin the resolution rule rather than any particular folder,
because the right answer differs between a checkout and an install and what has
to hold in both is the shape: never the install directory, never the whole of
somebody's Documents, and never silently the process working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from arelis import paths
from arelis.config import (
    _parse_workspace_roots,
    _resolve_root_path,
    ensure_package_inspect_root,
    load_config,
)


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Pretend to be an installed copy, with a home directory to own things in.

    An install is told apart from a checkout by two markers that a fake
    site-packages directory deliberately lacks, so pointing INSTALL_PARENT at an
    empty directory is enough to take the installed branch everywhere.
    """
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    monkeypatch.setattr(paths, "INSTALL_PARENT", site_packages)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    return home


def test_the_shipped_dot_root_is_not_the_install_directory(installed: Path) -> None:
    """The defect, stated as the one thing that must not be true.

    This is the assertion that would have failed before the change and the reason
    the file exists. Everything else here is about not overcorrecting.
    """
    resolved = _resolve_root_path(".")
    assert resolved != paths.INSTALL_PARENT
    assert not resolved.is_relative_to(paths.INSTALL_PARENT)
    assert not paths.PACKAGE_ROOT.is_relative_to(resolved), (
        "the model's sandbox contains the installed package"
    )


def test_the_shipped_dot_root_lands_in_a_folder_the_user_owns(
    installed: Path,
) -> None:
    resolved = _resolve_root_path(".")
    assert resolved == installed / "Documents" / "Arelis"


def test_the_default_root_is_not_the_whole_of_documents(installed: Path) -> None:
    """Blast radius, and the reason a named subfolder is worth the extra click.

    Documents itself would hand a model write and delete access to everything a
    person owns on first launch. One bad tool call would then be unrecoverable
    and entirely Arelis's fault.
    """
    resolved = _resolve_root_path(".")
    assert resolved != installed / "Documents"
    assert resolved.parent == installed / "Documents"


def test_a_relative_root_is_taken_as_user_owned_not_program_relative(
    installed: Path,
) -> None:
    """Someone writing `notes` in config means their notes, not ours."""
    resolved = _resolve_root_path("notes")
    assert resolved == installed / "Documents" / "Arelis" / "notes"


def test_an_absolute_root_is_honoured_exactly(installed: Path, tmp_path: Path) -> None:
    """The escape hatch has to keep working, or multi-project setups break.

    Anyone with real projects names them absolutely, and that must be taken at
    face value rather than reinterpreted against a default they never asked for.
    """
    elsewhere = tmp_path / "projects" / "thing"
    elsewhere.mkdir(parents=True)
    assert _resolve_root_path(str(elsewhere)) == elsewhere


def test_a_root_never_resolves_against_the_process_working_directory(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Arelis is launched from the Start menu as often as from a shell.

    If "." meant the working directory, the same config would grant a different
    sandbox depending on how the program happened to be started, and a shortcut
    with no working directory set would grant something arbitrary.
    """
    strange_cwd = tmp_path / "somewhere-else"
    strange_cwd.mkdir()
    monkeypatch.chdir(strange_cwd)
    assert _resolve_root_path(".") == installed / "Documents" / "Arelis"


def test_an_empty_roots_list_still_yields_one_usable_root(installed: Path) -> None:
    """Config with the key present but nothing under it must not mean no access.

    An empty list is what a user leaves behind after deleting a root in Settings,
    and interpreting it as "no filesystem at all" would silently disable every
    file tool with nothing on screen to explain why.
    """
    named = _parse_workspace_roots([])
    assert len(named) == 1
    assert Path(named[0]["path"]) == installed / "Documents" / "Arelis"
    assert named[0]["read_only"] is False


def test_a_checkout_keeps_resolving_roots_against_the_repository() -> None:
    """Otherwise every workspace test in this suite quietly changes meaning.

    Not a nicety: the suite has hundreds of tests that read and write through the
    workspace, and if a checkout started resolving "." to the developer's
    Documents folder they would begin operating on real files outside the
    repository.
    """
    assert paths.is_source_checkout(), "these tests run from a checkout"
    assert _resolve_root_path(".") == paths.INSTALL_PARENT


def test_a_redirected_documents_folder_still_yields_a_root_off_the_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OneDrive moves Documents and the literal path stops existing.

    Creating Arelis/ under a Documents directory that is not the real one puts
    the user's files somewhere they will never think to look.
    """
    home = tmp_path / "home"
    home.mkdir()
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    monkeypatch.setattr(paths, "INSTALL_PARENT", site_packages)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert not (home / "Documents").exists()
    assert _resolve_root_path(".") == home / "Arelis"


def test_installed_adds_a_read_only_inspect_root_on_the_package(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Installed, she can read her own package and must not write it."""
    package = tmp_path / "site-packages" / "arelis"
    package.mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKAGE_ROOT", package)

    named = ensure_package_inspect_root(_parse_workspace_roots(["."]))
    by_path = {Path(e["path"]).resolve(): e for e in named}

    inspect = by_path[package.resolve()]
    assert inspect["read_only"] is True
    assert inspect["name"] == "source"

    default = by_path[(installed / "Documents" / "Arelis").resolve()]
    assert default["read_only"] is False

    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        yaml.dump({"workspace": {"roots": ["."]}, "persona_file": "persona/arelis.md"}),
        encoding="utf-8",
    )
    loaded = load_config(cfg)["workspace"]["named_roots"]
    loaded_by_path = {Path(e["path"]).resolve(): e for e in loaded}
    assert loaded_by_path[package.resolve()]["read_only"] is True
    assert loaded_by_path[(installed / "Documents" / "Arelis").resolve()]["read_only"] is False


def test_installed_inspect_root_renames_when_source_is_taken(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "site-packages" / "arelis"
    package.mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKAGE_ROOT", package)

    named = [
        {"name": "source", "path": str((installed / "Documents" / "Arelis").resolve()), "read_only": False},
    ]
    result = ensure_package_inspect_root(named)
    inspect = next(e for e in result if Path(e["path"]).resolve() == package.resolve())
    assert inspect["name"] == "arelis-source"
    assert inspect["read_only"] is True


def test_installed_forces_read_only_when_the_package_is_already_a_root(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "site-packages" / "arelis"
    package.mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKAGE_ROOT", package)

    named = [
        {"name": "Arelis", "path": str((installed / "Documents" / "Arelis").resolve()), "read_only": False},
        {"name": "pkg", "path": str(package.resolve()), "read_only": False},
    ]
    result = ensure_package_inspect_root(named)
    assert len(result) == 2
    pkg = next(e for e in result if Path(e["path"]).resolve() == package.resolve())
    assert pkg["read_only"] is True
    docs = next(
        e for e in result if Path(e["path"]).resolve() == (installed / "Documents" / "Arelis").resolve()
    )
    assert docs["read_only"] is False


def test_checkout_does_not_add_a_second_inspect_root() -> None:
    """On a source checkout, "." already is the repo. Do not stack another."""
    assert paths.is_source_checkout(), "these tests run from a checkout"
    before = [
        {"name": "repo", "path": str(paths.INSTALL_PARENT.resolve()), "read_only": False},
    ]
    after = ensure_package_inspect_root(before)
    assert after is before
    assert after == before
