"""Spoken inspect asks route to a workspace read of her source."""

from __future__ import annotations

from arelis.core.intent_catalog import (
    inspect_read_path,
    looks_like_source_inspect,
    looks_like_source_write,
)
from arelis.core.plan_nudge import select_plan
from arelis.core.preflight import detect_intents

INSPECT_LINES: tuple[tuple[str, str], ...] = (
    ("how do you confirm writes?", "arelis/tools/policy.py"),
    ("how does my confirm gate work?", "arelis/tools/policy.py"),
    ("how does confirm work", "arelis/tools/policy.py"),
    ("where is the Drive strip?", "arelis/ui/panels/drive.py"),
    ("show me the Drive strip", "arelis/ui/panels/drive.py"),
    ("what's in policy.py?", "arelis/tools/policy.py"),
    ("what does tool_subset do?", "arelis/core/tool_subset.py"),
    (
        "read arelis/core/tool_subset.py and tell me what it does",
        "arelis/core/tool_subset.py",
    ),
    (
        "look at the files required for an accurate assessment of the solar system simulation",
        "arelis/physics/engine.py",
    ),
    (
        "how accurate would you say the space simulation is? what are the biggest glaring holes?",
        "arelis/physics/engine.py",
    ),
)

NEGATIVES = (
    "how do toroids relate to physics?",
    "how does pytest work",
    "how does interference work",
    "how do I sign in",
    "what does this pdf",
    "create a pdf",
    "who are you",
    "cite your source",
    "what's your source for that weather number",
    "the confirm gate paused that write",
    "don't mention the confirm gate",
    "email me docs/architecture.md",
    "email me policy.py",
    "What does docs/contract.pdf say about termination?",
    "look at the weather",
    "look at my inbox",
    "how accurate is that forecast",
    "can you even look at that stuff?",
)


def test_spoken_inspect_lines_route_to_workspace_read() -> None:
    for text, path in INSPECT_LINES:
        assert looks_like_source_inspect(text), text
        assert not looks_like_source_write(text), text
        assert inspect_read_path(text) == path, text
        hints = detect_intents(text)
        inspect = [h for h in hints if h.kind == "inspect"]
        assert inspect, text
        assert inspect[0].expected_tools == ("workspace",), text
        assert path in inspect[0].nudge, text
        plan = select_plan(text)
        assert plan is not None, text
        assert plan.id == "inspect", text
        assert plan.steps == ("workspace",), text
        assert path in plan.message, text
        webbed = select_plan(text, skill_ids=["web"])
        assert webbed is not None and webbed.id == "inspect", text
        assert path in (webbed.message or ""), text


def test_fix_confirm_gate_is_a_source_write() -> None:
    text = "fix your confirm gate"
    assert looks_like_source_write(text)
    assert not looks_like_source_inspect(text)
    hints = detect_intents(text)
    kinds = {h.kind for h in hints}
    tools = {t for h in hints for t in h.expected_tools}
    assert kinds & {"inspect_write", "workspace_write"}
    assert "workspace" in tools
    assert "inspect" not in kinds
    plan = select_plan(text)
    assert plan is not None
    assert plan.id == "inspect_write"
    assert plan.steps == ("workspace",)
    assert "write" in plan.message.lower() or "edit" in plan.message.lower()
    assert "Allow" in plan.message


def test_investigate_the_sim_files_is_inspect_not_a_web_report() -> None:
    text = "investigate the solar system simulation files"
    assert looks_like_source_inspect(text)
    plan = select_plan(text)
    assert plan is not None and plan.id == "inspect"
    assert "arelis/physics/engine.py" in plan.message
    assert "research_report" not in plan.steps
    kinds = {h.kind for h in detect_intents(text)}
    assert "inspect" in kinds
    assert "research" not in kinds


def test_solar_assess_fans_out_physics_files() -> None:
    text = (
        "look at the files required for you to give me an accurate "
        "assessment of the solar system simulation"
    )
    assert looks_like_source_inspect(text)
    assert inspect_read_path(text) == "arelis/physics/engine.py"
    hints = detect_intents(text)
    inspect = [h for h in hints if h.kind == "inspect"]
    assert inspect
    nudge = inspect[0].nudge
    assert "arelis/physics/engine.py" in nudge
    assert "arelis/physics/constants.py" in nudge
    assert "arelis/physics/horizons.py" in nudge
    assert "arelis/physics/scene.py" in nudge
    assert "Horizons VECTORS" in nudge
    assert "do not list the workspace root" in nudge.lower()
    plan = select_plan(text)
    assert plan is not None and plan.id == "inspect"
    assert "fanout" in plan.message.lower()
    assert "do not list the workspace root" in plan.message.lower()


def test_inspect_negatives_are_not_source_reads() -> None:
    for text in NEGATIVES:
        assert not looks_like_source_inspect(text), text
        assert not looks_like_source_write(text), text
        kinds = {h.kind for h in detect_intents(text)}
        assert "inspect" not in kinds, text
        assert "inspect_write" not in kinds, text
        plan = select_plan(text)
        assert plan is None or plan.id != "inspect", text
