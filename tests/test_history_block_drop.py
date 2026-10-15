"""History overflow drops one block, and the side calls do not think.

A tool-heavy chat used to cross history_max_messages after about ten
questions, then shave two or three rows off the front of every later
prompt. That is the edit that makes the prefix cache miss right after
the persona and the tools. The cap and the token budget now drop down
to about half, so the prefix holds for many turns and breaks once.

The fold that should soften a drop was running the chat model with
thinking on, hitting summarize_max_ms, and discarding the summary.
Vision's describe call did the same.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from arelis.tools.vision import VisionTool
from arelis.workspace import WorkspaceRoots

_SUMMARY = "SUMMARY: They kept the plant heights.\nFACTS:\n- NONE"
_SLOW_S = 30.0


def _loop(
    memory: SessionMemory,
    router: Any,
    agent: dict[str, Any],
) -> AgentLoop:
    return AgentLoop(
        EventBus(),
        router,
        ToolRegistry(),
        memory,
        "PERSONA",
        {"agent": agent, "ollama": {"num_ctx": 65536}},
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )


def _extends(previous: list[dict[str, Any]], nxt: list[dict[str, Any]]) -> bool:
    """True when the next prompt still starts with the previous one."""
    return nxt[: len(previous)] == previous


def _stable_runs(prompts: list[list[dict[str, Any]]]) -> list[int]:
    runs: list[int] = []
    length = 1
    for index in range(1, len(prompts)):
        if _extends(prompts[index - 1], prompts[index]):
            length += 1
            continue
        runs.append(length)
        length = 1
    runs.append(length)
    return runs


def _tool_follow(index: int) -> list[dict[str, Any]]:
    """About a dozen prompt rows, the shape that tripped the old cap."""
    marker = f"q{index}"
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "document", "arguments": {"marker": marker}}}
            ],
        },
        {"role": "tool", "tool_name": "document", "content": f"{marker} wrote plants.csv"},
        {"role": "tool", "tool_name": "analyze", "content": f"{marker} mean height 12"},
        {"role": "assistant", "content": f"{marker} calling plot"},
        {"role": "tool", "tool_name": "plot", "content": f"{marker} wrote the chart"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "plot", "arguments": {"marker": marker}}}
            ],
        },
        {"role": "tool", "tool_name": "plot", "content": f"{marker} chart path"},
        {"role": "tool", "tool_name": "document", "content": f"{marker} row dump"},
        {"role": "assistant", "content": f"{marker} reading the table"},
        {"role": "tool", "tool_name": "analyze", "content": f"{marker} last rows"},
    ]


@pytest.mark.asyncio
async def test_tool_heavy_session_keeps_one_prefix_then_drops_a_block() -> None:
    """Many turns share a prefix, then one drop lands near half the cap."""
    cap = 120
    memory = SessionMemory(max_messages=10_000)
    loop = _loop(
        memory,
        _QuietRouter(),
        {
            "history_max_messages": cap,
            "history_min_recent": 6,
            "summarize_skip_slash": True,
        },
    )
    prompts: list[list[dict[str, Any]]] = []
    for index in range(36):
        memory.add("user", f"question {index} plot the plants")
        prompts.append(
            await loop._messages_for_turn(
                [{"role": "system", "content": "PERSONA"}],
                1_000_000,
                4.0,
                "fast",
                user_text="/continue",
            )
        )
        memory.remember_turn_follow(_tool_follow(index))
        memory.add("assistant", f"chart {index} is ready")

    runs = _stable_runs(prompts)
    long_runs = [run for run in runs if run >= 5]
    assert len(long_runs) >= 2, runs
    break_at = next(
        index
        for index in range(1, len(prompts))
        if not _extends(prompts[index - 1], prompts[index])
    )
    assert len(prompts[break_at]) <= (cap // 2) + 8


class _QuietRouter:
    def model_for(self, role: str | None = None) -> str:
        del role
        return "probe-model"

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        if False:
            yield ("token", "")
        raise AssertionError("the prefix test must not fold history")


class _SlowThinkProvider:
    def __init__(self) -> None:
        self.thinks: list[Any] = []

    async def stream_chat(self, model, messages, **kwargs):
        del model, messages
        think = kwargs.get("think", None)
        self.thinks.append(think)
        if think is not False:
            await asyncio.sleep(_SLOW_S)
            yield ("thinking", "still thinking")
            return
        yield ("token", _SUMMARY)


class _SlowThinkRouter:
    def __init__(self) -> None:
        self.provider = _SlowThinkProvider()
        self.active_model = "qwen3.5:9b"
        self.default_keep_alive = "30m"
        self.stream_thinks: list[Any] = []

    def model_for(self, role: str | None = None) -> str:
        del role
        return self.active_model

    async def stream(self, role, messages, **kwargs):
        del role, messages
        think = kwargs.get("think", None)
        self.stream_thinks.append(think)
        if think is not False:
            await asyncio.sleep(_SLOW_S)
            yield ("thinking", "still thinking")
            return
        yield ("token", _SUMMARY)


@pytest.mark.asyncio
async def test_summary_fold_disables_thinking_and_keeps_the_summary() -> None:
    """A slow thinker used to burn summarize_max_ms and drop with no summary."""
    memory = SessionMemory(max_messages=10_000)
    router = _SlowThinkRouter()
    loop = _loop(
        memory,
        router,
        {
            "history_max_messages": 8,
            "history_min_recent": 2,
            "summarize_max_ms": 200,
            "summarize_skip_slash": True,
        },
    )
    for index in range(12):
        memory.add("user", f"question {index} about the plants")
        memory.add("assistant", f"answer {index}")
    messages = await loop._messages_for_turn(
        [{"role": "system", "content": "PERSONA"}],
        1_000_000,
        4.0,
        "fast",
        user_text="what about the plants",
    )
    recorded = router.provider.thinks + router.stream_thinks
    assert recorded == [False]
    assert "plant heights" in memory.summary
    assert "plant heights" in json.dumps(messages)


@pytest.mark.asyncio
async def test_vision_describe_disables_thinking(tmp_path) -> None:
    """The describe call thinks unless told not to, and that costs the turn."""
    from PIL import Image

    path = tmp_path / "paste.png"
    Image.new("RGB", (1837, 1116), (20, 80, 140)).save(path, format="PNG")

    class _Runner:
        def __init__(self) -> None:
            self.think: Any = "missing"

        async def chat_sees_images(self) -> bool:
            return True

        async def run_vision(self, prompt, images_b64, **kwargs):
            del prompt, images_b64
            self.think = kwargs.get("think", None)
            return "a chart of plant heights"

    runner = _Runner()
    tool = VisionTool(WorkspaceRoots.from_paths([str(tmp_path)]), runner)
    result = await tool.run(path=str(path), question="what is on screen")
    assert result.ok
    assert runner.think is False


