"""Whether model setup still has to run, and recording a model file.

The workspace marker already exists. Chat is llama.cpp. First-run looks for
a chat GGUF on disk. If it is missing, the wizard downloads one.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arelis.config import merge_local_config, shipped_num_ctx
from arelis.onboarding import marker_path
from arelis.paths import ensure, state_dir
from arelis.setup.catalog import by_tag

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
    """Mark setup complete when the chat GGUF is already on this PC."""
    found = _located_gguf()
    if found is None:
        return False
    record_model_setup_complete(tag=found.name)
    return True


def needs_model_setup() -> bool:
    """True when no chat GGUF is on disk yet."""
    return _located_gguf() is None


def record_model_choice(tag: str) -> None:
    """Pin the chosen GGUF path, context cap, and catalog n_cpu_moe/ubatch."""
    name = (tag or "").strip()
    if not name:
        raise ValueError("model tag is empty")
    model = by_tag(name)
    filename = model.filename if model is not None else name
    llamacpp: dict[str, Any] = {
        "model": filename,
        "default_cap": int(shipped_num_ctx()),
    }
    if model is not None:
        llamacpp["n_cpu_moe"] = int(model.n_cpu_moe)
        llamacpp["ubatch"] = int(model.ubatch)
    patch: dict[str, Any] = {"llamacpp": llamacpp}
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


def _located_gguf() -> Path | None:
    try:
        from arelis.config import load_config
        from arelis.llm.llama_launch import locate_model_gguf

        found = locate_model_gguf(load_config())
    except Exception:
        # Config or disk probe failed: treat as missing so first-run can ask.
        return None
    return found


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
