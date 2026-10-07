"""Simplified Chinese is a session, not a scrubbed accident."""

from __future__ import annotations

from arelis.core.confirm_patterns import affirmation_pattern
from arelis.core.confirm_speech import (
    classify_hangup,
    classify_repeat,
    classify_voice_act,
)
from arelis.i18n import set_ui_language, tr
from arelis.talk_language import (
    keeps_cjk,
    reply_instruction,
    session_code,
    spoken_policy,
    turn_language,
)
from arelis.voice.speech_text import prepare_spoken_text, split_sentences


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


def test_chinese_answers_are_not_stripped_for_speech() -> None:
    heard = prepare_spoken_text("今天天气不错。Arelis 在。", language="zh")
    assert "今天天气不错" in heard
    assert "阿瑞丽丝" in heard
    assert "Uh-rell-iss" not in heard
    english = prepare_spoken_text("hello 你好 there", language="en")
    assert "你好" not in english
    parts = split_sentences("第一句。第二句！", language="zh")
    assert parts == ["第一句。", "第二句！"]


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


def test_window_copy_follows_the_session_language() -> None:
    set_ui_language("zh")
    try:
        assert tr("Settings") == "设置"
        assert tr("stop") == "停止"
        assert tr("not a real label") == "not a real label"
    finally:
        set_ui_language("en")
    assert tr("Settings") == "Settings"


def test_asking_switches_the_session_language() -> None:
    from arelis.talk_language import match_language_switch

    assert match_language_switch("switch to chinese") == ("zh", "")
    assert match_language_switch("switch to simplified chinese") == ("zh", "")
    assert match_language_switch("can you speak chinese?") == ("zh", "")
    assert match_language_switch("用中文") == ("zh", "")
    assert match_language_switch("换成简体中文") == ("zh", "")
    assert match_language_switch("中文") == ("zh", "")
    assert match_language_switch("switch to english") == ("en", "")
    assert match_language_switch("换成英文") == ("en", "")
    assert match_language_switch("english") == ("en", "")
    assert match_language_switch("switch to chinese and what's the weather") == (
        "zh",
        "what's the weather",
    )
    assert match_language_switch("the chinese room") is None
    assert match_language_switch("use chinese notation") is None
    assert match_language_switch("translate this to chinese") is None


def test_chinese_phonemes_are_kokoro_ipa() -> None:
    import pytest

    pytest.importorskip("misaki.zh")
    from arelis.voice.kokoro_tts import _VOCAB, _phonemize_zh

    class _Synth:
        _zh_g2p = None

    phonemes = _phonemize_zh("你好。", _Synth())
    assert "↓" in phonemes
    assert "." in phonemes
    assert "。" not in phonemes
    assert not any("\u3105" <= ch <= "\u312f" for ch in phonemes)
    assert all(ch in _VOCAB for ch in phonemes)
