from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from arelis.core.context import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

# Stop/Esc used to hide the whole user turn from the next prompt. That kept a
# cancelled "text my wife" from becoming the next SMS body, but it also erased
# a cancelled homework dump — she then said the derivation was not in the
# session while it was still on screen. Sends stay redacted; other asks stay
# visible and marked stopped.
_STOPPED_NOTE = (
    "[Stopped. Visible in chat. Do not resume unless they clearly ask to continue.]"
)
_STOPPED_SEND_NOTE = (
    "[Stopped a send. Do not send it. They cancelled that message.]"
)
_PHONE_IN_ASK = re.compile(r"(?:\+?1[-.\s]*)?\b\d{3}[-.\s]*\d{3}[-.\s]*\d{4}\b")
_SEND_ASK_START = re.compile(
    r"(?i)^\s*(?:please\s+)?(?:text|sms|imessage|email|mail)\s+"
)
_SEND_ASK_VERB = re.compile(
    r"(?i)\bsend\s+(?:an?\s+)?(?:text|sms|email|mail|message)\b"
)

# Argument names worth recording in a trace line, most specific first.
_TRACE_KEYS = ("path", "url", "prompt", "query")
_MAX_TRACE_TARGET = 80
_MAX_TRACE_NOTE = 400
_STOPPED_PREVIEW = 1200


def _cancelled_was_send(text: str) -> bool:
    raw = text or ""
    if _PHONE_IN_ASK.search(raw):
        return True
    if _SEND_ASK_START.search(raw):
        return True
    return bool(_SEND_ASK_VERB.search(raw))


