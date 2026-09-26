"""Shared detect → draft → force-notice helpers for SMS, email, and agenda.

The three complete modules keep their parsers and field locks. What they
shared was the leftover-recipient walk, the "you have not finished"
notice, and appending the current user turn onto history pairs.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from arelis.history_view import history_pairs

SEND_ALLOW_CLOSER = (
    "Chatting is not sending. The confirm card will ask the user to Allow."
)
CREATE_ALLOW_CLOSER = (
    "Do not send_sms. Do not web_search. Chatting is not creating. "
    "The confirm card will ask the user to Allow."
)


class CompleteDraft(Protocol):
    @property
    def complete(self) -> bool: ...


def remaining_labels(
    labels: Iterable[str],
    already: Iterable[str] | None,
) -> list[str]:
    """Labels still owed, case-insensitive against ``already``."""
    sent = {s.lower() for s in (already or ())}
    return [item for item in labels if item and item.lower() not in sent]


def next_unsent(
    labels: Iterable[str],
    already: Iterable[str] | None,
    fallback: str = "",
) -> str:
    left = remaining_labels(labels, already)
    return left[0] if left else fallback


def with_current_user_turn(
    pairs: list[tuple[str, str]],
    user_text: str,
) -> list[tuple[str, str]]:
    """Append this user line unless history already ends on it."""
    if not pairs or pairs[-1] != ("user", user_text):
        return [*pairs, ("user", user_text)]
    return pairs


def history_with_current(history: list[object] | None, user_text: str) -> list[tuple[str, str]]:
    return with_current_user_turn(history_pairs(history or []), user_text)


def unfinished_call_notice(
    what: str,
    call_clause: str,
    *,
    extra: str = "",
    after: str = SEND_ALLOW_CLOSER,
) -> str:
    """User-role nudge when the model tried to finish without the tool call."""
    return f"You have not finished {what}. {call_clause}.{extra} {after}"
