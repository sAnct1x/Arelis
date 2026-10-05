"""Reply language for the pocket. English first, then a short major-language list.

The phone stores a BCP-47 tag and sends the short code on each turn. The house
injects a system line for that turn only, it does not flip PC conversation
mode, and it does not change the persona file.
"""

from __future__ import annotations

import re
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


_SIMPLIFIED = (
    "The user is using Simplified Chinese (简体中文) for this whole session. "
    "Reply entirely in Simplified Chinese. Use simplified characters, not traditional. "
    "Keep your character: a peer at the desk, warm and precise, not a helpdesk. "
    "Casual in, casual out. Do not add English filler. "
    "Physics and math: say the idea in Chinese, keep the notation, and keep the "
    "English technical term in parentheses when that is how a class says it. "
    "Call tools for algebra, units, constants, plots, files, and the web; "
    "the user-facing answer is still Chinese. "
    "Do not switch languages unless they clearly ask for the English wording."
)

_TRADITIONAL = (
    "The user is writing in Traditional Chinese (繁體中文). "
    "Reply entirely in Traditional Chinese. "
    "Do not switch languages unless they clearly ask."
)

# Byte-identical to the conversation-mode line the prompt used to inline.
# English stays here so a Chinese session can replace it without a second copy
# drifting in prompt_sections.
_SPOKEN_EN = (
    "You are speaking aloud in conversation mode. Prefer "
    "1-3 short sentences unless the user asked for detail, "
    "code, steps, or a list. Their text is a speech "
    'transcript, messy, filled with ah/um, and wrong on '
    "names. Hear what they meant from the last few turns. "
    "Do not correct the transcript and do not ask them to "
    "repeat themselves. If they said they missed what you "
    'said, say the last answer again, do not ask what they '
    "wanted repeated. Small talk is talk: what are you "
    "doing tonight is not a calendar, and what did I say "
    "without a topic is not a recall search. Do not "
    "interview; one follow-up is enough and none is fine. "
    "When they asked you to do something (text, email, "
    "write, search, weather, scrape, remember), call the "
    'tool first, do not only talk about doing it, and do '
    "not ask permission in chat. send_sms and send_email "
    "open a confirm card; that is how the message is "
    "approved."
)

_SPOKEN_ZH = (
    "你正在对话模式里出声说话，用简体中文。默认一两句到三句，"
    "除非他们要细节、步骤或推导。他们的文字是语音识别结果，可能有错字和口头语。"
    "按最近几轮理解意思，不要纠正转写，也不要叫他们再说一遍。"
    "如果他们没听清，把上一句再讲一遍。闲聊就是闲聊。"
    "要你做事（发消息、写文件、搜索、计算、查天气）就先调用工具，不要只说你打算做。"
    "send_sms 和 send_email 会弹出确认，那就是批准方式。"
    "公式和符号保持原样，解释用简体中文。"
)


def reply_instruction(raw: Any) -> str:
    """Turn-local system line. Empty for English so the default prompt stays put."""
    key = str(raw or "").strip().lower().replace("_", "-")
    code = normalize(raw)
    if code == DEFAULT:
        return ""
    if code == "zh":
        if "hant" in key or key in {"zh-tw", "zh-hk", "zh-mo"}:
            return _TRADITIONAL
        return _SIMPLIFIED
    name = native_name(code)
    return (
        f"The user is writing in {name}. Reply in {name}. "
        "Do not switch languages unless they clearly ask."
    )


def spoken_policy(raw: Any) -> str:
    """Conversation-mode system line. Chinese sessions get the Chinese one."""
    if normalize(raw) == "zh":
        key = str(raw or "").strip().lower().replace("_", "-")
        if "hant" in key or key in {"zh-tw", "zh-hk", "zh-mo"}:
            return _SPOKEN_EN
        return _SPOKEN_ZH
    return _SPOKEN_EN


def session_code(config: Any) -> str:
    """UI language for this process. English when unset."""
    if not isinstance(config, dict):
        return DEFAULT
    ui = config.get("ui") or {}
    if not isinstance(ui, dict):
        return DEFAULT
    return normalize(ui.get("language"))


def turn_language(config: Any, explicit: Any = "") -> str:
    """Phone tag wins when the turn sent one. Otherwise the session language."""
    raw = str(explicit or "").strip()
    if raw:
        return normalize(raw)
    return session_code(config)


def active_reply_language(config: Any) -> str:
    """Language of the turn in flight, else the session language."""
    if not isinstance(config, dict):
        return DEFAULT
    explicit = str(config.get("_reply_language") or "").strip()
    if explicit:
        return normalize(explicit)
    return session_code(config)


def keeps_cjk(config: Any) -> bool:
    """True when Chinese characters are the reply, not a leak to scrub."""
    return active_reply_language(config) == "zh"


_LANG_WORD = (
    r"simplified\s+chinese|mandarin|chinese|english"
    r"|简体中文|中文|汉语|英文|英语"
)
_LANG_SWITCH = re.compile(
    rf"""(?ix)
    ^\s*
    (?:(?:hey|hi)\s+)?
    (?:arelis\s*[,，:]?\s*)?
    (?:(?:can|could|would)\s+you\s+)?
    (?:please\s+)?
    (?:
        (?:switch|change|set)(?:\s+the)?(?:\s+language)?\s+(?:back\s+)?to
        |(?:speak|talk|answer)(?:\s+in)?
        |use
    )
    \s+
    (?P<lang>{_LANG_WORD})
    \s*
    (?:mode|模式)?
    \s*
    (?:
        (?:
            (?:[,，]|然后|再)
            |\s+(?:and\s+then|and|then)
        )
        \s*
        (?P<rest>.*?)
    )?
    \s*[.!?。！？]*\s*$
    """
)
_LANG_SWITCH_ZH = re.compile(
    rf"""(?x)
    ^\s*
    (?:请)?
    (?:换成|改成|切换到|切换成|用|说|讲)
    (?P<lang>{_LANG_WORD})
    \s*
    (?:吧)?
    \s*
    (?:
        (?:[,，]|然后|再)\s*
        (?P<rest>.*?)
    )?
    \s*[.!?。！？]*\s*$
    """
)
_LANG_BARE = re.compile(
    rf"(?ix)^\s*(?P<lang>{_LANG_WORD})\s*[.!?。！？]*\s*$"
)


def _language_code(name: str) -> str:
    folded = re.sub(r"\s+", " ", (name or "").strip().lower())
    if folded in {"english", "英文", "英语"}:
        return "en"
    return "zh"


def match_language_switch(text: str) -> tuple[str, str] | None:
    """(code, remainder) when this line asks to change the session language.

    Remainder is what to do after the switch. Empty when the switch was the
    whole ask. None when the line mentions a language and is not a switch.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    bare = _LANG_BARE.match(raw)
    if bare:
        return _language_code(bare.group("lang")), ""
    found = _LANG_SWITCH_ZH.match(raw) or _LANG_SWITCH.match(raw)
    if found is None:
        return None
    rest = (found.groupdict().get("rest") or "").strip(" \t.,!！?？。")
    return _language_code(found.group("lang")), rest
