"""Persist SMS chat threads across launches. Bodies only — no secrets."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from arelis.paths import state_dir

log = logging.getLogger(__name__)

THREADS_PATH = state_dir() / "sms_threads.json"
MAX_PER_THREAD = 200
MAX_THREADS = 40


def load_threads(path: Path | None = None) -> dict[str, dict[str, Any]]:
    target = path or THREADS_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read SMS threads: %s", exc)
        return {}
    rows = raw.get("threads") if isinstance(raw, dict) else None
    if not isinstance(rows, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in rows.items():
        if isinstance(value, dict) and key:
            out[str(key)] = value
    return out


def save_threads(
    threads: dict[str, dict[str, Any]],
    path: Path | None = None,
) -> None:
    target = path or THREADS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    keys = list(threads.keys())[-MAX_THREADS:]
    payload = {"threads": {key: threads[key] for key in keys}}
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def cap_messages(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) <= MAX_PER_THREAD:
        return rows
    return rows[-MAX_PER_THREAD:]
