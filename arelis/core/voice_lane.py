"""First spoken pass: a short no-tool prompt, then a filler and a tool handoff.

Spoken turns can answer from a compact, byte-stable prefix that carries no
tool schemas. If the model signals that it needs a tool, the loop speaks a
short filler and runs the same user turn through the normal tool loop.
Typed chat never uses this path.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from arelis.core.context import context_budget
from arelis.core.prompt_sections import (
    append_clock,
    append_nasa_fact_guidance,
    append_stable_operating_context,
    append_stopped_turn_note,
    append_volatile_operating_context,
)
from arelis.memory.retrieval import memories_prompt_for_turn
from arelis.talk_language import active_reply_language, reply_instruction

NEED_TOOL_MARKER = "NEED_TOOL"
FILLER_EN = "Let me look that up."
FILLER_ZH = "我先查一下。"
# 1-3 short spoken sentences. Enough for a direct answer, not a lecture.
VOICE_LANE_MAX_TOKENS = 160

_VOICE_LANE_EN = (
    "You are Arelis, a local personal research partner, speaking aloud. "
    "Answer in 1-3 short spoken sentences unless they asked for detail, "
    "code, steps, or a list. Their text is a speech transcript: messy, "
    "filled with ah/um, and sometimes wrong on names. Hear what they "
    "meant from the last few turns. Do not correct the transcript and "
    "do not ask them to repeat themselves. "
    "You have no tools on this pass. If you can answer from what you "
    "know, answer now. If you need a tool (weather, a live lookup, "
    "files, calendar, a message, the web, a catalog, a calculation you "
    "should not guess, the desktop, or anything you cannot honestly "
    "know), reply with exactly this token and nothing else:\n"
    f"{NEED_TOOL_MARKER}\n"
    "Never write that token in an ordinary answer. It is not spoken."
)

_VOICE_LANE_ZH = (
    "你是 Arelis，本地的个人研究伙伴，正在出声说话。默认一两句到三句，"
    "除非他们要细节、步骤或推导。他们的文字是语音识别结果，可能有错字和口头语。"
    "按最近几轮理解意思，不要纠正转写，也不要叫他们再说一遍。"
    "这一轮你没有工具。能根据已有知识回答就直接回答。"
    "如果需要工具（天气、实时查询、文件、日历、发消息、网页、星表、"
    "不该口算的计算、桌面，或任何你并不能如实知道的事），只回复这个标记，不要写别的：\n"
    f"{NEED_TOOL_MARKER}\n"
    "普通回答里不要写出这个标记。它不会被读出来。"
)

_TOOL_SHAPED = re.compile(
    r"<tool_call\b|</tool_call>|<function(?:_call)?\b|"
    r"\"name\"\s*:\s*\"[a-z][a-z0-9_]{1,40}\"",
    re.IGNORECASE,
)


def lane_enabled(config: dict[str, Any] | None) -> bool:
    """True only when voice.lane.enabled is explicitly on."""
    voice = (config or {}).get("voice") or {}
    lane = voice.get("lane") if isinstance(voice, dict) else None
    if not isinstance(lane, dict):
        return False
    return bool(lane.get("enabled", False))


def should_run_first_pass(ctx: Any, config: dict[str, Any] | None) -> bool:
    """True for a spoken turn that should try the short no-tool pass."""
    if not lane_enabled(config) or not bool(getattr(ctx, "speak", False)):
        return False
    if bool(getattr(ctx, "expect_tool_round", False)):
        return False
    if bool(getattr(ctx, "research_mode", False)):
        return False
    if getattr(ctx, "staged_files", ()):
        return False
    return True


def should_speak_routed_filler(ctx: Any, config: dict[str, Any] | None) -> bool:
    """True when a spoken turn already knows it will use tools, so skip the probe."""
    if not lane_enabled(config) or not bool(getattr(ctx, "speak", False)):
        return False
    return bool(getattr(ctx, "expect_tool_round", False))


def voice_lane_prompt(language: str | None = None) -> str:
    """Byte-stable first-pass system text for one reply language."""
    if language == "zh":
        return _VOICE_LANE_ZH
    return _VOICE_LANE_EN


def filler_text(config: dict[str, Any] | None = None) -> str:
    """Short line spoken before a tool handoff. Never stored as the turn's answer."""
    if active_reply_language(config) == "zh":
        return FILLER_ZH
    return FILLER_EN


_FENCE_LINE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")


def _strip_trailing_punctuation(text: str) -> str:
    compact = text.strip()
    while compact and unicodedata.category(compact[-1]).startswith("P"):
        compact = compact[:-1].rstrip()
    return compact


