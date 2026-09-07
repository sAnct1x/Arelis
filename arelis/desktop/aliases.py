"""Resolve spoken app names to a launch key — not a per-app tool."""

from __future__ import annotations

import re

# Built-in shortcuts. Config aliases merge on top (override by key).
# Values are launch keys (ShellExecute / App Paths), not filesystem paths.
DEFAULT_ALIASES: dict[str, str] = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "paint": "mspaint",
    "mspaint": "mspaint",
    "snip": "snippingtool",
    "snipping tool": "snippingtool",
    "snippingtool": "snippingtool",
}

_SPOKEN = re.compile(r"\s+")


def normalize_name(target: str) -> str:
    return _SPOKEN.sub(" ", (target or "").strip().lower())


def resolve_app(
    target: str,
    *,
    aliases: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Return (launch_key, error). Never a raw filesystem path."""
    raw = normalize_name(target)
    if not raw:
        return None, "Need an app name (e.g. notepad, calculator)."
    merged = {**DEFAULT_ALIASES, **{normalize_name(k): v for k, v in (aliases or {}).items()}}
    if raw in merged:
        return merged[raw], None
    compact = raw.replace(" ", "")
    for key, value in merged.items():
        if key.replace(" ", "") == compact:
            return value, None
    return raw, None
