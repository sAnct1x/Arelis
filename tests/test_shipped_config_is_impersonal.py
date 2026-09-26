"""What ships inside the package must mean something on a stranger's machine.

`arelis/config/default.yaml` and the persona markdown are packaged
(`pyproject.toml` package-data) and installed onto every user's computer. A value
in there that only makes sense on one machine is worse than a value that is
merely wrong, because it fails at the moment the feature is used rather than at
startup — a ComfyUI directory under someone else's home folder does not break the
app, it breaks image generation, weeks later, for a reason the user cannot read.

That exact line shipped in this repo until it was removed, which is the argument
for a test rather than a note. This one fails the next time, not just this time.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "arelis"
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "default.yaml"
PERSONA = PACKAGE_ROOT / "persona" / "arelis.md"

HOME_PATH = re.compile(r"(?i)[a-z]:[\\/]users[\\/]([a-z0-9._-]+)")
HOME_PLACEHOLDERS = frozenset({"you", "your", "user", "username", "name", "x"})
MAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
ABSOLUTE = re.compile(r"(?i)^(?:[a-z]:[\\/]|[\\/]{2}|/(?:home|users|mnt|opt)/)")


def _walk(node: Any, trail: str = "") -> list[tuple[str, str]]:
    """Every scalar in the config, with the dotted key path that reaches it."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_walk(value, f"{trail}.{key}" if trail else str(key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_walk(value, f"{trail}[{index}]"))
    elif isinstance(node, str):
        found.append((trail, node))
    return found


def _config_values() -> list[tuple[str, str]]:
    loaded = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8")) or {}
    return _walk(loaded)


def test_no_shipped_config_value_points_into_someones_home_directory() -> None:
    bad = [
        f"{key} -> {value}"
        for key, value in _config_values()
        if any(who.lower() not in HOME_PLACEHOLDERS for who in HOME_PATH.findall(value))
    ]
    assert not bad, (
        "default.yaml ships to every user, and these values name a home "
        "directory that exists on one machine:\n  " + "\n  ".join(bad)
    )


def test_no_shipped_config_value_is_an_absolute_path() -> None:
    """Relative paths resolve per install; absolute ones point at one computer."""
    bad = [
        f"{key} -> {value}"
        for key, value in _config_values()
        if ABSOLUTE.match(value.strip())
    ]
    assert not bad, (
        "An absolute path in default.yaml cannot be right on a machine that is "
        "not this one:\n  " + "\n  ".join(bad)
    )


def test_no_shipped_config_value_carries_an_email_address() -> None:
    """A default mailbox is somebody's, and it will not be the user's."""
    bad = [
        f"{key} -> {value}"
        for key, value in _config_values()
        if MAIL.search(value) and "example.com" not in value.lower()
    ]
    assert not bad, (
        "An address in default.yaml would ship as a stranger's default:\n  "
        + "\n  ".join(bad)
    )


def test_comfy_auto_start_ships_with_nowhere_to_start_from() -> None:
    """Auto-start plus a path is a subprocess launched on somebody else's PC.

    Off with an empty path is the honest default: the feature reports itself
    unavailable rather than failing at a directory the user has never heard of.
    """
    loaded = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8")) or {}
    image = (loaded.get("tools") or {}).get("image") or {}
    assert image.get("auto_start") is False
    assert not str(image.get("launch_cwd") or "").strip()


def test_the_persona_does_not_describe_one_particular_person() -> None:
    """Her character ships; the operator's hobbies should not ride along.

    An interest list baked in here is a taste, not a trait, and it arrives
    identically on the machine of somebody who installed this to manage a diary.
    """
    text = PERSONA.read_text(encoding="utf-8").lower()
    for giveaway in ("interferometry", "astrophysics", "optics"):
        assert giveaway not in text, (
            f"The shipped persona names {giveaway!r} as an interest. Curiosity is "
            "a trait worth shipping; a subject list belongs in a user's profile."
        )
