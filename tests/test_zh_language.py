"""Simplified Chinese is a session, not a scrubbed accident."""

from __future__ import annotations

from arelis.core.confirm_patterns import affirmation_pattern
from arelis.core.confirm_speech import (
    classify_hangup,
    classify_repeat,
    classify_voice_act,
)
from arelis.talk_language import (
    keeps_cjk,
    reply_instruction,
    session_code,
    spoken_policy,
    turn_language,
)


def test_simplified_reply_is_explicit_and_english_stays_empty() -> None:
    assert reply_instruction("en") == ""
    assert reply_instruction("") == ""
    note = reply_instruction("zh")
    assert "简体中文" in note
    assert "Simplified" in note
    assert "繁體" not in note
    traditional = reply_instruction("zh-TW")
    assert "繁體中文" in traditional
    assert spoken_policy("zh").startswith("你正在对话模式")
    assert "speaking aloud" in spoken_policy("en")


def test_session_language_drives_the_turn_unless_the_phone_says() -> None:
    config = {"ui": {"language": "zh"}}
    assert session_code(config) == "zh"
    assert turn_language(config, "") == "zh"
    assert turn_language(config, "en") == "en"
    assert keeps_cjk({"ui": {"language": "zh"}})
    assert keeps_cjk({"_reply_language": "zh", "ui": {"language": "en"}})
    assert not keeps_cjk({"_reply_language": "en", "ui": {"language": "zh"}})
    assert not keeps_cjk({"ui": {"language": "en"}})


def test_spoken_yes_stop_and_goodbye_in_chinese() -> None:
    assert classify_voice_act("好的") == "allow"
    assert classify_voice_act("可以。") == "allow"
    assert classify_voice_act("停") == "stop"
    assert classify_voice_act("别说了") == "stop"
    assert classify_voice_act("不要") == "skip"
    assert classify_voice_act("今天天气怎么样") is None
    assert classify_hangup("再见")
    assert classify_repeat("再说一遍")
    assert affirmation_pattern().match("好的")


