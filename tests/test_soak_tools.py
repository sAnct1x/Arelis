"""Offline production tool-bounce soak (pytest entry)."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.eval.conversation import SOAK_TOOL_NAMES, run_conversation_soak, soak_registry
from arelis.eval.soak_scenarios import limb_catalog_turns, production_bounce_turns


def _cleanup_leftover_soak_pngs() -> None:
    folder = PROJECT_ROOT / "outputs" / "images" / "soak"
    if not folder.is_dir():
        return
    for path in folder.glob("soak_*.png"):
        path.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _no_soak_png_leftovers() -> None:
    _cleanup_leftover_soak_pngs()
    yield
    _cleanup_leftover_soak_pngs()


def test_soak_registry_covers_every_attended_tool(tmp_path: Path) -> None:
    names = soak_registry(image_dir=tmp_path).names()
    missing = sorted(SOAK_TOOL_NAMES - names)
    extra = sorted(names - SOAK_TOOL_NAMES)
    assert not missing, f"soak stubs missing {missing}"
    assert not extra, f"soak stubs extra {extra}"


@pytest.mark.asyncio
async def test_production_tool_bounce_soak_offline(tmp_path: Path) -> None:
    report = await run_conversation_soak(
        production_bounce_turns(),
        soak_id="production_tool_bounce",
        mode="mock",
        fail_fast=False,
        image_dir=tmp_path,
    )
    assert report.ok, report.summary + "\n" + "\n".join(
        f"{t.turn_id}: {t.reasons}" for t in report.turns if not t.ok
    )
    assert len(report.turns) == 12
    tools = [t.tools_called for t in report.turns]
    assert any("send_sms" in x for x in tools)
    assert any("agenda" in x for x in tools)
    assert any("weather" in x for x in tools)
    assert any("image" in x for x in tools)
    assert any("vision" in x for x in tools)
    assert any("send_email" in x for x in tools)
    fanout = next(t for t in report.turns if t.turn_id == "fanout_weather_inbox")
    assert "weather" in fanout.tools_called
    assert "inbox" in fanout.tools_called
    assert any("phase=fanout" in line for line in fanout.thinking_tail)


@pytest.mark.asyncio
async def test_limb_catalog_hits_every_tool(tmp_path: Path) -> None:
    turns = limb_catalog_turns()
    called_expect = {t.expect_tools[0] for t in turns if t.expect_tools}
    missing_script = sorted(SOAK_TOOL_NAMES - called_expect)
    assert not missing_script, f"limb catalog never calls {missing_script}"
    cfg = {
        "skill_tool_subset": False,
        "research_tool_subset": False,
        "chat_fast_path": False,
        "email_force_call": False,
        "sms_force_call": False,
        "agenda_force_call": False,
        "image_force_call": False,
        "weather_force_call": False,
    }
    used: set[str] = set()
    failures: list[str] = []
    # One session per limb so a prior email/SMS draft cannot redirect later tools.
    for turn in turns:
        report = await run_conversation_soak(
            [turn],
            soak_id=f"limb_{turn.id}",
            mode="mock",
            fail_fast=True,
            image_dir=tmp_path,
            agent_cfg=cfg,
        )
        if not report.ok:
            failures.append(
                f"{turn.id}: {report.turns[0].reasons if report.turns else report.summary}"
            )
        if report.turns:
            used.update(report.turns[0].tools_called)
    assert not failures, "\n".join(failures)
    missing = sorted(SOAK_TOOL_NAMES - used)
    assert not missing, f"loop never executed {missing}"
