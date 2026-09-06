"""JSON sidecar next to a generated PNG so later turns know how it was made."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sidecar_path(png_path: Path) -> Path:
    return Path(png_path).with_suffix(".json")


def write_sidecar(
    png_path: Path,
    *,
    prompt: str,
    negative: str,
    seed: int,
    checkpoint: str,
    width: int,
    height: int,
    style: str,
    mode: str,
    source: str,
    denoise: float,
    n: int,
) -> Path:
    dest = sidecar_path(png_path)
    dest.write_text(
        json.dumps(
            {
                "prompt": prompt,
                "negative": negative,
                "seed": int(seed),
                "checkpoint": checkpoint,
                "width": int(width),
                "height": int(height),
                "style": style,
                "mode": mode,
                "source": source,
                "denoise": float(denoise),
                "n": int(n),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return dest


def read_named_sidecar(path_str: str) -> dict[str, Any]:
    """Sidecar for an outputs/images/ path as chat and tools write it."""
    from arelis.paths import user_data_dir

    raw = (path_str or "").strip().replace("\\", "/")
    if not raw:
        return {}
    path = Path(raw)
    if not path.is_absolute():
        path = user_data_dir() / raw
    return read_sidecar(path)


def read_sidecar(png_path: Path) -> dict[str, Any]:
    dest = sidecar_path(png_path)
    if not dest.is_file():
        return {}
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
