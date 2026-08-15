from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from arelis.core.context import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

# Argument names worth recording in a trace line, most specific first.
_TRACE_KEYS = ("path", "url", "prompt", "query")
_MAX_TRACE_TARGET = 80
_MAX_TRACE_NOTE = 400


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

    When sink is set, each add/summary/fact is written through immediately so a
    crash loses at most the turn in progress. Persistence is not this class's
    job when sink is None — that is how scheduled runs stay isolated.
    """

    messages: list[ChatMessage] = field(default_factory=list)
    max_messages: int = 40
    max_tokens: int | None = None
    chars_per_token: float = DEFAULT_CHARS_PER_TOKEN
    # Folded-away turns, injected as a pinned system block. Kept here rather
    # than in the message list so a later fit cannot drop the summary itself.
    summary: str = ""
    # Durable-seeming claims extracted during summarization. The store records
    # them as pending; nothing becomes active without a later review click.
    pending_facts: list[str] = field(default_factory=list)
    sink: MemorySink | None = None

    def add(self, role: str, content: str, note: str = "") -> None:
        self.messages.append(ChatMessage(role=role, content=content, note=note))
        self._trim()
        if self.sink is not None:
            self.sink.on_message(role, content, note)

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

    def as_ollama(self, *, include_notes: bool = True) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for m in self.messages:
            if m.role == "notice":
                continue
            content = m.content
            if include_notes and m.note:
                content = f"{m.content}\n\n{m.note}"
            out.append({"role": m.role, "content": content})
        return out

    def drop_prompt_prefix(self, n: int) -> None:
        """Drop the oldest *n* prompt-visible messages. Notices stay.

        ``as_ollama`` skips role ``notice``, so a raw ``messages[n:]`` slice
        drifts whenever an inbound SMS line sits in the working set — it can
        delete the previous user/assistant turn or leave a stale prefix.
        The archive sink already has those rows; this only shrinks the
        in-process list so the next turn does not re-drop the same prefix.
        """
        if n <= 0:
            return
        kept: list[ChatMessage] = []
        skipped = 0
        for message in self.messages:
            if message.role == "notice":
                kept.append(message)
                continue
            if skipped < n:
                skipped += 1
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
                    )
                )
        self.summary = summary
        self.pending_facts.clear()

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
            parts.append(str(resolved_path)[:_MAX_TRACE_TARGET])
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