def _is_marker_line(line: str) -> bool:
    compact = line.strip().strip("`").strip().strip("*").strip()
    compact = _strip_trailing_punctuation(compact)
    return compact.upper() == NEED_TOOL_MARKER


def _is_fence_line(line: str) -> bool:
    return bool(_FENCE_LINE.match(line.strip()))


def _looks_like_tool_shaped(text: str) -> bool:
    if not text or not _TOOL_SHAPED.search(text):
        return False
    from arelis.core.json_tools import parse_fallback_payload

    parsed = parse_fallback_payload(text, strict=False)
    if parsed and parsed.get("kind") == "tool":
        return True
    return bool(
        re.search(r"<tool_call\b|</tool_call>|<function(?:_call)?\b", text, re.I)
        or re.search(
            r"\"name\"\s*:\s*\"[a-z][a-z0-9_]{1,40}\".{0,200}\"arguments\"",
            text,
            re.I | re.DOTALL,
        )
    )


def first_pass_needs_tool(text: str) -> bool:
    """True when the first-pass reply is the tool signal, never to be spoken."""
    from arelis.core.json_tools import strip_thinking_text

    raw = strip_thinking_text(text or "").strip()
    if not raw:
        return False
    lines = [line for line in raw.splitlines() if line.strip()]
    if lines and _is_marker_line(lines[0]):
        return True
    significant = [line for line in lines if not _is_fence_line(line)]
    if significant and _is_marker_line(significant[0]):
        return True
    if any(_is_marker_line(line) for line in lines) and all(
        _is_marker_line(line) or _looks_like_tool_shaped(line) or _is_fence_line(line)
        for line in lines
    ):
        return True
    return _looks_like_tool_shaped(raw)


def first_pass_system_messages(loop: Any, ctx: Any) -> list[dict[str, str]]:
    """Byte-stable prefix for the first spoken pass. No tool policy, no schemas."""
    language = active_reply_language(loop.config)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": voice_lane_prompt(language)},
    ]
    append_stable_operating_context(
        messages,
        loop,
        active_room=getattr(ctx, "active_room", None),
    )
    lang_note = reply_instruction(loop.config.get("_reply_language"))
    if lang_note:
        messages.append({"role": "system", "content": lang_note})
    from arelis.core.agent_loop import theme_line

    messages.append({"role": "system", "content": theme_line()})
    return messages


def first_pass_turn_tail(loop: Any, ctx: Any) -> list[dict[str, str]]:
    """This-turn lines that trail history, so the prefix stays cacheable."""
    tail: list[dict[str, str]] = []
    stopped = ""
    if loop.config.get("_stopped_ask"):
        stopped = str(loop.config.get("_stopped_ask") or "")
    append_stopped_turn_note(tail, stopped)
    append_nasa_fact_guidance(tail, getattr(ctx, "text", "") or "")
    model = loop.router.model_for(getattr(ctx, "role", None))
    append_volatile_operating_context(
        tail,
        loop,
        role=getattr(ctx, "role", "") or "",
        model=model,
        skill_ids=list(getattr(ctx, "skill_ids", ()) or ()),
    )
    return tail


async def build_first_pass_messages(loop: Any, ctx: Any) -> list[dict[str, Any]]:
    """Prompt for the first spoken pass: short prefix, history, volatile tail."""
    system_messages = first_pass_system_messages(loop, ctx)
    turn_tail = first_pass_turn_tail(loop, ctx)
    retrieved = await memories_prompt_for_turn(
        loop, getattr(ctx, "text", "") or ""
    )
    if retrieved:
        turn_tail.append({"role": "system", "content": retrieved})
    append_clock(turn_tail, loop)
    num_ctx = int(getattr(loop, "_turn_num_ctx", None) or 32768)
    try:
        ratio = float(loop.memory.chars_per_token or 4.0)
    except (TypeError, ValueError):
        ratio = 4.0
    if ratio <= 0:
        ratio = 4.0
    budget = context_budget(
        num_ctx,
        tool_output_chars=0,
        chars_per_token=ratio,
        schema_chars=0,
    )
    return await loop._messages_for_turn(
        system_messages,
        budget,
        ratio,
        getattr(ctx, "role", "fast"),
        user_text=getattr(ctx, "text", "") or "",
        turn_tail=turn_tail,
    )


def system_prefix(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages ahead of the first user line. The cacheable voice-lane prefix."""
    prefix: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "user":
            break
        prefix.append(message)
    return prefix
