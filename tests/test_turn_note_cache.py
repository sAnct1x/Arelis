"""#278: a note Arelis adds mid-turn must not render as a new question.

The Qwen template drops the thinking of every tool round before the last
plain user row. A plain note re-rendered the earlier rounds, so llama-server
could not reuse its prompt cache and prefilled them again.
"""

from __future__ import annotations

import pytest

from arelis.core.turn_prepare import prepare_turn
from arelis.llm.llamacpp import _wire_messages
from tests.test_prompt_cache_r2 import _loop


@pytest.mark.asyncio
async def test_a_mid_turn_note_keeps_the_earlier_rounds_thinking() -> None:
    ctx = await prepare_turn(_loop(), "what's the weather tomorrow", "fast")
    assert ctx is not None
    call = {"function": {"name": "weather", "arguments": {}}}
    ctx.messages += [
        {"role": "assistant", "content": "", "reasoning_content": "Check it.", "tool_calls": [call]},
        {"role": "tool", "content": "Mild.", "tool_name": "weather"},
        {"role": "user", "content": "Now write the answer in words."},
    ]
    wired = _wire_messages(ctx.messages)
    assert wired[-1]["content"] == "<tool_response>\nNow write the answer in words.\n</tool_response>"
    assert wired[-3]["reasoning_content"] == "Check it."
