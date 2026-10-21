"""Whether model setup still has to run, and recording a model name.

The workspace marker already exists. Chat is llama.cpp, so first-run does
not install an engine or pull a model. Marker helpers stay so an older
profile still loads.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from arelis.config import merge_local_config
from arelis.onboarding import marker_path
from arelis.paths import ensure, state_dir
from arelis.setup.catalog import EMBED_TAG

log = logging.getLogger(__name__)


def shipped_fast_tag() -> str:
    """Chat model name from shipped default.yaml (not a local pin)."""
    try:
        import yaml

        from arelis.config import DEFAULT_CONFIG_PATH

        data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        # Unreadable shipped default: treat as no tag rather than abort launch.
        return ""
    if not isinstance(data, dict):
        return ""
    models = data.get("models") or {}
    if not isinstance(models, dict):
        return ""
    return str(models.get("fast") or "").strip()


def try_quiet_complete_model_setup() -> bool:
    """Nothing to download. First-run can open the window."""
    return True


def needs_model_setup() -> bool:
    """First-run does not install a chat server or pull a model."""
    return False


def record_model_choice(tag: str) -> None:
    """Pin one chat model as both composer chips."""
    name = (tag or "").strip()
    if not name:
        raise ValueError("model tag is empty")
    patch: dict[str, Any] = {
        "models": {
            "fast": name,
            "research": name,
        },
        "memory": {"embed_model": EMBED_TAG},
    }
    merge_local_config(patch)
    record_model_setup_complete(tag=name)


def record_model_setup_complete(*, tag: str) -> None:
    payload = _read_marker() or {}
    payload["model_setup"] = {
        "complete": True,
        "tag": (tag or "").strip(),
        "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_marker(payload)


def _read_marker() -> dict[str, Any] | None:
    path = marker_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_marker(payload: dict[str, Any]) -> None:
    try:
        ensure(state_dir())
        marker_path().write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Could not record model setup: %s", exc)
