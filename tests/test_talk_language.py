from arelis.talk_language import (
    DEFAULT,
    LANGUAGES,
    bcp47,
    is_english,
    normalize,
    reply_instruction,
)


def test_english_is_first_and_default() -> None:
    assert LANGUAGES[0][0] == DEFAULT == "en"
    rest = [row[1] for row in LANGUAGES[1:]]
    assert rest == sorted(rest)


def test_unknown_falls_back_to_english() -> None:
    assert normalize("") == "en"
    assert normalize("tlh") == "en"
    assert normalize("zh-CN") == "zh"
    assert normalize("Chinese") == "zh"
    assert bcp47("ja") == "ja-JP"
    assert is_english("en-US")
    assert not is_english("es")


def test_english_does_not_rewrite_the_persona() -> None:
    assert reply_instruction("en") == ""
    note = reply_instruction("zh")
    assert "Chinese" in note
    assert "Reply in Chinese" in note
