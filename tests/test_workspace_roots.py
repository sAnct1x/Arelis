from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from arelis import paths
from arelis.config import load_config
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.workspace import (
    UNSAFE_WINDOWS_PATH_MSG,
    AmbiguousPathError,
    RootEntry,
    WorkspaceRoots,
    is_unsafe_windows_path,
)


def _two_projects(tmp_path: Path) -> WorkspaceRoots:
    a = tmp_path / "arelis"
    b = tmp_path / "interferometer"
    a.mkdir()
    b.mkdir()
    return WorkspaceRoots(
        [
            RootEntry(name="arelis", path=a.resolve()),
            RootEntry(name="interferometer", path=b.resolve()),
        ]
    )


def test_external_read_grant_allows_absolute_read(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret-ish", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])

    with pytest.raises(PermissionError):
        ws.resolve(str(outside))
    assert ws.grant_external_read(outside) == outside.resolve()
    hit = ws.resolve_read(str(outside))
    assert hit.path == outside.resolve()
    assert hit.root_name == "external"
    # Writes still sandboxed.
    with pytest.raises(PermissionError):
        ws.resolve(str(outside), for_create=True)
    ws.clear_external_reads()
    with pytest.raises(PermissionError):
        ws.resolve_read(str(outside))


def _directory_is_case_sensitive(directory: Path) -> bool:
    """True when two spellings of one name are two files.

    APFS and NTFS are usually case-insensitive, so Notes.TXT and notes.txt
    are the same directory entry. Path equality still compares the spelling.
    """
    probe = directory / "._ArelisCaseProbe"
    other = directory / "._areliscaseprobe"
    probe.write_text("a", encoding="utf-8")
    try:
        if not other.exists():
            return True
        try:
            return not os.path.samefile(probe, other)
        except OSError:
            return True
    finally:
        probe.unlink(missing_ok=True)
        other.unlink(missing_ok=True)


def test_bare_path_ambiguous_refuses(tmp_path: Path) -> None:
    ws = _two_projects(tmp_path)
    (ws.roots[0].path / "notes.txt").write_text("a", encoding="utf-8")
    (ws.roots[1].path / "notes.txt").write_text("b", encoding="utf-8")
    with pytest.raises(AmbiguousPathError, match="more than one project"):
        ws.resolve("notes.txt")


def _installed_package_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, dict]:
    """Installed copy: Documents/Arelis writable, package inspectable."""
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    site_packages = tmp_path / "site-packages"
    package = site_packages / "arelis"
    package.mkdir(parents=True)
    (package / "inspect_me.py").write_text("# shipped\n", encoding="utf-8")
    monkeypatch.setattr(paths, "INSTALL_PARENT", site_packages)
    monkeypatch.setattr(paths, "PACKAGE_ROOT", package)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(
        yaml.dump({"workspace": {"roots": ["."]}, "persona_file": "persona/arelis.md"}),
        encoding="utf-8",
    )
    return package, load_config(cfg)


def test_installed_package_inspect_root_is_readable_not_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package, data = _installed_package_roots(monkeypatch, tmp_path)
    ws = WorkspaceRoots.from_config(data)

    hit = ws.resolve_read(str(package / "inspect_me.py"))
    assert hit.path == (package / "inspect_me.py").resolve()
    assert hit.root_name in ("source", "arelis-source")

    with pytest.raises(PermissionError, match="read-only"):
        ws.resolve(str(package / "inspect_me.py"), for_write=True)
    with pytest.raises(PermissionError, match="read-only"):
        ws.resolve(str(package / "new.py"), for_create=True)

    docs = tmp_path / "home" / "Documents" / "Arelis"
    created = ws.resolve("fresh.txt", for_create=True)
    assert created.path == (docs / "fresh.txt").resolve()
    assert created.root_name != hit.root_name


_UNSAFE_WINDOWS_PATHS = ('\\\\evil\\share\\x.txt', '\\\\?\\UNC\\evil\\share')

