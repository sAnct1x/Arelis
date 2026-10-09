"""Baked face layers on disk, in the app cache, premultiplied.

A crash mid-write leaves a temp name, never a half file under the real key.
A bad file is deleted and the bake runs again.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

FORMAT_VERSION = 1
# 1x, 1.5x, 2x, and one dock resize. Older sizes drop first.
KEEP_SIZES = 4
# Four of those rasters, zlib, sit well under this. Past it, drop the oldest.
CAP_BYTES = 480 * 1024 * 1024
_BASE = ("face", "wisps", "ring", "star", "blur_soft", "blur_wide")

_VERSION: str | None = None


def renderer_version() -> str:
    """Hash of the art sources. A change in those files misses the old cache."""
    global _VERSION
    if _VERSION is None:
        root = Path(__file__).resolve().parent
        digest = hashlib.sha256()
        for name in (
            "plate.py",
            "hair_paint.py",
            "face_src.py",
            "adult.py",
            "bake.py",
            "nebula_src.py",
            "scene_bits.py",
        ):
            digest.update((root / name).read_bytes())
        _VERSION = digest.hexdigest()[:16]
    return _VERSION


def cache_root() -> Path:
    """This profile's cache. Tests point it at tmp_path."""
    from arelis.paths import cache_dir, ensure

    return ensure(cache_dir() / "persona-face")


def cache_key(width: int, height: int, dpr: float) -> str:
    ratio = f"{float(dpr):.2f}"
    return f"f{FORMAT_VERSION}-r{renderer_version()}-{int(width)}x{int(height)}-d{ratio}"


def _is_base(name: str) -> bool:
    if name in _BASE or name in {"back_0", "front_0"}:
        return True
    return name.startswith(("mouth_", "eye_", "gaze_", "wink_", "smile_", "glance_"))


def _split(layers: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    base: dict[str, np.ndarray] = {}
    rest: dict[str, np.ndarray] = {}
    for name, array in layers.items():
        if _is_base(name):
            base[name] = array
        elif name.startswith(("back_", "front_")):
            rest[name] = array
        else:
            base[name] = array
    return base, rest


def _write_npz(path: Path, layers: dict[str, np.ndarray], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.npz")
    payload = {name: np.ascontiguousarray(array) for name, array in layers.items()}
    payload["meta"] = np.array(json.dumps(meta))
    np.savez_compressed(tmp, **payload)
    os.replace(tmp, path)


def _read_npz(path: Path, *, need_face: bool) -> dict[str, np.ndarray] | None:
    if not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as packed:
            meta_raw = packed["meta"]
            raw = meta_raw.item() if getattr(meta_raw, "shape", ()) == () else meta_raw
            meta = json.loads(str(raw))
            if int(meta.get("format", -1)) != FORMAT_VERSION:
                raise ValueError("format")
            if str(meta.get("renderer", "")) != renderer_version():
                raise ValueError("renderer")
            out = {name: np.array(packed[name]) for name in packed.files if name != "meta"}
    # A torn or foreign file is not a face. The caller deletes it and bakes.
    except Exception:
        return None
    if need_face and "face" not in out:
        return None
    return out


def load_layers(
    width: int, height: int, dpr: float
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]] | None:
    """Base layers (face and phase 0) first, then the other hair phases."""
    folder = cache_root() / cache_key(width, height, dpr)
    base = _read_npz(folder / "base.npz", need_face=True)
    if base is None:
        _drop(folder)
        return None
    phases_path = folder / "phases.npz"
    if not phases_path.is_file():
        rest = {}
    else:
        rest = _read_npz(phases_path, need_face=False)
        if rest is None:
            _drop(folder)
            return None
    try:
        os.utime(folder)
    except OSError:
        pass
    return base, rest


def store_base(layers: dict[str, np.ndarray], width: int, height: int, dpr: float) -> None:
    """Face and phase 0, as soon as they exist. A quit during the hair sweep keeps her."""
    if "face" not in layers:
        return
    root = cache_root()
    key = cache_key(width, height, dpr)
    folder = root / key
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        "format": FORMAT_VERSION,
        "renderer": renderer_version(),
        "width": int(width),
        "height": int(height),
        "dpr": round(float(dpr), 2),
    }
    base, _rest = _split(layers)
    _write_npz(folder / "base.npz", base, meta)
    _prune(root, keep=key)


def store_layers(layers: dict[str, np.ndarray], width: int, height: int, dpr: float) -> None:
    if "face" not in layers:
        return
    root = cache_root()
    key = cache_key(width, height, dpr)
    folder = root / key
    staging = root / f".{key}.writing"
    if staging.exists():
        _drop(staging)
    staging.mkdir(parents=True, exist_ok=True)
    meta = {
        "format": FORMAT_VERSION,
        "renderer": renderer_version(),
        "width": int(width),
        "height": int(height),
        "dpr": round(float(dpr), 2),
    }
    base, rest = _split(layers)
    _write_npz(staging / "base.npz", base, meta)
    _write_npz(staging / "phases.npz", rest, meta)
    if folder.exists():
        _drop(folder)
    os.replace(staging, folder)
    _prune(root, keep=key)


def _drop(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            return
        return
    for child in path.rglob("*"):
        if child.is_file():
            try:
                child.unlink()
            except OSError:
                pass
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass


def _folder_bytes(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _prune(root: Path, keep: str) -> None:
    """Drop other art versions, then the oldest sizes past the count and the cap."""
    folders = [item for item in root.iterdir() if item.is_dir() and not item.name.startswith(".")]
    prefix = f"f{FORMAT_VERSION}-r{renderer_version()}-"
    for folder in folders:
        if not folder.name.startswith(prefix):
            _drop(folder)
    kept = [item for item in root.iterdir() if item.is_dir() and item.name.startswith(prefix)]
    kept.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    ordered = [item for item in kept if item.name == keep] + [
        item for item in kept if item.name != keep
    ]
    used = 0
    for index, folder in enumerate(ordered):
        size = _folder_bytes(folder)
        if index > 0 and (index >= KEEP_SIZES or used + size > CAP_BYTES):
            _drop(folder)
            continue
        used += size
