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

_UNC = ('\\\\evil\\share\\x', '\\\\/evil/share')


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


@pytest.mark.parametrize("raw", _UNC, ids=['unc', 'mixed-slash'])
def test_usable_file_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    assert _usable_file(raw) == ""


@pytest.mark.parametrize("raw", _UNC, ids=['unc', 'mixed-slash'])
def test_denied_file_path_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    assert is_denied_file_path(raw) is True


@pytest.mark.parametrize("raw", _UNC, ids=['unc', 'mixed-slash'])
def test_look_scratch_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_look_pending()
    _block_unsafe_fs(monkeypatch)
    assert is_look_scratch(raw) is False
    note_look_scratch(raw)
    assert forget_look_scratch(raw) is False
    assert prune_look_scratch(directory=Path(raw)) == 0
    clear_look_pending()


@pytest.mark.parametrize("raw", _UNC, ids=['unc', 'mixed-slash'])
def test_discover_comfy_skips_unc(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ComfyUI"
    root.mkdir()
    (root / "main.py").write_text("# local\n", encoding="utf-8")
    _block_unsafe_fs(monkeypatch)
    assert discover_comfy(roots=[raw]) is None
    assert discover_comfy(roots=[raw, root]) == root


@pytest.mark.parametrize("raw", _UNC, ids=['unc', 'mixed-slash'])
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
