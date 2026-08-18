"""Standing user profile from data/profile.yaml (non-location fields).

Location stays in arelis.location — this module only formats identity and
preferences that should ride every turn without becoming SQLite facts.
Re-reads the file each call so edits apply on the next turn.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import user_data_dir

log = logging.getLogger(__name__)

# Keep this short. A 50-field schema burns context and goes stale; these are
# the fields worth typing once. Empty values are omitted from the prompt.
# `email` is loaded separately for "email me" routing and is not injected here.
_FIELD_ORDER: tuple[tuple[str, str], ...] = (
    ("name", "Name"),
    ("prefer_called", "Prefer to be called"),
    ("pronouns", "Pronouns"),
    ("work", "Work"),
    ("school", "School"),
    ("answer_style", "Answer style"),
    ("units", "Units"),
    ("timezone_note", "Timezone note"),
    ("notes", "Notes"),
)

_MAX_FIELD_CHARS = 240
_MAX_BLOCK_CHARS = 900


def resolve_profile_path(config: dict[str, Any] | None = None) -> Path:
    """Same file as location.profile_path (default data/profile.yaml)."""
    cfg = (config or {}).get("location") or {}
    raw = str(cfg.get("profile_path") or "data/profile.yaml").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = user_data_dir() / path
    return path


def load_standing_profile(
    path: Path | str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return filled standing fields from profile.yaml, or {} if absent."""
    file_path = Path(path) if path is not None else resolve_profile_path(config)
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read profile %s: %s", file_path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}

    # Prefer an explicit `user:` / `about:` block; else accept top-level keys
    # other than location (so a flat file still works).
    section: Any = None
    for key in ("user", "about", "identity"):
        if isinstance(raw.get(key), dict):
            section = raw[key]
            break
    if section is None:
        section = {k: v for k, v in raw.items() if k != "location"}

    if not isinstance(section, dict):
        return {}

    out: dict[str, str] = {}
    for key, _label in _FIELD_ORDER:
        value = section.get(key)
        if value is None:
            continue
        text = " ".join(str(value).split())
        if not text:
            continue
        if len(text) > _MAX_FIELD_CHARS:
            text = text[: _MAX_FIELD_CHARS - 1].rstrip() + "…"
        out[key] = text
    return out


def load_profile_email(
    path: Path | str | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """The user's inbox from profile.yaml, or empty.

    Used for "email me" and scheduled digests. Not the Gmail Arelis sends from,
    and not included in the standing prompt (it is a routing key, not chatter).
    """
    file_path = Path(path) if path is not None else resolve_profile_path(config)
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return ""
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read profile email %s: %s", file_path, exc)
        return ""
    if not isinstance(raw, dict):
        return ""
    section: Any = None
    for key in ("user", "about", "identity"):
        if isinstance(raw.get(key), dict):
            section = raw[key]
            break
    if section is None:
        section = {k: v for k, v in raw.items() if k != "location"}
    if not isinstance(section, dict):
        return ""
    text = " ".join(str(section.get("email") or "").split())
    if not text or "@" not in text:
        return ""
    local, _, domain = text.partition("@")
    if not local or "." not in domain or " " in text:
        return ""
    return text


def standing_profile_prompt_line(
    fields: dict[str, str] | None = None,
    *,
    config: dict[str, Any] | None = None,
    path: Path | str | None = None,
) -> str:
    """One system block for standing identity/prefs, or empty when unset."""
    data = fields if fields is not None else load_standing_profile(path, config=config)
    if not data:
        return ""
    lines = [
        "Standing profile (hand-edited in data/profile.yaml; treat as durable, "
        "not guesses. Location/timezone may also appear on a separate line.):"
    ]
    total = 0
    for key, label in _FIELD_ORDER:
        value = data.get(key)
        if not value:
            continue
        line = f"- {label}: {value}"
        if total + len(line) > _MAX_BLOCK_CHARS:
            break
        lines.append(line)
        total += len(line)
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
