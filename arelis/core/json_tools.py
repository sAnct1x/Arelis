from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def strip_thinking_text(text: str) -> str:
    """Remove reasoning markup so it never reaches the chat bubble.

    Three shapes have to be handled, and the third is the one that matters.
    Balanced <think>...</think> is the easy case. A stray closing tag with no
    opener means the stream began mid-thought, so everything before it is
    reasoning. An *unclosed* opener means the model was cut off mid-thought:
    dropping only the tag would publish the entire chain of thought as the
    answer, which is exactly what deepseek-r1 does when it hits a length limit.
    """
    if not text:
        return text
    out = _THINK_BLOCK.sub("", text)

    # Unmatched closing tag: the reasoning ran from the start of the stream.
    close = _THINK_CLOSE.search(out)
    if close and not _THINK_OPEN.search(out[: close.start()]):
        out = out[close.end() :]

    # Unmatched opening tag: reasoning ran to the end and was never closed.
    open_tag = _THINK_OPEN.search(out)
    if open_tag and not _THINK_CLOSE.search(out[open_tag.end() :]):
        out = out[: open_tag.start()]

    out = _THINK_OPEN.sub("", out)
    out = _THINK_CLOSE.sub("", out)
    return out.strip()


class ThinkingStripper:
    """strip_thinking_text applied to a stream, one chunk at a time.

    The whole-message version can look at the text from both ends. A stream
    cannot, and two things go wrong if you ignore that.

    A tag can be split across chunks: "<thi" arrives, then "nk>". Emitting the
    first half immediately would put a stray fragment in the bubble and then
    fail to recognize the tag. So any trailing text that could still turn into a
    tag is held back until the next chunk decides it.

    A closing tag can arrive with no opener, which means the reasoning started
    before the first chunk and everything already emitted was part of it. There
    is no way to un-emit from inside here, so the stripper raises a reset flag
    and the caller retracts what it published.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._inside = False
        self._pending = ""
        self._emitted = False
        self._reset = False

    def feed(self, chunk: str) -> str:
        """Return the visible text in this chunk, holding back partial tags."""
        buffer = self._pending + chunk
        self._pending = ""
        out: list[str] = []
        while buffer:
            if self._inside:
                index = buffer.lower().find(self._CLOSE)
                if index < 0:
                    self._pending = _tag_prefix_suffix(buffer, self._CLOSE)
                    break
                buffer = buffer[index + len(self._CLOSE) :]
                self._inside = False
                continue
            index = buffer.lower().find(self._OPEN)
            close = buffer.lower().find(self._CLOSE)
            if close >= 0 and (index < 0 or close < index):
                # Closing tag with no opener: the stream began mid-thought.
                out.clear()
                if self._emitted:
                    self._reset = True
                    self._emitted = False
                buffer = buffer[close + len(self._CLOSE) :]
                continue
            if index < 0:
                keep = _tag_prefix_suffix(buffer, self._OPEN)
                if keep:
                    self._pending = keep
                    buffer = buffer[: len(buffer) - len(keep)]
                out.append(buffer)
                break
            out.append(buffer[:index])
            buffer = buffer[index + len(self._OPEN) :]
            self._inside = True
        visible = "".join(out)
        if visible:
            self._emitted = True
        return visible

    def flush(self) -> str:
        """Release anything still held once the stream is over.

        Text held inside an unclosed <think> stays dropped, matching what
        strip_thinking_text does with a message that was cut off mid-thought.
        """
        if self._inside:
            self._pending = ""
            return ""
        out, self._pending = self._pending, ""
        return out

    def take_reset(self) -> bool:
        """True once after a closing tag invalidated everything emitted so far."""
        was_set, self._reset = self._reset, False
        return was_set


def _tag_prefix_suffix(text: str, tag: str) -> str:
    """Return the trailing part of text that could be the start of tag."""
    limit = min(len(text), len(tag) - 1)
    for size in range(limit, 0, -1):
        if text[-size:].lower() == tag[:size].lower():
            return text[-size:]
    return ""


def _extract_json_spans(text: str) -> list[tuple[int, int]]:
    """Locate top-level {...} objects, including nested braces.

    Brace counting is string-aware because a quoted brace inside a value, which
    is common in file content being written, would otherwise close the object
    early and produce an unparseable fragment. Spans rather than substrings,
    because strict mode needs to know *where* an object sat in the message.
    """
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(text)):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append((i, j + 1))
                    i = j + 1
                    break
        else:
            # Ran off the end with braces still open: nothing further can parse.
            break
    return out


def _extract_json_objects(text: str) -> list[str]:
    return [text[start:end] for start, end in _extract_json_spans(text)]


def _normalize_tool_dict(data: dict[str, Any]) -> dict[str, Any] | None:
    """Recognize the tool-call and final-answer shapes models actually emit."""
    # Arelis format: {"tool": ..., "args": {...}}
    if isinstance(data.get("tool"), str):
        args = data.get("args") or data.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        return {"kind": "tool", "name": data["tool"], "args": args}

    # OpenAI-style flat call. An args-like key is required: without it a plain
    # {"name": "Vega"} in a research answer would be read as a tool call.
    if isinstance(data.get("name"), str) and (
        "arguments" in data or "args" in data or "parameters" in data
    ):
        args = data.get("arguments") or data.get("args") or data.get("parameters") or {}
        return {"kind": "tool", "name": data["name"], "args": _coerce_args(args)}

    # OpenAI-style nested call: {"function": {"name": ..., "arguments": ...}}
    if isinstance(data.get("function"), dict):
        fn = data["function"]
        if isinstance(fn.get("name"), str):
            args = fn.get("arguments") or fn.get("args") or {}
            return {"kind": "tool", "name": fn["name"], "args": _coerce_args(args)}

    if isinstance(data.get("final"), str):
        return {"kind": "final", "text": data["final"]}
    return None


def _coerce_args(args: Any) -> dict[str, Any]:
    """Arguments arrive as a dict or as a JSON string, depending on the model."""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            # Keep the raw text rather than dropping it: the tool reports a
            # useful argument error and the model can correct itself.
            return {"_raw": args}
    return args if isinstance(args, dict) else {}


def parse_fallback_payload(text: str, *, strict: bool = False) -> dict[str, Any] | None:
    """Parse JSON fallback tool/final payloads from model text.

    Accepts:
      {"tool":"workspace","args":{...}}
      {"name":"workspace","arguments":{...}}
      {"final":"..."}

    strict controls how much of the message has to be JSON, and it is the
    security-relevant knob. Permissive scanning treats any JSON object found
    anywhere in the reply as an instruction, so an answer that merely *discusses*
    a tool call, or shows one in a fenced example, gets executed and the prose
    is discarded. That is a real path from ordinary content to an unintended
    file write.

    strict=True is used while native tool calling is working, where prose is
    usually just prose. It accepts a payload only when the object is the last
    thing in the message. That distinguishes the two cases that actually occur:

        "Here is my request:  {"tool": ...}"        -> a call, executed
        "You could emit {"tool": ...} to do that."  -> an explanation, ignored

    A model announcing a call puts the object last. A model explaining one keeps
    writing afterwards. The rule is not airtight, and an answer that happens to
    end with an example payload would still run, which is why writes stay behind
    the confirm card where the user sees the exact call before it happens.

    strict=False is used once the loop has fallen back to JSON mode, where the
    model was told to emit nothing but that object and scanning anywhere in the
    message is the recovery path for models that wrap it in stray text.
    """
    if not text or not text.strip():
        return None
    cleaned = strip_thinking_text(text)
    stripped = cleaned.strip()

    candidates: list[str] = []
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    fences = list(_FENCE.finditer(cleaned))
    if strict:
        # Only trailing payloads count. A fenced block that closes the message
        # is the same announcement pattern as a bare trailing object.
        if fences and cleaned[fences[-1].end() :].strip() == "":
            candidates.append(fences[-1].group(1).strip())
        spans = _extract_json_spans(cleaned)
        if spans and cleaned[spans[-1][1] :].strip() == "":
            candidates.append(cleaned[spans[-1][0] : spans[-1][1]])
    else:
        candidates.extend(m.group(1).strip() for m in fences)
        candidates.extend(_extract_json_objects(cleaned))

    seen: set[str] = set()
    for raw in candidates:
        if raw in seen:
            continue
        seen.add(raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        normalized = _normalize_tool_dict(data)
        if normalized:
            return normalized
    return None


def extract_native_tool_calls(calls: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Normalize Ollama tool_calls into (name, args) pairs, dropping duplicates.

    Identical calls in one round are dropped rather than executed twice. A model
    repeating itself within a single response is always a glitch, never intent,
    and executing it twice means two file writes or two ComfyUI jobs from one
    confirm. Distinct calls to the same tool (two different paths) are kept.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for call in calls:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        if not name:
            continue
        args = _coerce_args(fn.get("arguments") or {})
        fingerprint = name + "\x00" + json.dumps(args, sort_keys=True, default=str)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        out.append((name, args))
    return out
