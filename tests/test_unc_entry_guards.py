"""UNC and device-path guards at the entry points added in #58.

A normal local file still resolves. The unsafe strings are refused before any
filesystem call: the tripwire raises if resolve, stat, or open sees one.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from arelis.browser.files import resolve_upload_path
from arelis.core.email_complete import resolve_attach_path
from arelis.core.look import frame_sha256
from arelis.desk import _normalize_abs
from arelis.local_open import open_local_file, open_local_file_as, reveal_local_file
from arelis.tools.image_meta import read_named_sidecar
from arelis.workspace import UNSAFE_WINDOWS_PATH_MSG, WorkspaceRoots, is_unsafe_windows_path

_UNC = (
    r"\\evil\share\x",
    r"\\/evil/share",
    r"\\?\UNC\evil\share\x",
)
_DRIVE = r"C:\Users\example\note.txt"


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
    real_stat = Path.stat
    real_open = Path.open
    real_read_bytes = Path.read_bytes
    real_read_text = Path.read_text
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
    monkeypatch.setattr(Path, "stat", wrap("stat", real_stat))
    monkeypatch.setattr(Path, "open", wrap("open", real_open))
    monkeypatch.setattr(Path, "read_bytes", wrap("read_bytes", real_read_bytes))
    monkeypatch.setattr(Path, "read_text", wrap("read_text", real_read_text))
    monkeypatch.setattr(os, "stat", boom_os_stat)


def _plant_attach_decoy(raw: str, data_root: Path) -> None:
    """A leaf the unguarded attach lookup would return, when the OS allows the name."""
    name = Path(raw).name
    if not name or name in {".", ".."} or os.sep in name:
        return
    docs = data_root / "outputs" / "documents"
    dest = docs / name
    try:
        dest.relative_to(docs)
    except ValueError:
        return
    docs.mkdir(parents=True, exist_ok=True)
    dest.write_text("decoy", encoding="utf-8")


def _plant_frame_decoy(raw: str, data_root: Path) -> None:
    """Bytes an unguarded frame_sha256 would hash, for a relative path under the data root."""
    candidate = Path(raw)
    if candidate.is_absolute():
        return
    dest = data_root / candidate
    try:
        dest.relative_to(data_root)
    except ValueError:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"decoy-frame")


def _capture_openers(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def popen(args, *args_, **kwargs):
        calls.append(tuple(args))

        class Proc:
            pass

        return Proc()

    def startfile(path, operation="open"):
        calls.append((str(path), operation))

    monkeypatch.setattr("arelis.local_open.subprocess.Popen", popen)
    monkeypatch.setattr("arelis.local_open.os.startfile", startfile, raising=False)
    return calls


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_resolve_upload_path_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    hit, err = resolve_upload_path(raw)
    assert hit is None
    assert err == UNSAFE_WINDOWS_PATH_MSG


def test_resolve_upload_path_allows_a_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    note = out / "example.txt"
    note.write_text("hi", encoding="utf-8")
    monkeypatch.setattr("arelis.browser.files.outputs_dir", lambda: out)
    hit, err = resolve_upload_path(str(note))
    assert err == ""
    assert hit == note.resolve()

    missed, miss_err = resolve_upload_path(_DRIVE)
    assert missed is None
    assert miss_err != UNSAFE_WINDOWS_PATH_MSG
    assert "Not a file" in miss_err


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_resolve_attach_path_refuses_unc(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    _plant_attach_decoy(raw, tmp_path)
    root = tmp_path / "proj"
    root.mkdir()
    workspace = WorkspaceRoots.from_paths([str(root)])
    _block_unsafe_fs(monkeypatch)
    assert resolve_attach_path(raw) == ""
    assert resolve_attach_path(raw, workspace=workspace) == ""


def test_resolve_attach_path_allows_a_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    docs = tmp_path / "outputs" / "documents"
    docs.mkdir(parents=True)
    note = docs / "example.txt"
    note.write_text("hello", encoding="utf-8")
    assert resolve_attach_path(str(note)) == str(note.resolve())
    root = tmp_path / "proj"
    root.mkdir()
    kept = root / "kept.txt"
    kept.write_text("kept", encoding="utf-8")
    workspace = WorkspaceRoots.from_paths([str(root)])
    assert resolve_attach_path(str(kept), workspace=workspace) == str(kept.resolve())


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_frame_sha256_refuses_unc_without_reading(
    raw: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    _plant_frame_decoy(raw, tmp_path)
    _block_unsafe_fs(monkeypatch)
    digest = frame_sha256(raw)
    assert digest == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert digest != hashlib.sha256(b"decoy-frame").hexdigest()


def test_frame_sha256_hashes_a_local_file(tmp_path: Path) -> None:
    note = tmp_path / "example.txt"
    payload = b"local-bytes"
    note.write_bytes(payload)
    assert frame_sha256(str(note)) == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_normalize_abs_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    assert _normalize_abs(raw) == ""


def test_normalize_abs_keeps_a_drive_letter_and_a_real_file(tmp_path: Path) -> None:
    note = tmp_path / "example.txt"
    note.write_text("hi", encoding="utf-8")
    assert _normalize_abs(str(note)) == str(note.resolve())
    drive = _normalize_abs(_DRIVE)
    assert drive
    assert "example" in drive
    assert "note.txt" in drive


@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_read_named_sidecar_refuses_unc(raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _block_unsafe_fs(monkeypatch)
    assert read_named_sidecar(raw) == {}


def test_read_named_sidecar_reads_a_local_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    folder = tmp_path / "outputs" / "images"
    folder.mkdir(parents=True)
    png = folder / "example.png"
    png.write_bytes(b"png")
    png.with_suffix(".json").write_text(
        json.dumps({"prompt": "a fox", "seed": 3}),
        encoding="utf-8",
    )
    data = read_named_sidecar(str(png))
    assert data["prompt"] == "a fox"
    assert data["seed"] == 3
    assert read_named_sidecar("outputs/images/example.png")["seed"] == 3


@pytest.mark.parametrize(
    "opener",
    [open_local_file, open_local_file_as, reveal_local_file],
    ids=["open", "open-as", "reveal"],
)
@pytest.mark.parametrize("raw", _UNC, ids=["unc", "mixed-slash", "device-unc"])
def test_local_open_refuses_unc(opener, raw: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_openers(monkeypatch)
    _block_unsafe_fs(monkeypatch)
    with pytest.raises(PermissionError, match="network location"):
        opener(raw)
    assert calls == []


@pytest.mark.parametrize(
    "opener",
    [open_local_file, open_local_file_as, reveal_local_file],
    ids=["open", "open-as", "reveal"],
)
def test_local_open_drive_letter_is_a_missing_file(opener, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_openers(monkeypatch)
    with pytest.raises(FileNotFoundError):
        opener(_DRIVE)
    assert calls == []


@pytest.mark.parametrize(
    "opener",
    [open_local_file, open_local_file_as, reveal_local_file],
    ids=["open", "open-as", "reveal"],
)
def test_local_open_reaches_the_opener_for_a_real_file(
    opener, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note = tmp_path / "example.txt"
    note.write_text("hi", encoding="utf-8")
    calls = _capture_openers(monkeypatch)
    opener(note)
    assert calls
    flat = " ".join(str(part) for call in calls for part in call)
    resolved = str(note.resolve())
    assert resolved in flat or str(note.resolve().parent) in flat or note.name in flat
    if sys.platform != "win32" and opener is reveal_local_file:
        assert str(note.resolve().parent) in flat
