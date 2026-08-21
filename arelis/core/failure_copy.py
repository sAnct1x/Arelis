"""What a person reads when something fails, as opposed to what a model reads.

``arelis.llm.errors`` already does this for Ollama: chat gets a short instruction,
the exception and the URL go to Thinking. Two paths never got the same treatment.

The orchestrator's last line of defence published
``f"Turn failed: {exc.__class__.__name__}: {exc}"``, which the UI put straight in
the transcript — so the worst moment the app has produced the least human sentence
it could, ``Turn failed: ConnectError: [Errno 11001] getaddrinfo failed``.

Failed tool output went to chat verbatim, up to 500 characters. That was a
deliberate choice and half right: "Not a file: C:/typo.csv" is exactly what the
user needs, and hiding it made a wrong path look like a silent no-op. What it did
not anticipate is that tool failures are written *for the model* — the analyze tool
now answers a bad file type with "Call vision(path=…) for an image", which is an
instruction to a 7B appearing in a human's chat window.

So the rule here is not "hide the output". It is: pass through what a person can
act on, and swap out anything addressed to the model. Detail is never lost — it
goes to Thinking and Workspace either way.
"""

from __future__ import annotations

import re

TURN_FAILED_NOTICE = (
    "Something went wrong mid-turn, so I stopped rather than guess. "
    "The details are in Thinking (Ctrl+1). Try again, or rephrase."
)

# Sentences aimed at the model. A tool that says "Call vision(path=…)" or
# "Rejected: `calculator` takes none of…" is mid-conversation with the 7B, and
# repeating that to the user reads as the app talking to itself.
_MODEL_DIRECTED = re.compile(
    r"(?i)("
    r"^rejected:|"
    r"\bcall\s+\w+\(|"
    r"\bcall\s+(?:the\s+)?\w+\s+tool\b|"
    r"\bdo not\s+(?:call|invent|guess|quote|scrape)\b|"
    r"\bwith its own arguments\b|"
    r"\bintent preflight\b|"
    r"\ballow still applies\b"
    r")"
)

# Instruction footers on a successful tool result. Strip only when that result
# is about to become chat because Qwen left the wrap-up empty.
_SUCCESS_FOOTER = re.compile(
    r"(?i)("
    r"summarize these events|"
    r"do not invent(?:\s+events)?|"
    r"do not quote(?:\s+(?:event\s+ids|google/outlook))|"
    r"do not quote event ids"
    r")"
)

_WORKSPACE_LISTING_LINE = re.compile(r"(?m)^\[(?:dir|file)\]\s")

# Human copy for the tools whose failures reach the transcript, used when the raw
# output turns out to be model-directed. Keyed by tool name.
_TOOL_NOTICES: dict[str, str] = {
    "analyze": (
        "That file is not a spreadsheet, so I could not read it as a table. "
        "I will try the right reader for it."
    ),
    "workspace": "I could not read that file. The path is in Workspace.",
    "image": "Image generation failed. The details are in Workspace.",
    "doc_extract": "I could not read that PDF. The details are in Workspace.",
    "document": "I could not write that file. The details are in Thinking.",
    "vision": "I could not open that image.",
}

_GENERIC_TOOL_NOTICE = "`{tool}` did not complete. The details are in Thinking."

# Long enough for "Not a file: <a real Windows path>", short enough that a stack
# trace or a page of scraped text cannot land in the transcript.
_MAX_PASSTHROUGH = 240


_ERRNO_PREFIX = re.compile(r"^\[(?:Errno|WinError)\s*-?\d+\]\s*")


def plain_reason(exc: BaseException) -> str:
    """The readable half of an exception: no class name, no errno bracket.

    ``open failed: [Errno 13] Permission denied: 'C:/x'`` becomes
    ``Permission denied: 'C:/x'``. The refusal itself is usually the useful part —
    a path outside the workspace roots, a file held open by something else — so
    this trims the machine framing rather than replacing the sentence.
    """
    text = str(exc).strip()
    text = _ERRNO_PREFIX.sub("", text)
    if not text:
        return type(exc).__name__
    if len(text) > _MAX_PASSTHROUGH:
        text = text[:_MAX_PASSTHROUGH].rstrip() + "…"
    return text[0].upper() + text[1:] if text[:1].islower() else text


def turn_failed_notice(exc: BaseException) -> tuple[str, str]:
    """Return (chat copy, Thinking detail) for an unhandled turn failure.

    An Ollama exception that reaches this far is still an Ollama exception, so it
    keeps the copy that names the chip in the title bar rather than the generic
    line — the user's next action is different.
    """
    detail = f"{type(exc).__name__}: {exc}"
    try:
        import httpx

        from arelis.llm.errors import classify_ollama_failure

        if isinstance(exc, (httpx.HTTPError, httpx.NetworkError, httpx.TimeoutException)):
            failure = classify_ollama_failure(exc)
            return failure.chat, failure.detail
    except Exception:
        # Copy is not worth an exception inside the handler of an exception.
        pass
    return TURN_FAILED_NOTICE, detail


def is_model_directed(text: str) -> bool:
    """True when this sentence is talking to the model, not to the user."""
    return bool(_MODEL_DIRECTED.search((text or "").strip()))


def tool_failure_notice(tool: str, output: str) -> str:
    """One line a person can act on, for a tool that failed.

    Passes the tool's own first line through when it is plain — "Not a file:
    C:/typo.csv" is the whole answer and swapping it for something vaguer would
    undo the reason this was ever shown. Substitutes human copy when the line is
    addressed to the model, or when there is nothing to show.
    """
    name = (tool or "").strip() or "that tool"
    first = ""
    for line in (output or "").splitlines():
        if line.strip():
            first = line.strip()
            break

    if not first or is_model_directed(first) or is_model_directed(output or ""):
        return _TOOL_NOTICES.get(name, _GENERIC_TOOL_NOTICE.format(tool=name))
    if len(first) > _MAX_PASSTHROUGH:
        return _TOOL_NOTICES.get(name, _GENERIC_TOOL_NOTICE.format(tool=name))
    return first


def _strip_success_footers(text: str) -> str:
    """Drop model-only instruction lines; keep the person-facing body."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        if _SUCCESS_FOOTER.search(line):
            continue
        if is_model_directed(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def chat_followup_from_tool(tool: str, output: str) -> str:
    """Person-facing copy when the model leaves chat empty after a tool.

    The model still sees the raw tool result (including instruction footers).
    This path is only the last-resort chat line.
    """
    body = (output or "").strip()
    name = (tool or "").strip()
    if not body:
        return (
            "The tool finished, but I could not write a follow-up. "
            "Send the same ask again."
        )
    listing = _WORKSPACE_LISTING_LINE.search(body) or body.lstrip().startswith(
        ("[dir]", "[file]")
    )
    if name == "workspace" and listing:
        return "That listing is in Workspace."
    if listing and name in {"", "workspace"}:
        return "That listing is in Workspace."
    cleaned = _strip_success_footers(body)
    if not cleaned:
        if name == "agenda":
            return "No events in this window."
        return "The tool finished. The details are in Workspace."
    if len(cleaned) > 1600:
        cleaned = cleaned[:1597].rstrip() + "…"
    return cleaned


__all__ = [
    "TURN_FAILED_NOTICE",
    "chat_followup_from_tool",
    "is_model_directed",
    "plain_reason",
    "tool_failure_notice",
    "turn_failed_notice",
]
