"""UNC and device-path guards for the entry points named on issue 92.

A normal local file still works. The unsafe strings are refused before any
filesystem call: the tripwire raises if resolve, stat, or open sees one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from arelis.core.document_refs import _usable_file
from arelis.desktop.sanctuary import is_denied_file_path
from arelis.look_scratch import (
    clear_look_pending,
    forget_look_scratch,
    is_look_scratch,
    note_look_scratch,
    prune_look_scratch,
)
from arelis.tools.comfy_lifecycle import discover_comfy, resolve_launch
from arelis.workspace import is_unsafe_windows_path

_UNC = (
    r"\\evil\share\x",
    r"\\/evil/share",
    r"\\?\UNC\evil\share\x",
)


def _unsafe_text(text: str) -> bool:
    if is_unsafe_windows_path(text):
        return True
    folded = text.replace("/", "\\")
    return "evil" in folded or "??" in text


def _block_unsafe_fs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test instead of touching a UNC or device path."""
    real_resolve = Path.resolve
    real_exists = Path.exists
    real_is_file = Path.is_file
    real_is_dir = Path.is_dir
    real_stat = Path.stat
    real_open = Path.open
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text
    real_unlink = Path.unlink
    real_iterdir = Path.iterdir
    real_mkdir = Path.mkdir
    real_os_stat = os.stat

    def wrap(label: str, orig):
        def wrapped(self: Path, *args, **kwargs):
            if _unsafe_text(str(self)):
                raise AssertionError(f"{label} touched {self}")
            return orig(self, *args, **kwargs)

        return wrapped

    def boom_os_stat(path, *args, **kwargs):
        if _unsafe_text(str(path)):
            raise AssertionError(f"os.stat touched {path}")
        return real_os_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", wrap("resolve", real_resolve))
    monkeypatch.setattr(Path, "exists", wrap("exists", real_exists))
    monkeypatch.setattr(Path, "is_file", wrap("is_file", real_is_file))
    monkeypatch.setattr(Path, "is_dir", wrap("is_dir", real_is_dir))
    monkeypatch.setattr(Path, "stat", wrap("stat", real_stat))
    monkeypatch.setattr(Path, "open", wrap("open", real_open))
    monkeypatch.setattr(Path, "read_bytes", wrap("read_bytes", real_read_bytes))
    monkeypatch.setattr(Path, "read_text", wrap("read_text", real_read_text))
    monkeypatch.setattr(Path, "unlink", wrap("unlink", real_unlink))
    monkeypatch.setattr(Path, "iterdir", wrap("iterdir", real_iterdir))
    monkeypatch.setattr(Path, "mkdir", wrap("mkdir", real_mkdir))
    monkeypatch.setattr(os, "stat", boom_os_stat)


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_usable_file_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    assert _usable_file(raw) == ""


def test_usable_file_reads_a_local_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    note = tmp_path / "example.txt"
    note.write_text("hi", encoding="utf-8")
    _block_unsafe_fs(monkeypatch)
    assert Path(_usable_file(str(note))) == note.resolve()
    assert _usable_file(str(tmp_path / "missing.txt")) == ""


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_denied_file_path_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    assert is_denied_file_path(raw) is True


def test_denied_file_path_allows_a_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = tmp_path / "example.txt"
    note.write_text("hi", encoding="utf-8")
    _block_unsafe_fs(monkeypatch)
    assert is_denied_file_path(note) is False


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_look_scratch_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_look_pending()
    _block_unsafe_fs(monkeypatch)
    assert is_look_scratch(raw) is False
    note_look_scratch(raw)
    assert forget_look_scratch(raw) is False
    assert prune_look_scratch(directory=Path(raw)) == 0
    clear_look_pending()


def test_look_scratch_still_forgets_a_local_still(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr("arelis.look_scratch.images_dir", lambda: images)
    clear_look_pending()
    shot = images / "browser_example.png"
    shot.write_bytes(b"png")
    _block_unsafe_fs(monkeypatch)
    assert is_look_scratch(shot) is True
    note_look_scratch(shot)
    assert forget_look_scratch(shot) is True
    assert not shot.exists()
    clear_look_pending()


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_discover_comfy_skips_unc(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ComfyUI"
    root.mkdir()
    (root / "main.py").write_text("# local\n", encoding="utf-8")
    _block_unsafe_fs(monkeypatch)
    assert discover_comfy(roots=[raw]) is None
    assert discover_comfy(roots=[raw, root]) == root


def test_resolve_launch_uses_a_local_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main.py"
    main.write_text("# local\n", encoding="utf-8")
    _block_unsafe_fs(monkeypatch)
    resolved = resolve_launch(
        launch_command="",
        launch_cwd=str(tmp_path),
        comfy_url="http://127.0.0.1:8188",
    )
    assert resolved is not None
    argv, cwd = resolved
    assert Path(cwd).resolve() == tmp_path.resolve()
    assert "main.py" in " ".join(argv)
    assert "8188" in " ".join(argv)


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_resolve_launch_refuses_unc_paths(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main = tmp_path / "main.py"
    main.write_text("# local\n", encoding="utf-8")
    _block_unsafe_fs(monkeypatch)
    assert (
        resolve_launch(
            launch_command="",
            launch_cwd=raw,
            comfy_url="http://127.0.0.1:8188",
        )
        is None
    )
    assert (
        resolve_launch(
            launch_command=raw,
            launch_cwd=str(tmp_path),
            comfy_url="http://127.0.0.1:8188",
        )
        is None
    )
