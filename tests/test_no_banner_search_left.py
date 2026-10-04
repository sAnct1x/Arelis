"""Guard: geo-indexed open-port camera search is gone from the tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.config import load_config
from arelis.earth.secrets import earth_block, earth_secret

_NEEDLE = "sho" + "dan"
_EXTS = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".json",
    ".ps1",
    ".iss",
    ".cfg",
}
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
# Release history stays as written; a future notes file may name the removal.
_HISTORY_ALLOW = ("docs/whats-new.md", "docs/releases/")
_THIS_NAME = Path(__file__).name
_REPO = Path(__file__).resolve().parents[1]
# 841 matching files on 8de3f6f; 200 is well under that.
_MIN_FILES = 200


def _is_history(rel: str) -> bool:
    if rel == _HISTORY_ALLOW[0]:
        return True
    return rel == "docs/releases" or rel.startswith(_HISTORY_ALLOW[1])


def _scan(roots: list[Path], base: Path) -> tuple[list[str], int]:
    hits: list[str] = []
    visited = 0
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                files.append(path)
    for path in files:
        if path.suffix.lower() not in _EXTS:
            continue
        if path.name == _THIS_NAME:
            continue
        visited += 1
        try:
            rel = path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            rel = path.name
        if _is_history(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        needle = _NEEDLE.lower()
        for i, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append(f"{rel}:{i}")
    return hits, visited


def _repo_roots() -> list[Path]:
    roots = [
        _REPO / "arelis",
        _REPO / "tests",
        _REPO / "docs",
        _REPO / ".github",
        _REPO / "README.md",
        _REPO / "pyproject.toml",
        _REPO / "data" / "secrets.example.yaml",
    ]
    installer = _REPO / "win-installer"
    if installer.is_dir():
        roots.append(installer)
    return roots


def test_banner_search_word_is_gone() -> None:
    hits, visited = _scan(_repo_roots(), _REPO)
    assert visited >= _MIN_FILES, f"scan too thin: {visited} files"
    assert hits == [], "left behind:\n" + "\n".join(hits)


def test_scan_helper_reports_a_planted_hit(tmp_path: Path) -> None:
    planted = tmp_path / "arelis" / "plant.py"
    planted.parent.mkdir()
    planted.write_text(f"label = '{_NEEDLE}'\n", encoding="utf-8")
    hits, visited = _scan([tmp_path / "arelis"], tmp_path)
    assert visited >= 1
    assert hits == ["arelis/plant.py:1"]


def test_leftover_banner_secret_is_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    field = _NEEDLE + "_key"
    env_name = "ARELIS_" + _NEEDLE.upper() + "_KEY"
    path = tmp_path / "secrets.yaml"
    path.write_text(
        "earth:\n"
        f'  {field}: "placeholder"\n'
        '  firms_key: "k"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(env_name, "placeholder")
    monkeypatch.delenv("ARELIS_FIRMS_KEY", raising=False)
    assert earth_secret("firms_key", "ARELIS_FIRMS_KEY", path=path) == "k"
    block = earth_block(path)
    assert isinstance(block, dict)
    assert block.get("firms_key") == "k"
    assert block.get(field) == "placeholder"


def test_leftover_banner_config_keys_do_not_break_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "config.local.yaml"
    local.write_text(
        "earth:\n"
        f"  {_NEEDLE}_key: x\n"
        "tools:\n"
        f"  {_NEEDLE}: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("arelis.config.LOCAL_CONFIG_PATH", local)
    cfg = load_config()
    assert cfg["tools"]["browser"]["enabled"] is True


def test_live_and_lod_have_no_banner_adapter() -> None:
    from arelis.earth import live, lod, runtime

    assert _NEEDLE not in live._adapter_fns()
    assert _NEEDLE not in lod.ADAPTER_TTL_S
    assert _NEEDLE not in lod.ADAPTER_LAYERS
    assert _NEEDLE not in lod.ADAPTER_BANDS
    assert _NEEDLE not in lod.SIBLINGS
    assert _NEEDLE not in runtime.LOOK_BOX_ADAPTERS


def test_muted_camera_fetch_still_replaces_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.frames import lla_to_ecef
    from arelis.earth.live import merge_live
    from arelis.earth.simulate import CAMERAS, populate
    from arelis.earth.store import EntityStore
    from tests.earth_helpers import _mute_live

    store = EntityStore()
    populate(store, 1.0)
    assert len(store.in_layer("cameras")) == len(CAMERAS)
    pos = lla_to_ecef(51.508, -0.128, 12.0)
    live_cam = Entity(
        id="tfl:JamCams_00001.01251",
        cls="camera",
        layer="cameras",
        label="TfL Trafalgar Square",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="reconstructed",
        source="TfL JamCam",
        cite="TfL JamCam published position.",
    )
    _mute_live(monkeypatch, fetch_cameras=lambda: [live_cam])
    merge_live(store)
    cams = store.in_layer("cameras")
    assert len(cams) == 1
    assert cams[0].id == "tfl:JamCams_00001.01251"
