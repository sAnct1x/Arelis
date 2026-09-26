"""The assembled prompt, pinned. Changing it should cost a conscious edit.

Prefix caching is the reason. The system prompt is built static-part-first and
byte-identical across turns, with the volatile lines appended at the end, so
the model can reuse the prefill. Move one byte near the front and every turn
pays the prefill again, forever, on a 12 GB card — and nothing fails, nothing
logs, the only symptom is that she got slower and nobody can say when.

That is not a thing a unit test catches. `prepare_turn` was just split from 529
lines into named sections, and the only way to know it moved nothing was to
capture the output before and after and diff it. This file keeps that check
instead of throwing it away with the scratch file.

If a diff here is deliberate, read it first — the golden is stored indented so
review sees the actual prompt change — then regenerate:

    python -m pytest tests/test_prompt_golden.py --regenerate-prompt-golden

and say in the commit message what moved and why it was worth the cache.

Everything clock-, machine- or disk-dependent is stubbed at the module that
defines it rather than at `prompt_sections`, so this keeps working if the
sections are rearranged again.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import arelis.contacts
import arelis.core.episodes
import arelis.core.lessons
import arelis.core.loop_helpers
import arelis.core.plan_nudge
import arelis.core.prompt_sections as sections
import arelis.core.skills
import arelis.core.turn_prepare as subject
import arelis.core.world_state
import arelis.look_scratch
import arelis.profile
import arelis.talk_language
from arelis.core import agent_loop as agent_loop_mod
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import prepare_turn
from arelis.tools.base import ToolRegistry

GOLDEN = Path(__file__).parent / "prompt_golden.json"


class _Router:
    active_model = None

    def model_for(self, role=None):
        return "probe-model"


class _Tool:
    description = "probe tool"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name


class _Named:
    def __init__(self, line: str) -> None:
        self.line = line

    def prompt_line(self) -> str:
        return self.line


class _Room:
    name = "probe-room"
    tools: list[str] = []
    spec = SimpleNamespace(skills=[])

    def prompt_block(self) -> str:
        return "ROOM"


TOOLS = (
    "weather",
    "user_location",
    "web_search",
    "scrape",
    "web_fetch",
    "send_sms",
    "send_email",
    "contacts",
    "agenda",
    "calculator",
)

# text, stopped_ask, and the two flags that change the shape of the prompt.
CASES = (
    ("plain", False, False, False, "hello", ""),
    ("rich-spoken", True, True, False, "hello", "old ask"),
    ("weather", False, False, True, "what's the weather tomorrow?", ""),
    (
        "current-web",
        False,
        False,
        True,
        "find the current price of gold and verify it",
        "",
    ),
    ("sms", False, False, True, "text Brian that I'm running late", ""),
)


# name -> (sentinel, modules that must be patched).
#
# The modules matter and the list is not padding. `prompt_sections` does
# `from arelis.core.agent_loop import now_line`, which binds the function object
# at import time, so patching the module that *defines* it changes nothing here.
# The first draft of this file did exactly that, and the golden it produced had
# a live wall clock in it — green on the minute it was written and broken by the
# next one. Both ends are patched now, and `test_every_stub_took` is what makes
# sure this table has not silently stopped matching the imports.
_STUBS: tuple[tuple[str, object, tuple], ...] = (
    ("now_line", lambda: "NOW", (agent_loop_mod, sections)),
    (
        "standing_profile_prompt_line",
        lambda **_: "PROFILE",
        (arelis.profile, sections),
    ),
    ("contacts_prompt_line", lambda: "CONTACTS", (arelis.contacts, sections)),
    (
        "world_state_prompt_line",
        lambda *a, **k: "WORLD",
        (arelis.core.world_state, sections),
    ),
    (
        "episodes_prompt_line",
        lambda *a, **k: "EPISODES",
        (arelis.core.episodes, sections),
    ),
    ("select_plan", lambda *a, **k: None, (arelis.core.plan_nudge, sections)),
    ("select_lessons", lambda **_: ["lesson"], (arelis.core.lessons, sections)),
    ("format_lessons", lambda _l: "LESSONS", (arelis.core.lessons, sections)),
    (
        "_wants_project_context",
        lambda **_: True,
        (agent_loop_mod, sections),
    ),
    (
        "select_skill_ids_detailed",
        lambda *a, **k: (("probe",), False),
        (arelis.core.skills, subject),
    ),
    ("reply_instruction", lambda _l: "LANGUAGE", (arelis.talk_language,)),
    ("clear_look_pending", lambda: None, (arelis.look_scratch,)),
    ("hold_look_files", lambda _f: None, (arelis.look_scratch,)),
    ("keep_look_files", lambda _t: [], (arelis.look_scratch,)),
)

# Sentinels that must show up in the captured prompt if the stubs bound.
_MUST_APPEAR = ("NOW", "PROFILE", "CONTACTS", "WORLD", "LESSONS")


@pytest.fixture
def pinned(monkeypatch):
    """Stub every line that would otherwise differ between two runs."""
    for name, stub, modules in _STUBS:
        for module in modules:
            if hasattr(module, name):
                monkeypatch.setattr(module, name, stub)


def _loop(*, speak: bool, rich: bool, preflight: bool) -> AgentLoop:
    config: dict = {
        "agent": {
            "chat_fast_path": True,
            "intent_preflight": preflight,
            "lessons": True,
            "max_rounds": 4,
        },
        "ollama": {"num_ctx": 4096},
        "_speak_replies": speak,
        "_reply_language": "probe",
    }
    if rich:
        config["_workspace"] = _Named("WORKSPACE")
        config["_rooms"] = SimpleNamespace(active=_Room())
        config["_location"] = _Named("LOCATION")
    registry = ToolRegistry()
    for name in TOOLS:
        registry.register(_Tool(name))  # type: ignore[arg-type]
    loop = AgentLoop(
        EventBus(),
        _Router(),  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "PERSONA",
        config,
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )
    loop._active_facts_line = lambda: "FACTS"  # type: ignore[method-assign]
    return loop


async def _capture_async() -> list[dict]:
    rows = []
    for name, speak, rich, preflight, text, stopped in CASES:
        loop = _loop(speak=speak, rich=rich, preflight=preflight)
        ctx = await prepare_turn(loop, text, "fast", stopped_ask=stopped)
        assert ctx is not None, f"{name}: prepare_turn returned None"
        rows.append(
            {
                "name": name,
                "messages": ctx.messages,
                "expected": sorted(loop._expected_tools),
                "expect_tool_round": ctx.expect_tool_round,
                "num_ctx": loop._turn_num_ctx,
            }
        )
    return rows


def _capture() -> list[dict]:
    return asyncio.run(_capture_async())


def _blob(rows) -> str:
    return json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_every_stub_took(pinned) -> None:
    """A stub that quietly fails to bind is worse than no stub at all.

    It does not error. It produces a golden with a wall clock baked into it,
    which passes on the minute it was generated and fails the next morning for
    a reason that looks nothing like the cause. Rebind the imports and this is
    the test that notices, instead of a confusing red suite tomorrow.
    """
    blob = _blob(_capture())
    for sentinel in _MUST_APPEAR:
        assert sentinel in blob, (
            f"{sentinel!r} is missing, so its stub did not bind — check the "
            "module list in _STUBS against the imports in prompt_sections.py"
        )
    for leak in ("Eastern", "Daylight", "Standard Time", "2026", "2027"):
        assert leak not in blob, (
            f"{leak!r} reached the golden: something volatile is unstubbed and "
            "this file would start failing on its own"
        )


def test_the_assembled_prompt_has_not_moved(pinned, request) -> None:
    rows = _capture()
    if request.config.getoption("--regenerate-prompt-golden", default=False):
        GOLDEN.write_text(_blob(rows), encoding="utf-8")
        pytest.skip("regenerated tests/prompt_golden.json")
    assert GOLDEN.exists(), "run with --regenerate-prompt-golden to create it"
    assert _blob(rows) == GOLDEN.read_text(encoding="utf-8"), (
        "the assembled prompt changed. If that was deliberate, read the diff — "
        "a change near the front of the system prompt costs the prefix cache on "
        "every turn from now on — then regenerate with "
        "--regenerate-prompt-golden and say in the commit what moved."
    )


def test_the_static_prefix_is_first_and_identical_across_every_case(pinned) -> None:
    """The cacheable part must not vary with what was asked.

    This is the property prefix caching actually depends on, and it is not
    implied by the golden above: five cases could each be stable run to run and
    still disagree with each other, which caches nothing.
    """
    rows = _capture()
    heads = {r["messages"][0]["content"] for r in rows}
    assert heads == {"PERSONA"}, (
        f"case-dependent content reached the front of the prompt: {heads}"
    )
