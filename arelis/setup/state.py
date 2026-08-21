"""Whether model setup still has to run, and recording the choice.

The workspace marker already exists. Model setup is a field on that same file,
not a second permission and not a bump of MARKER_VERSION. An older marker
without the field means “asked about the folder, not yet about a brain.”

If this copy already pinned a chat tag in config.local.yaml, we mark setup
complete without showing glass. That person is not a new user.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from arelis.config import LOCAL_CONFIG_PATH, merge_local_config
from arelis.onboarding import marker_path
from arelis.paths import ensure, state_dir
from arelis.setup.catalog import EMBED_TAG

log = logging.getLogger(__name__)


def needs_model_setup() -> bool:
    marker = _read_marker()
    setup = (marker or {}).get("model_setup") or {}
    if setup.get("complete"):
        return False
    tag = _configured_fast()
    if tag:
        # Already pinned a brain in config.local.yaml. Do not re-ask just
        # because Ollama is down this morning.
        record_model_setup_complete(tag=tag)
        return False
    return True


def record_model_choice(tag: str) -> None:
    """Pin one chat model as both composer chips, and a window this card holds.

    The shipped ``num_ctx`` is one number measured on one 12 GB card. Pinning a
    window derived from the card that is actually present is the difference
    between a stranger on 8 GB spilling layers to the CPU and a stranger on
    24 GB being capped for no reason.
    """
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
    window = _window_for_tag(name)
    if window:
        patch["ollama"] = {"num_ctx": window, "research_num_ctx": window}
    merge_local_config(patch)
    record_model_setup_complete(tag=name)


def _window_for_tag(tag: str) -> int:
    """Measured-VRAM context window, or 0 when we cannot tell."""
    try:
        from arelis.setup.catalog import by_tag
        from arelis.setup.context import context_window_for
        from arelis.setup.hardware import probe_hardware

        model = by_tag(tag)
        if model is None:
            return 0
        return int(context_window_for(model, probe_hardware()))
    except Exception as exc:  # pragma: no cover - never block the pin
        log.info("Could not size the context window for %s: %s", tag, exc)
        return 0


def record_model_setup_complete(*, tag: str) -> None:
    payload = _read_marker() or {}
    payload["model_setup"] = {
        "complete": True,
        "tag": (tag or "").strip(),
        "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_marker(payload)


def _configured_fast() -> str:
    """Only a tag this copy pinned locally — not the shipped default.yaml."""
    path = LOCAL_CONFIG_PATH
    if not path.is_file():
        return ""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    models = data.get("models") or {}
    if not isinstance(models, dict):
        return ""
    return str(models.get("fast") or "").strip()


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
