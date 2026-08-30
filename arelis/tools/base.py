from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from arelis.tools.policy import (
    CONTACTS_WRITE_ACTIONS,
    INBOX_WRITE_ACTIONS,
    CapabilityClass,
    ToolRisk,
    evaluate_capability,
    evaluate_confirm,
)
from arelis.tools.policy import (
    describe_call as render_confirm_detail,
)
from arelis.tools.safety import redact_secrets

# Placeholder / empty-write args must never reach an Allow card (U7).
_PLACEHOLDER_ARG = re.compile(
    r"(?i)<[^>]*>|\buser_phone_number\b|\byour_phone\b|\bphone_number_here\b|"
    r"\bTODO\b|\bTBD\b|\bxxx+\b"
)


def confirm_args_blocked(name: str, args: dict[str, Any] | None) -> str | None:
    """Return a reason when this call must not show an Allow card, else None."""
    tool = (name or "").strip()
    args = args or {}
    action = str(args.get("action") or "").strip().lower()
    for key, value in args.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if _PLACEHOLDER_ARG.search(text):
            return f"Placeholder argument {key}={text!r} — fill a real value first."
    if tool == "workspace" and action == "write":
        content = str(args.get("content") or "")
        if not content.strip():
            return "workspace write has empty content — nothing to Allow."
    if tool == "document":
        body = str(args.get("body") or "")
        rows = str(args.get("rows") or "")
        title = str(args.get("title") or "")
        from_path = str(args.get("from_path") or "")
        if (
            not body.strip()
            and not rows.strip()
            and not title.strip()
            and not from_path.strip()
        ):
            return "document has empty body — nothing to Allow."
    if tool == "contacts" and action in CONTACTS_WRITE_ACTIONS:
        phone = str(args.get("phone") or args.get("number") or "").strip()
        if phone and _PLACEHOLDER_ARG.search(phone):
            return f"Contacts phone looks like a placeholder: {phone!r}"
    if tool == "inbox" and action in INBOX_WRITE_ACTIONS:
        if action == "create_folder":
            if not str(args.get("folder") or "").strip():
                return "inbox create_folder needs a folder name."
        elif action == "move":
            if not str(args.get("id") or "").strip():
                return "inbox move needs an id from list or search."
            if not str(args.get("folder") or "").strip():
                return "inbox move needs a folder."
        elif not str(args.get("id") or "").strip():
            return "inbox change needs an id from list or search."
    return None


def capability_class(
    name: str, args: dict[str, Any] | None = None
) -> CapabilityClass:
    """Blast-radius class for a concrete tool call (argument-aware)."""
    return evaluate_capability(name, args)


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]
    risk: ToolRisk

    async def run(self, **kwargs: Any) -> ToolResult:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[dict[str, str]]:
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def names(self) -> set[str]:
        return set(self._tools)

    def ollama_tools(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        """OpenAI-style tools array for Ollama /api/chat.

        When ``names`` is set, only those tools are offered (per-turn subset).
        """
        out: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if names is not None and tool.name not in names:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
            )
        return out

    def needs_confirm(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        confirm_writes: bool = True,
        confirm_image: bool = True,
        confirm_send: bool = True,
        confirm_browser: bool = True,
        confirm_vision: bool = True,
    ) -> bool:
        """Decide whether this specific call must go through the confirm card.

        Argument-dependent, not just risk-dependent: workspace(action=read) is
        free, workspace(action=write) is gated. An unknown tool returns False
        because the agent loop rejects it before it ever reaches here, and
        prompting the user to approve something that cannot run is noise.

        send_email and send_sms are named explicitly rather than riding on
        side_effect risk. That branch answers to confirm_image, named for the
        only tool that used to reach it, so turning off image confirmations
        would otherwise turn off mail/SMS confirmations as a side effect
        nobody asked for. browser and vision are gated by their own toggles
        for the same reason — they must not share the image (Comfy) toggle.
        """
        tool = self.get(name)
        if tool is None:
            return False
        return evaluate_confirm(
            name,
            args,
            risk=tool.risk,
            confirm_writes=confirm_writes,
            confirm_image=confirm_image,
            confirm_send=confirm_send,
            confirm_browser=confirm_browser,
            confirm_vision=confirm_vision,
        )

    def summarize_call(self, name: str, args: dict[str, Any]) -> str:
        """One-line rendering of a pending call for the confirm card and trace.

        Redacted, because the most common thing a user is asked to approve is a
        file write, and the content being written is exactly where a key or
        password shows up. Sorted so the same call always reads the same way.
        """
        parts = [f"{k}={_short(redact_secrets(str(v)))}" for k, v in sorted(args.items())]
        joined = ", ".join(parts)
        return f"{name}({joined})" if joined else f"{name}()"

    def describe_call(self, name: str, args: dict[str, Any]) -> str:
        """A fuller rendering of a pending call, for the confirm card."""
        return render_confirm_detail(
            name, args, lookup=self.get, summarize=self.summarize_call
        )

    async def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        """Invoke a tool by name.

        `name` is positional-only on purpose. Arguments come from model output,
        so a hallucinated {"name": ...} argument would otherwise collide with
        this parameter and raise TypeError inside the agent loop, killing the
        turn with no error event and leaving the UI stuck in its busy state.
        """
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {name}")
        try:
            return await tool.run(**kwargs)
        except TypeError as exc:
            # Bad argument shape from the model is a recoverable tool failure,
            # not a crash: hand it back so the model can retry with valid args.
            return ToolResult(ok=False, output=f"Invalid arguments for `{name}`: {exc}")


def _short(value: Any, limit: int = 80) -> str:
    text = str(value).replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text
