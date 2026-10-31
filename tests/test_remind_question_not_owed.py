""""remind me, what does a light year measure?" does not owe the remind tool."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.core.turn_scratch import named_tools_owed


def _owed(text: str) -> list[str]:
    ctx = SimpleNamespace(
        text=text, typed_text=None, staged_files=(), available_all={"remind", "units"}
    )
    return named_tools_owed(SimpleNamespace(tools_used=[]), ctx)


def test_a_remind_me_question_owes_no_remind_but_a_timer_ask_does() -> None:
    assert _owed("remind me, what does a light year measure?") == []
    assert _owed("remind me in 20 minutes to stretch") == ["remind"]
