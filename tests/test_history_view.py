"""history_pairs reads chat history as (role, content) pairs."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.history_view import history_pairs


def test_history_pairs_missing_or_none_content_is_empty() -> None:
    assert history_pairs([{"role": "user"}]) == [("user", "")]
    assert history_pairs([{"role": "assistant", "content": None}]) == [("assistant", "")]
    assert history_pairs([SimpleNamespace(role="user", content=None)]) == [("user", "")]
    assert history_pairs([{"content": "orphaned"}]) == [("", "orphaned")]


