"""One number bounds the conversation history, not two that disagree.

Two limiters used to guard the same list. ``SessionMemory.max_messages``
defaulted to 40; ``agent.history_max_messages`` said 120. The tighter one wins,
so the loop's cap was unreachable and the oldest turns were deleted inside
SessionMemory instead — silently, with no summary, no pending facts and no
telemetry, which is exactly what the loop's fold path exists to prevent.

Nothing failed when that was true. The session simply forgot, and the tests that
covered folding kept passing because they used messages fat enough to blow the
token budget before the count cap could bite.
"""

from __future__ import annotations

from arelis.config import load_config
from arelis.core.memory import SessionMemory


def _configured_cap() -> int:
    return int((load_config().get("agent") or {}).get("history_max_messages"))


def test_the_working_set_is_built_from_the_configured_cap() -> None:
    memory = SessionMemory.from_config(load_config())
    assert memory.max_messages == _configured_cap()


def test_the_dataclass_default_does_not_undercut_the_config() -> None:
    """A caller that forgets from_config must not silently shrink history."""
    assert SessionMemory().max_messages >= _configured_cap()


def test_a_missing_setting_leaves_the_default_alone() -> None:
    memory = SessionMemory.from_config({})
    assert memory.max_messages == SessionMemory().max_messages


def test_a_junk_setting_leaves_the_default_alone() -> None:
    memory = SessionMemory.from_config({"agent": {"history_max_messages": "lots"}})
    assert memory.max_messages == SessionMemory().max_messages


def test_the_cap_is_honoured_as_messages_arrive() -> None:
    memory = SessionMemory.from_config({"agent": {"history_max_messages": 6}})
    for i in range(20):
        memory.add("user", f"u{i}")
    assert len(memory.messages) == 6
    assert memory.messages[-1].content == "u19"


def test_restoring_a_long_room_does_not_load_it_all() -> None:
    """hydrate used to skip the trim, and get_messages has no limit.

    Restoring a months-old conversation would put every message it ever held
    into the working set, then hand the next prompt build a history far past the
    cap — which the loop would answer by folding hundreds of messages at once,
    inside an 8s budget it could not meet.
    """
    memory = SessionMemory.from_config({"agent": {"history_max_messages": 10}})
    archive = [{"role": "user", "content": f"old {i}"} for i in range(400)]
    memory.hydrate(archive, summary="earlier")

    assert len(memory.messages) == 10
    assert memory.messages[-1].content == "old 399"
    assert memory.summary == "earlier"
