"""Barge-in mode and conservative headset detection.

On speakers with no echo cancellation, her own TTS reaches the mic, VAD
fires, and she cuts herself off. Barge-in therefore defaults to headset
mode: it is armed during playback only when the current output device
looks like a headset or headphones. always is today's behaviour on any
device. off leaves Stop and wake in place and ignores playback VAD.
"""
from __future__ import annotations

from typing import Any

HEADSET = "headset"
ALWAYS = "always"
OFF = "off"

# Substrings, case-insensitive, matched against the output description or
# id. Conservative: Bluetooth alone is not enough (a Bluetooth speaker
# is still a speaker). "hands-free" is the Windows Bluetooth HFP name.
_HEADSET_MARKERS = (
    "headset",
    "headphone",
    "airpod",
    "hands-free",
    "handsfree",
    "hands free",
)


def parse_barge_in_mode(value: Any, *, default: str = HEADSET) -> str:
    """Return headset, always, or off.

    Legacy booleans keep their old meaning: true is always (today's
    behaviour), false is off. Unknown or missing values use default,
    which is headset so an omitted key does not re-enable speaker echo.
    """
    if value is True:
        return ALWAYS
    if value is False:
        return OFF
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {ALWAYS, "on", "true", "yes", "1"}:
        return ALWAYS
    if text in {OFF, "false", "no", "0", "never"}:
        return OFF
    if text in {HEADSET, "headphones"}:
        return HEADSET
    return default


def is_headset_output(description: str, device_id: str = "") -> bool:
    """True only when the output name or id clearly looks like a headset."""
    text = f"{description} {device_id}".strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _HEADSET_MARKERS)


def barge_in_armed(mode: str, description: str = "", device_id: str = "") -> bool:
    """Whether playback VAD may interrupt her on this output."""
    parsed = parse_barge_in_mode(mode)
    if parsed == ALWAYS:
        return True
    if parsed == OFF:
        return False
    return is_headset_output(description, device_id)
