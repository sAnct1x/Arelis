"""Read earth.* keys from secrets.yaml or the environment.

Never log the values. Adapters fail closed when a key is missing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

SECRETS_PATH = state_dir() / "secrets.yaml"


def earth_secret(field: str, env: str, path: Path | None = None) -> str:
    raw = (os.environ.get(env) or "").strip()
    if raw:
        return raw
    path = path or SECRETS_PATH
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(data, dict):
        return ""
    block = data.get("earth")
    if not isinstance(block, dict):
        return ""
    return str(block.get(field) or "").strip()


def earth_block(path: Path | None = None) -> dict[str, Any]:
    path = path or SECRETS_PATH
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    block = data.get("earth")
    return block if isinstance(block, dict) else {}
