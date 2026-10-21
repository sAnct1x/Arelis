from __future__ import annotations

import builtins
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from arelis.tools.coerce import coerce_arguments
from arelis.tools.model_schema import model_parameters
from arelis.tools.policy import (
    CONTACTS_WRITE_ACTIONS,
    GOALS_WRITE_ACTIONS,  # noqa: F401 — re-exported
    INBOX_WRITE_ACTIONS,
    NEVER_BATCH,  # noqa: F401 — re-exported
    SOLAR_WRITE_ACTIONS,  # noqa: F401 — re-exported
    TASKS_WRITE_ACTIONS,  # noqa: F401 — re-exported
    CapabilityClass,
    ToolRisk,
    confirm_toggles_for_call,
    evaluate_capability,
    evaluate_confirm,
)
from arelis.tools.policy import (
    describe_call as render_confirm_detail,
)
from arelis.tools.safety import redact_secrets

log = logging.getLogger(__name__)

# Template tokens the model uses when it has not filled a real value (U7).
# Do not match raw "<...>" — that flags comparison text ("<30 Hz ... >30 Hz")
# and real HTML as placeholders. The 9B then re-emits the same write until
# max_rounds (a 7-minute homework dump with no answer).
_PLACEHOLDER_TOKEN = (
    r"user_phone_number|your_phone|phone_number_here|"
    r"your_email|user_email|email_here|TODO|TBD|xxx+"
)
_PLACEHOLDER_ARG = re.compile(
    rf"(?i)<(?:{_PLACEHOLDER_TOKEN})>|\b(?:{_PLACEHOLDER_TOKEN})\b"
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
            return (
                f"Placeholder argument {key}={_short(text)!r} "
                "- fill a real value first."
            )
    if tool == "workspace" and action == "write":
        content = str(args.get("content") or "")
        if not content.strip():
            return (
                "workspace write has empty content. "
                "Pass content= with the file body."
            )
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
            return "document has empty body, nothing to Allow."
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
        # Groups load_tools has recorded for this session. A settings rebuild
        # makes a new registry, so the set starts empty again. Turns share
        # this list: each turn builds a new agent loop.
        self.loaded_groups: list[str] = []

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> builtins.list[dict[str, str]]:
        # The method is named `list`, so a bare `list[...]` annotation is
        # the method, not the builtin. mypy then reports "not valid as a
        # type" — the only error this file had.
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def names(self) -> set[str]:
        return set(self._tools)

    def chat_tools(
        self,
        names: set[str] | None = None,
        *,
        param_hints: bool = False,
    ) -> builtins.list[dict[str, Any]]:
        """OpenAI-style tools array for the model server /api/chat.

        When ``names`` is set, only those tools are offered (per-turn subset).
        Descriptions are one line; param essays are stripped. Names, enums,
        and required stay, that is what structured calling needs. Aliases,
        paging knobs, and expert knobs listed in ``MODEL_HIDDEN_PARAMS`` are
        left out of this array only. The tool still accepts them.

        When ``param_hints`` is True (native_tool_calling mode), specific
        parameter descriptions are kept to guide the model.
        """
        from arelis.core.compact_prompt import skinny_tool

        out: builtins.list[dict[str, Any]] = []
        for tool in self._tools.values():
            if names is not None and tool.name not in names:
                continue
            spec = skinny_tool(
                tool.name,
                getattr(tool, "description", "") or "",
                getattr(tool, "parameters_schema", None),
                param_hints=param_hints,
            )
            fn = spec["function"]
            fn["parameters"] = model_parameters(tool.name, fn["parameters"])
            out.append(spec)
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
        confirm_desktop: bool = True,
        confirm_vision: bool = True,
        confirm_run: bool = True,
        allow_writes_this_turn: bool = False,
        asked: bool = False,
        ask_is_grant: bool = True,
        run_declined: bool = False,
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
        for the same reason, they must not share the image (Comfy) toggle.
        """
        tool = self.get(name)
        if tool is None:
            return False
        # A declined run stays on the turn. The python cell asks for no
        # card when programs are off, so without this the same code runs
        # anyway. Turns with no decline are unchanged.
        if name == "python" and run_declined:
            return True
        # Programs opt-out skips the card only for exact bytes the user
        # already approved. A rename, a new file, or a restart does not
        # make unseen source trusted.
        # All cards off is the user's saved settings, not this turn's
        # grant. A one-turn write grant does not count. That saved-off
        # path skips a script's first run without hashing the file or
        # opening the approvals list.
        run_confirm = confirm_run
        if name == "run_script":
            clear = getattr(tool, "clear_run_pin", None)
            if callable(clear):
                clear(args or {})
            cards_off = not (
                confirm_writes
                or confirm_image
                or confirm_send
                or confirm_browser
                or confirm_desktop
                or confirm_vision
                or confirm_run
            )
            if not confirm_run and not cards_off:
                approved = getattr(tool, "user_approved_script", None)
                if not (callable(approved) and approved(args or {})):
                    run_confirm = True
        turn = confirm_toggles_for_call(
            name,
            confirm_writes=confirm_writes,
            confirm_image=confirm_image,
            confirm_send=confirm_send,
            confirm_browser=confirm_browser,
            confirm_vision=confirm_vision,
            confirm_desktop=confirm_desktop,
            confirm_run=run_confirm,
            allow_writes_this_turn=allow_writes_this_turn,
        )
        return evaluate_confirm(
            name,
            args,
            risk=tool.risk,
            confirm_writes=turn["confirm_writes"],
            confirm_image=turn["confirm_image"],
            confirm_send=turn["confirm_send"],
            confirm_browser=turn["confirm_browser"],
            confirm_desktop=turn["confirm_desktop"],
            confirm_vision=turn["confirm_vision"],
            confirm_run=turn["confirm_run"],
            asked=asked,
            ask_is_grant=ask_is_grant,
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

    def coerce_call_args(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Convert string arguments from this tool's schema.

        Any failure returns the original dict and logs once. The turn
        keeps going with the values the model sent.
        """
        tool = self.get(name)
        if tool is None:
            return args
        schema = getattr(tool, "parameters_schema", None)
        if not isinstance(schema, dict):
            return args
        try:
            return coerce_arguments(schema, args)
        except Exception:
            log.warning(
                "Tool arguments for %s were left as the model sent them",
                name,
                exc_info=True,
            )
            return args

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
        # the model server types arguments only for names in the tools array. A loaded
        # tool is not in that array, so every argument arrives as a string.
        # Convert from this tool's schema on every call. A value that already
        # has the right type is left as it is. A conversion that does not
        # parse is left as it is, and the tool reports it. A crash inside
        # conversion leaves the raw arguments and the call still runs.
        kwargs = self.coerce_call_args(name, kwargs)
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
