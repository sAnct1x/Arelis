"""Shared chat-wire helpers for the llama.cpp server.

Tool-call chunks arrive either whole or as indexed deltas. Both shapes land
in one list before the arguments are parsed.
"""

from __future__ import annotations

import json
from typing import Any


def same_model(name: str, *candidates: str) -> bool:
    """True if `name` is the same model as any candidate, or a tagged variant.

    `qwen2.5:7b` matches `qwen2.5:7b:latest` and `qwen2.5:7b-instruct`.
    It does not match `qwen2.5:14b`.
    """
    raw = (name or "").strip()
    if not raw:
        return False
    for item in candidates:
        other = (item or "").strip()
        if not other:
            continue
        if raw == other:
            return True
        if raw.startswith(f"{other}:") or other.startswith(f"{raw}:"):
            return True
        if raw.startswith(f"{other}-") or other.startswith(f"{raw}-"):
            return True
    return False


def _new_slot() -> dict[str, Any]:
    return {"type": "function", "function": {"name": "", "arguments": {}}}


def _merge_tool_calls(dst: list[dict[str, Any]], incoming: list[Any]) -> None:
    """Accumulate streamed partial tool_calls into dst.

    Two wire formats have to coexist. One sends each tool call complete in a
    single chunk with no index. OpenAI-compatible endpoints send deltas: one
    chunk carrying the name, then further chunks carrying slices of the
    argument JSON, all tagged with an index.

    When index is absent the two are told apart by whether the chunk names a
    tool. A named chunk starts a new call; an unnamed chunk is an argument
    continuation and belongs to the call already in progress. Appending on every
    unnamed chunk instead, which is what a naive len(dst) fallback does, splits
    one call into several partial ones and can turn a single confirmed write
    into repeated writes.
    """
    for item in incoming:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        idx = item.get("index")
        if idx is None:
            if fn.get("name") or not dst:
                dst.append(_new_slot())
            idx = len(dst) - 1
        while len(dst) <= idx:
            dst.append(_new_slot())

        slot = dst[idx]
        slot_fn = slot.setdefault("function", {"name": "", "arguments": {}})
        if fn.get("name"):
            slot_fn["name"] = fn["name"]
        if "arguments" in fn:
            args = fn["arguments"]
            if isinstance(args, str):
                slot_fn["_args_raw"] = slot_fn.get("_args_raw", "") + args
            elif isinstance(args, dict):
                slot_fn["arguments"] = args
        if item.get("type"):
            slot["type"] = item["type"]


def _finalize_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse accumulated argument text and drop slots that never got a name."""
    out: list[dict[str, Any]] = []
    for call in calls:
        fn = dict(call.get("function") or {})
        raw = fn.pop("_args_raw", None)
        if raw is not None and not fn.get("arguments"):
            try:
                fn["arguments"] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                fn["arguments"] = {"_raw": raw}
        elif isinstance(fn.get("arguments"), str):
            try:
                fn["arguments"] = json.loads(fn["arguments"])
            except json.JSONDecodeError:
                pass
        if not fn.get("name"):
            continue
        if not isinstance(fn.get("arguments"), dict):
            fn["arguments"] = {}
        out.append({"type": call.get("type") or "function", "function": fn})
    return out
