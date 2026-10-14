"""Routing classification telemetry (Wave 0 / Wave 2)."""

from __future__ import annotations

from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.tools.base import ToolRegistry


class _StubRouter:
    default_role = "fast"
    active_model = "stub"


def _orch() -> Orchestrator:
    return Orchestrator(
        EventBus(),
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {"workspace": {"roots": ["."]}, "_persona_path": "persona.md"},
        SessionMemory(),
    )


def test_chip_research_wins() -> None:
    role, reason = _orch().classify_role("hello", "research")
    assert role == "research"
    assert reason == "chip"


def test_wording_does_not_pick_the_model() -> None:
    """A research-shaped ask, a file ask, and a hello all stay on the default."""
    for ask in (
        "Investigate recent battery recycling and write a report",
        "i want you to deeply research the best piezoelectric material",
        "please edit the python file and lint it",
        "search the web for lithium prices",
        "what's the weather today",
        "hey how are you",
        "Write the result as a PDF I can open.",
    ):
        role, reason = _orch().classify_role(ask)
        assert role == "fast", ask
        assert reason == "default", ask
    role, reason = _orch().classify_role(
        "Investigate and write a report on fusion", "fast"
    )
    assert role == "fast"
    assert reason == "default"


def test_switch_roles_sentence_is_the_chip() -> None:
    from arelis.core.orchestrator_shared import match_role_switch

    spoken = "switch roles to research, then I got a good prompt for you to look into"
    assert match_role_switch(spoken) == (
        "research",
        "I got a good prompt for you to look into",
    )
    assert match_role_switch("switch to research") == ("research", "")
    assert match_role_switch("set the role to fast") == ("fast", "")
    assert match_role_switch("switch to research the muon papers") is None
    assert match_role_switch("make it a research room") is None


async def test_switch_roles_sentence_sets_the_chip() -> None:
    from arelis.core.events import Event, EventType

    router = _StubRouter()

    def same_chat_weights(_a: str, _b: str) -> bool:
        return True

    router.same_chat_weights = same_chat_weights  # type: ignore[attr-defined]
    orch = Orchestrator(
        EventBus(),
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        {"workspace": {"roots": ["."]}, "_persona_path": "persona.md"},
        SessionMemory(),
    )
    await orch.on_user_message(
        Event(
            EventType.USER_MESSAGE,
            {
                "text": (
                    "switch roles to research, then I got a good prompt "
                    "for you to look into"
                )
            },
        )
    )
    queued = []
    while not orch.bus._queue.empty():
        queued.append(orch.bus._queue.get_nowait())
    assert orch.router.default_role == "research"
    assert any(
        event.type == EventType.ASSISTANT_DONE
        and "Role set to `research`" in str(event.payload.get("text") or "")
        for event in queued
    )
    assert orch._turn_task is None


def test_comms_bypasses_coder_sticky() -> None:
    from arelis.core.orchestrator import comms_bypasses_sticky

    assert comms_bypasses_sticky("text my wife that I'll be late")
    assert comms_bypasses_sticky(
        "send an email to bob@example.com about dinner: see you at 7"
    )
    assert not comms_bypasses_sticky("how are you tonight")
    assert not comms_bypasses_sticky("please edit the python file and lint it")
