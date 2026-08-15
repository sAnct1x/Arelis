"""Explicit durable facts, preferences, project decisions, and episodes.

risk=write so remember / prefer / decide / episode / forget go through the
confirm card. A wrong permanent fact or preference poisons every future answer,
which is why the gate is a capability click rather than a prompt instruction.
Proposed facts from the rolling summary are a separate path and stay pending
until the History dock approves them. Episodes are never auto-written from
every turn — only via this tool (or an explicit confirm path that calls
add_episode with source=confirm).
"""

from __future__ import annotations

from typing import Any

from arelis.memory.store import MemoryStore
from arelis.tools.base import ToolResult


class MemoryTool:
    name = "memory"
    description = (
        "Remember or forget a durable fact, store a preference, record a "
        "project decision, or save a short episode summary. Use "
        "action=remember ONLY when the user explicitly asks to remember "
        "something durable about them (e.g. 'remember that I climb') — never "
        "because you read a file or want to 'keep something in mind' for this "
        "turn. Use action=prefer (or remember with type=preference) for "
        "key/value prefs, action=decide for project-scoped decisions, "
        "action=episode (or remember with type=episode) for a moment "
        "summary, and action=forget when a stored fact is wrong. The user "
        "confirms every change before it is kept."
    )
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["remember", "forget", "prefer", "decide", "episode"],
                "description": (
                    "remember stores a fact (or preference/episode when type "
                    "is set); prefer stores a key/value preference; decide "
                    "records a project decision; episode stores a short "
                    "moment summary; forget deactivates a matching active fact"
                ),
            },
            "fact": {
                "type": "string",
                "description": (
                    "One short durable statement about the user or their projects. "
                    "Used by remember/forget; also accepted as the value for "
                    "prefer/decide/episode when value/text/summary is omitted."
                ),
            },
            "type": {
                "type": "string",
                "enum": ["fact", "preference", "episode"],
                "description": (
                    "With action=remember: fact (default), preference "
                    "(requires key + value/fact), or episode (summary/fact)"
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "Episode summary for action=episode or remember+type=episode "
                    "(or use fact)"
                ),
            },
            "key": {
                "type": "string",
                "description": (
                    "Preference key for action=prefer or remember+type=preference; "
                    "optional fact key for action=remember (same-key active facts supersede)"
                ),
            },
            "value": {
                "type": "string",
                "description": "Preference value for action=prefer or remember+type=preference",
            },
            "project": {
                "type": "string",
                "description": (
                    "Project name for action=decide; optional project tag for "
                    "action=episode"
                ),
            },
            "text": {
                "type": "string",
                "description": "Decision text for action=decide (or use fact)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "remember").strip().lower()
        if action == "prefer":
            return self._prefer(kwargs)
        if action == "decide":
            return self._decide(kwargs)
        if action == "episode":
            return self._episode(kwargs)
        if action == "remember":
            typ = str(kwargs.get("type") or "fact").strip().lower()
            if typ == "preference":
                return self._prefer(kwargs)
            if typ == "episode":
                return self._episode(kwargs)
            if typ not in {"", "fact"}:
                return ToolResult(
                    ok=False,
                    output=f"Unknown type {typ!r}. Use fact, preference, or episode.",
                )
            fact = str(kwargs.get("fact") or "").strip()
            if not fact:
                return ToolResult(ok=False, output="memory needs a fact.")
            if len(fact) > 400:
                return ToolResult(
                    ok=False,
                    output="That fact is too long. Keep it to one short durable sentence.",
                )
            raw_key = kwargs.get("key")
            fact_key = None if raw_key is None else str(raw_key)
            return self._remember(fact, key=fact_key)
        if action == "forget":
            fact = str(kwargs.get("fact") or "").strip()
            if not fact:
                return ToolResult(ok=False, output="memory needs a fact.")
            return self._forget(fact)
        return ToolResult(
            ok=False,
            output=(
                f"Unknown action {action!r}. Use remember, forget, prefer, "
                "decide, or episode."
            ),
        )

    def _remember(self, fact: str, *, key: str | None = None) -> ToolResult:
        # Confirm already ran: explicit facts are active immediately. Proposed
        # candidates from summarization never come through this tool.
        fact_id = self.store.add_fact(
            fact,
            source="explicit",
            status="active",
            session_id=self.store.session_id,
            key=key,
        )
        if fact_id is None:
            return ToolResult(ok=False, output="Could not store that fact.")
        data: dict[str, Any] = {
            "id": fact_id,
            "fact": fact,
            "status": "active",
            "kind": "fact",
        }
        if key is not None and str(key).strip():
            data["key"] = str(key).strip().lower()
        return ToolResult(
            ok=True,
            output=f"Remembered: {fact}",
            data=data,
        )

    def _prefer(self, kwargs: dict[str, Any]) -> ToolResult:
        key = str(kwargs.get("key") or "").strip()
        value = str(kwargs.get("value") or kwargs.get("fact") or "").strip()
        if not key:
            return ToolResult(ok=False, output="prefer needs a key.")
        if not value:
            return ToolResult(ok=False, output="prefer needs a value.")
        if len(key) > 120:
            return ToolResult(ok=False, output="That preference key is too long.")
        if len(value) > 400:
            return ToolResult(
                ok=False,
                output="That preference value is too long. Keep it short.",
            )
        pref_id = self.store.set_preference(key, value)
        if pref_id is None:
            return ToolResult(ok=False, output="Could not store that preference.")
        return ToolResult(
            ok=True,
            output=f"Preference set: {key}={value}",
            data={"id": pref_id, "key": key, "value": value, "kind": "preference"},
        )

    def _decide(self, kwargs: dict[str, Any]) -> ToolResult:
        project = str(kwargs.get("project") or "").strip()
        text = str(kwargs.get("text") or kwargs.get("fact") or "").strip()
        if not project:
            return ToolResult(ok=False, output="decide needs a project.")
        if not text:
            return ToolResult(ok=False, output="decide needs a text.")
        if len(text) > 400:
            return ToolResult(
                ok=False,
                output="That decision is too long. Keep it to one short sentence.",
            )
        decision_id = self.store.add_decision(project, text)
        if decision_id is None:
            return ToolResult(ok=False, output="Could not store that decision.")
        return ToolResult(
            ok=True,
            output=f"Decision recorded for {project}: {text}",
            data={
                "id": decision_id,
                "project": project,
                "text": text,
                "kind": "decision",
            },
        )

    def _episode(self, kwargs: dict[str, Any]) -> ToolResult:
        summary = str(
            kwargs.get("summary") or kwargs.get("fact") or kwargs.get("text") or ""
        ).strip()
        if not summary:
            return ToolResult(ok=False, output="episode needs a summary.")
        if len(summary) > 400:
            return ToolResult(
                ok=False,
                output="That episode is too long. Keep it to one short summary.",
            )
        raw_project = kwargs.get("project")
        project = None if raw_project is None else str(raw_project).strip() or None
        episode_id = self.store.add_episode(
            summary,
            source="manual",
            session_id=self.store.session_id,
            project=project,
        )
        if episode_id is None:
            return ToolResult(ok=False, output="Could not store that episode.")
        data: dict[str, Any] = {
            "id": episode_id,
            "summary": summary,
            "source": "manual",
            "kind": "episode",
        }
        if project:
            data["project"] = project
        return ToolResult(
            ok=True,
            output=f"Episode saved: {summary}",
            data=data,
        )

    def _forget(self, fact: str) -> ToolResult:
        n = self.store.forget_fact(fact)
        if n == 0:
            # Exact match only: guessing which active fact they meant would
            # deactivate the wrong one.
            active = self.store.active_fact_texts(limit=12)
            hint = ""
            if active:
                listed = "; ".join(active)
                hint = f" Active facts look like: {listed}"
            return ToolResult(
                ok=False,
                output=(
                    f"No active fact matched {fact!r} exactly. Quote it the way "
                    f"it was stored.{hint}"
                ),
            )
        return ToolResult(
            ok=True,
            output=f"Forgot: {fact}",
            data={"fact": fact, "status": "rejected", "count": n},
        )
