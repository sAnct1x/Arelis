"""history_pairs reads chat history as (role, content) pairs."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.history_view import history_pairs


def test_history_pairs_none_and_empty_are_empty() -> None:
    assert history_pairs(None) == []
    assert history_pairs([]) == []


def test_history_pairs_reads_dicts_and_objects() -> None:
    dicts = [
        {"role": "user", "content": "where is the note"},
        {"role": "assistant", "content": "on the desk"},
    ]
    objects = [
        SimpleNamespace(role="user", content="where is the note"),
        SimpleNamespace(role="assistant", content="on the desk"),
    ]
    expected = [("user", "where is the note"), ("assistant", "on the desk")]
    assert history_pairs(dicts) == expected
    assert history_pairs(objects) == expected


def test_history_pairs_missing_or_none_content_is_empty() -> None:
    assert history_pairs([{"role": "user"}]) == [("user", "")]
    assert history_pairs([{"role": "assistant", "content": None}]) == [("assistant", "")]
    assert history_pairs([SimpleNamespace(role="user", content=None)]) == [("user", "")]
    assert history_pairs([{"content": "orphaned"}]) == [("", "orphaned")]


def test_history_pairs_skips_entries_that_are_neither() -> None:
    history = [
        "just a string",
        7,
        None,
        SimpleNamespace(role="user"),
        {"role": "assistant", "content": "kept"},
    ]
    assert history_pairs(history) == [("assistant", "kept")]


def test_history_pairs_preserves_order() -> None:
    history = [
        {"role": "user", "content": "first"},
        "skip me",
        SimpleNamespace(role="assistant", content="second"),
        3,
        {"role": "user", "content": None},
        None,
        SimpleNamespace(role="assistant", content="fourth"),
    ]
    assert history_pairs(history) == [
        ("user", "first"),
        ("assistant", "second"),
        ("user", ""),
        ("assistant", "fourth"),
    ]
