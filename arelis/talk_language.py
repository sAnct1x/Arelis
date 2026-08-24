"""Reply language for the pocket. English first, then a short major-language list.

The phone stores a BCP-47 tag and sends the short code on each turn. The house
injects a system line for that turn only — it does not flip PC conversation
mode, and it does not change the persona file.
"""

from __future__ import annotations

from typing import Any

# English stays first and is the default. The rest are alphabetical by English
# name. Major languages only; more can be added later without reshuffling this
# contract.
LANGUAGES: tuple[tuple[str, str, str, str], ...] = (
    ("en", "english", "en-US", "English"),
    ("zh", "chinese", "zh-CN", "Chinese"),
    ("fr", "french", "fr-FR", "French"),
    ("ja", "japanese", "ja-JP", "Japanese"),
    ("ko", "korean", "ko-KR", "Korean"),
    ("es", "spanish", "es-ES", "Spanish"),
)

DEFAULT = "en"

_BY_CODE = {row[0]: row for row in LANGUAGES}
_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "zh-tw": "zh",
    "zh-hant": "zh",
    "chinese": "zh",
    "fr": "fr",
    "fr-fr": "fr",
    "french": "fr",
    "ja": "ja",
    "ja-jp": "ja",
    "japanese": "ja",
    "ko": "ko",
    "ko-kr": "ko",
    "korean": "ko",
    "es": "es",
    "es-es": "es",
    "es-mx": "es",
    "spanish": "es",
}


def normalize(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace("_", "-")
    if not key:
        return DEFAULT
    if key in _ALIASES:
        return _ALIASES[key]
    short = key.split("-", 1)[0]
    if short in _BY_CODE:
        return short
    return DEFAULT


def bcp47(raw: Any) -> str:
    code = normalize(raw)
    return _BY_CODE[code][2]


def native_name(raw: Any) -> str:
    return _BY_CODE[normalize(raw)][3]


def is_english(raw: Any) -> bool:
    return normalize(raw) == DEFAULT


def reply_instruction(raw: Any) -> str:
    """Turn-local system line. Empty for English so the default prompt stays put."""
    code = normalize(raw)
    if code == DEFAULT:
        return ""
    name = native_name(code)
    return (
        f"The user is writing in {name}. Reply in {name}. "
        "Do not switch languages unless they clearly ask."
    )