_SAFE_WINDOWS_PATHS = (
    "notes.txt",
    r"C:\Users\someone\doc.txt",
    r"C:/Users/someone/doc.txt",
    "outputs/documents/x.md",
    r"file:///C:/Users/someone/doc.txt",
)


def _track_path_fs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Record Path.resolve / exists / stat / open so UNC checks stay pre-FS."""
    calls: list[tuple[str, str]] = []
    real_resolve = Path.resolve
    real_exists = Path.exists
    real_stat = Path.stat
    real_open = Path.open

    def track_resolve(self: Path, *args, **kwargs):
        calls.append(("resolve", str(self)))
        return real_resolve(self, *args, **kwargs)

    def track_exists(self: Path, *args, **kwargs):
        calls.append(("exists", str(self)))
        return real_exists(self, *args, **kwargs)

    def track_stat(self: Path, *args, **kwargs):
        calls.append(("stat", str(self)))
        return real_stat(self, *args, **kwargs)

    def track_open(self: Path, *args, **kwargs):
        calls.append(("open", str(self)))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", track_resolve)
    monkeypatch.setattr(Path, "exists", track_exists)
    monkeypatch.setattr(Path, "stat", track_stat)
    monkeypatch.setattr(Path, "open", track_open)
    return calls


@pytest.mark.parametrize("raw", _UNSAFE_WINDOWS_PATHS)
def test_resolve_refuses_unc_before_filesystem(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    ws = WorkspaceRoots.from_paths([str(root)])
    calls = _track_path_fs(monkeypatch)
    with pytest.raises(PermissionError, match="network location"):
        ws.resolve(raw)
    with pytest.raises(PermissionError, match="network location"):
        ws.resolve_read(raw)
    assert calls == []
    assert ws.grant_external_read(raw) is None
    assert calls == []
    assert not ws.has_external_read(raw)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", _UNSAFE_WINDOWS_PATHS)
async def test_workspace_tool_refuses_unc_without_fs(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.txt").write_text("safe", encoding="utf-8")
    ws = WorkspaceRoots.from_paths([str(root)])
    tool = CodeWorkspaceTool(ws)
    calls = _track_path_fs(monkeypatch)
    denied = await tool.run(action="read", path=raw)
    assert not denied.ok
    assert UNSAFE_WINDOWS_PATH_MSG in denied.output
    assert calls == []
    wrote = await tool.run(action="write", path=raw, content="nope")
    assert not wrote.ok
    assert UNSAFE_WINDOWS_PATH_MSG in wrote.output
    assert calls == []
    # Drive-letter and relative paths still resolve after the guard.
    hit = ws.resolve("ok.txt")
    assert hit.path == (root / "ok.txt").resolve()
    drive = ws.resolve(str((root / "ok.txt").resolve()))
    assert drive.path == (root / "ok.txt").resolve()


def _boom_fs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise if resolve/exists/is_file/stat run on a UNC probe path."""
    real_resolve = Path.resolve
    real_exists = Path.exists
    real_is_file = Path.is_file
    real_stat = Path.stat
    real_os_stat = os.stat

    def probe(text: str) -> bool:
        return (
            is_unsafe_windows_path(text)
            or "evil" in text
            or "??" in text
            or r"\server" in text.replace("/", "\\")
        )

    def boom_path(label: str, orig):
        def wrapped(self: Path, *args, **kwargs):
            if probe(str(self)):
                raise AssertionError(f"{label} touched {self}")
            return orig(self, *args, **kwargs)

        return wrapped

    def boom_os_stat(path, *args, **kwargs):
        if probe(str(path)):
            raise AssertionError(f"os.stat touched {path}")
        return real_os_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", boom_path("resolve", real_resolve))
    monkeypatch.setattr(Path, "exists", boom_path("exists", real_exists))
    monkeypatch.setattr(Path, "is_file", boom_path("is_file", real_is_file))
    monkeypatch.setattr(Path, "stat", boom_path("stat", real_stat))
    monkeypatch.setattr(os, "stat", boom_os_stat)


_ENTRY_UNC = (
    r"\\evil\share\x.txt",
    r"\\/server/share",
    r"\??/UNC/x",
)