def _stopped_prompt_content(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    if _cancelled_was_send(raw):
        return _STOPPED_SEND_NOTE
    preview = " ".join(raw.split())
    if len(preview) > _STOPPED_PREVIEW:
        preview = preview[: _STOPPED_PREVIEW - 1] + "…"
    return f"{_STOPPED_NOTE}\n{preview}"


class MemorySink(Protocol):
    """Optional write-through target for SessionMemory.

    The UI and CLI attach the SQLite store. The job runner passes nothing, so
    scheduled turns neither read nor pollute the archive by construction.
    """

    def on_message(self, role: str, content: str, note: str = "") -> None: ...

    def on_summary(self, text: str) -> None: ...

    def on_pending_fact(self, text: str) -> None: ...


@dataclass
class ChatMessage:
    role: str
    content: str
    # Context-only suffix, never shown in the chat. Used for the tool trace: the
    # model needs to know a file was written, the user already watched it happen.
    note: str = ""
    # Stop/Esc: keep the bubble in History. The next prompt sees a stopped
    # stub (sends redacted) so a cancelled ask can still be referred to.
    cancelled: bool = False
    # Per-turn system lines that sat immediately before this message.
    # Replay only. Not written through the archive, so the transcript never
    # shows them. Dropped when this message is trimmed.
    prompt_before: tuple[dict[str, Any], ...] = ()
    # Tool calls, tool results, and the tool-round note that followed this
    # message in the last request of its turn. Same rules as prompt_before.
    prompt_after: tuple[dict[str, Any], ...] = ()


@dataclass
class SessionMemory:
    """Conversation history for one session, held in memory only.

    Scope is deliberately narrow: user messages, final assistant answers, and a
    one-line trace of the tools each turn used. Chat notices (inbound SMS lines
    shown in the transcript) are stored as role ``notice`` so they survive
    restart; they are painted in chat on load and omitted from the model prompt.
    Tool results stay in the agent loop's local message list and are discarded
    when the turn ends, which keeps a 14000-char file read from occupying the
    context for the rest of the session. The trace is what makes "now edit that
    file" resolvable without paying that cost, since it carries the path but not
    the contents.

    Trimming is by message count and, when max_tokens is set, by estimated
    tokens, whichever binds first. That alone is not enough to protect the
    persona: Ollama still drops overflow from the front of the prompt, and
    system messages are assembled ahead of this history. fit_messages in the
    agent loop is what pins those; this class only keeps its own list short.

    ``max_messages`` must be built from ``agent.history_max_messages``, use
    :meth:`from_config`. Both numbers bound the same history, and the tighter
    one wins, so a default here that disagrees with config silently overrides
    it. That was a real bug: this defaulted to 40 while config said 120, so the
    agent loop's cap could never fire and the oldest turns were deleted here
    instead, quietly, with no summary and no telemetry, while the loop's
    careful fold-instead-of-forget path sat unreachable behind it.

    When sink is set, each add/summary/fact is written through immediately so a
    crash loses at most the turn in progress. Persistence is not this class's
    job when sink is None, that is how scheduled runs stay isolated.
    """

    messages: list[ChatMessage] = field(default_factory=list)
    # Matches agent.history_max_messages in default.yaml. See the class docstring
    # for why a smaller number here is not a safe default but a silent override.
    max_messages: int = 120
    max_tokens: int | None = None
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN
    # Folded-away turns, injected as a pinned system block. Kept here rather
    # than in the message list so a later fit cannot drop the summary itself.
    summary: str = ""
    # Durable-seeming claims extracted during summarization. The store records
    # them as pending; nothing becomes active without a later review click.
    pending_facts: list[str] = field(default_factory=list)
    sink: MemorySink | None = None

    @classmethod
    def from_config(
        cls, config: dict[str, Any], *, sink: MemorySink | None = None
    ) -> SessionMemory:
        """Build with the working set bounded by the configured history cap."""
        agent = config.get("agent") or {}
        try:
            cap = int(agent.get("history_max_messages", 0) or 0)
        except (TypeError, ValueError):
            cap = 0
        memory = cls(sink=sink)
        if cap > 0:
            memory.max_messages = cap
        return memory

    def remember_turn_block(self, block: list[dict[str, Any]]) -> None:
        """Keep this turn's system lines on the latest user message."""
        for message in reversed(self.messages):
            if message.role != "user":
                continue
            message.prompt_before = tuple(dict(item) for item in block)
            return

    def remember_turn_follow(self, follow: list[dict[str, Any]]) -> None:
        """Keep the tool round that followed the latest user message."""
        for message in reversed(self.messages):
            if message.role != "user":
                continue
            message.prompt_after = tuple(copy.deepcopy(item) for item in follow)
            return

    def add(self, role: str, content: str, note: str = "") -> None:
        self.messages.append(ChatMessage(role=role, content=content, note=note))
        self._trim()
        if self.sink is not None:
            self.sink.on_message(role, content, note)

    def mark_last_user_cancelled(self) -> None:
        """Tag the latest user turn stopped. Bubble stays; prompt gets a stub."""
        for message in reversed(self.messages):
            if message.role == "user":
                message.cancelled = True
                return

    def set_summary(self, text: str) -> None:
        self.summary = text
        if self.sink is not None and text:
            self.sink.on_summary(text)

    def add_pending_fact(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned or cleaned in self.pending_facts:
            return
        self.pending_facts.append(cleaned)
        if self.sink is not None:
            self.sink.on_pending_fact(cleaned)

    def _own_row(
        self, message: ChatMessage, *, include_notes: bool
    ) -> dict[str, Any] | None:
        if message.cancelled:
            content = _stopped_prompt_content(message.content)
            if not content:
                return None
            return {"role": message.role, "content": content}
        content = message.content
        if include_notes and message.note:
            content = f"{message.content}\n\n{message.note}"
        return {"role": message.role, "content": content}

    def _rows_for(
        self,
        message: ChatMessage,
        *,
        include_notes: bool,
        skip_before: bool = False,
    ) -> list[dict[str, Any]]:
        if message.role == "notice":
            return []
        rows: list[dict[str, Any]] = []
        if not skip_before:
            rows.extend(dict(item) for item in message.prompt_before)
        own = self._own_row(message, include_notes=include_notes)
        if own is not None:
            rows.append(own)
        rows.extend(copy.deepcopy(item) for item in message.prompt_after)
        return rows

    def as_ollama(
        self, *, include_notes: bool = True, include_latest_block: bool = True
    ) -> list[dict[str, Any]]:
        """Prompt rows. The latest user block can be omitted when the caller pins it."""
        latest_user = None
        if not include_latest_block:
            for index in range(len(self.messages) - 1, -1, -1):
                if self.messages[index].role == "user":
                    latest_user = index
                    break
        out: list[dict[str, Any]] = []
        for index, message in enumerate(self.messages):
            out.extend(
                self._rows_for(
                    message,
                    include_notes=include_notes,
                    skip_before=index == latest_user,
                )
            )
        return out

    def drop_prompt_prefix(self, n: int) -> None:
        """Drop the oldest *n* prompt-visible messages. Notices stay.

        ``as_ollama`` skips role ``notice``, so a raw ``messages[n:]`` slice
        drifts whenever an inbound SMS line sits in the working set, it can
        delete the previous user/assistant turn or leave a stale prefix.
        The archive sink already has those rows; this only shrinks the
        in-process list so the next turn does not re-drop the same prefix.
        """
        if n <= 0:
            return
        # Count the rows as_ollama would emit. A turn note rides on its user
        # message, so it drops with that message and is not split in half.
        kept: list[ChatMessage] = []
        skipped = 0
        dropping = True
        for message in self.messages:
            if message.role == "notice":
                kept.append(message)
                continue
            if dropping:
                skipped += len(self._rows_for(message, include_notes=True))
                if skipped >= n:
                    dropping = False
                continue
            kept.append(message)
        self.messages = kept

    def hydrate(
        self,
        messages: list[ChatMessage] | list[dict[str, Any]],
        *,
        summary: str = "",
    ) -> None:
        """Replace the in-process working set from the archive.

        Does not write through the sink: these rows are already on disk, and
        re-appending them would duplicate every loaded turn.

        The result is trimmed like any other growth. ``get_messages`` returns a
        whole session with no limit, so restoring a months-old room would
        otherwise load every message ever sent into the working set and hand the
        next prompt build a history far past the cap.
        """
        self.messages.clear()
        for item in messages:
            if isinstance(item, ChatMessage):
                self.messages.append(item)
            else:
                self.messages.append(
                    ChatMessage(
                        role=str(item.get("role") or "user"),
                        content=str(item.get("content") or ""),
                        note=str(item.get("note") or ""),
                        cancelled=bool(item.get("cancelled")),
                    )
                )
        self.summary = summary
        self.pending_facts.clear()
        self._trim()

    def clear(self) -> None:
        self.messages.clear()
        self.summary = ""
        self.pending_facts.clear()

    def _trim(self) -> None:
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]
        if self.max_tokens is None:
            return
        while len(self.messages) > 1 and self._token_count() > self.max_tokens:
            self.messages.pop(0)

    def _token_count(self) -> int:
        total = 0
        for message in self.messages:
            text = f"{message.content}\n\n{message.note}" if message.note else message.content
            total += estimate_tokens(text, chars_per_token=self.chars_per_token)
            for extra in (*message.prompt_before, *message.prompt_after):
                total += estimate_tokens(
                    str(extra.get("content") or ""),
                    chars_per_token=self.chars_per_token,
                )
        return total


def tool_trace_entry(
    name: str,
    args: dict[str, Any],
    ok: bool,
    *,
    resolved_path: str | None = None,
) -> str:
    """One line describing a call, for the memory trace.

    Only the argument that identifies the target is kept. A write's content or a
    scrape's returned text would defeat the point, which is to remember what was
    touched without carrying the payload into every later turn.

    resolved_path wins over args["path"] so multi-root sessions store a
    qualified identity that still points at the same file after a project switch.
    """
    parts = [name]
    action = str(args.get("action") or "").strip()
    if action:
        parts.append(action)
    for key in _TRACE_KEYS:
        if key == "path" and resolved_path:
            parts.append(str(resolved_path)[:240])
            break
        value = args.get(key)
        if value:
            parts.append(str(value)[:_MAX_TRACE_TARGET])
            break
    if not ok:
        parts.append("(failed)")
    return " ".join(parts)


def tool_trace_note(trace: list[str]) -> str:
    """Compact record of a turn's tool use, attached to the assistant message.

    Without this, "now edit that file" cannot be answered: memory keeps only the
    user's words and the final answer, so the path Arelis just wrote to is gone
    by the next turn unless she happened to name it in her reply. The note is
    capped because it rides along in the context on every turn after this one.
    """
    if not trace:
        return ""
    joined = "; ".join(trace)
    if len(joined) > _MAX_TRACE_NOTE:
        joined = joined[: _MAX_TRACE_NOTE - 1] + "…"
    return f"[tools used this turn: {joined}]"


def tool_passthrough_note(tool: str) -> str:
    """Mark an assistant turn that is a tool result rather than her words.

    When the model returns nothing after a tool succeeds, the turn still has to
    end with something. Prefer a plain-language fallback; only mark passthrough
    when the bubble still carries the tool's own prose (weather, agenda
    receipt). `_finish` then writes it to memory as an assistant turn, and
    from the next turn on it is indistinguishable from something she composed.

    That compounds. A pasted JSON body or a column of numbers becomes an
    example of how she talks, and the model reads its own history as a style
    guide. Whatever shape leaked through once gets imitated.

    So the bubble keeps the result and the note says where it came from. It
    rides into the next prompt the same way the stopped-turn note does.
    """
    name = (tool or "").strip()
    named = f" from {name}" if name else ""
    return (
        f"[The line above is raw tool output{named}, not her own words, the "
        "model returned nothing after the call. Do not treat it as an example "
        "of how she writes.]"
    )
