"""Slash help and /tool commands. Voice stays on Orchestrator."""

from __future__ import annotations

import json
import logging
import re
import shlex
from typing import Any

from arelis.core.events import Event, EventType
from arelis.core.memory import tool_trace_entry, tool_trace_note
from arelis.tools.safety import redact_secrets

# Absolute paths typed in chat that may need a session read grant.
_ABS_PATH_TOKEN = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+)"
    r"|(?:/(?:Users|home|tmp|var|etc|opt)[^\s\"'<>|]*))"
)

log = logging.getLogger(__name__)

ROLES: set[str] = {"fast", "research"}


def research_needs_vram_swap(router: object) -> bool:
    """True when research is a different Ollama tag from fast."""
    same = getattr(router, "same_chat_weights", None)
    if callable(same):
        try:
            return not bool(same("fast", "research"))
        except Exception:
            return True
    model_for = getattr(router, "model_for", None)
    if not callable(model_for):
        return True
    try:
        from arelis.llm.ollama import same_ollama_model

        return not same_ollama_model(
            str(model_for("fast") or ""),
            str(model_for("research") or ""),
        )
    except Exception:
        return True


def comms_bypasses_sticky(text: str) -> bool:
    """True when this turn is SMS/email/agenda and must not keep a sticky hold."""
    raw = (text or "").strip()
    if not raw:
        return False
    from arelis.core.agenda_complete import (
        looks_like_calendar_create,
        looks_like_calendar_delete,
        looks_like_calendar_read,
    )
    from arelis.core.email_complete import looks_like_compose_email
    from arelis.core.sms_complete import parse_sms_utterance

    if parse_sms_utterance(raw) is not None:
        return True
    if looks_like_compose_email(raw):
        return True
    return (
        looks_like_calendar_create(raw)
        or looks_like_calendar_delete(raw)
        or looks_like_calendar_read(raw)
    )


# Auto-routing heuristics. Tool-shaped asks stay on fast because
# that path follows the tool schema far more reliably than a long
# research loop, which tends to narrate a call instead of emitting one.
TOOL_LOOP_HINT = re.compile(
    r"\b(search|web_search|google|scrape|fetch|open|read|list|write|edit"
    r"|analyze|workspace|web_fetch|file|email|inbox|mail|schedule"
    r"|weather|forecast|recall|remember|agenda|calendar|tasks?|todo"
    r"|git|sms|text|inbound|research(?:_report)?|doc_extract|pdf)\b|https?://",
    re.IGNORECASE,
)
FILE_LOOP_HINT = re.compile(
    r"\b(file|readme|path|workspace|edit|write|refactor|python|code|debug"
    r"|class|function|lint|git|branch|commit|diff)\b",
    re.IGNORECASE,
)
# Deep / heavy research only → 14b. Short factual "look this up" stays on fast
# (7b+tools). Bare "research" / "cite" alone no longer force a VRAM swap (H2).
RESEARCH_HINTS: list[re.Pattern[str]] = [
    re.compile(
        r"\b("
        r"deep\s*-?\s*dive|"
        r"multi\s*-?\s*source|"
        r"write\s+a\s+report|"
        r"thorough\s+research|"
        r"in\s*-?\s*depth\s+(?:research|look|analysis|report)|"
        r"investigate|"
        r"hypothesis|"
        r"derive|"
        r"astrophys|interferom|spectrum|"
        r"research\s+report|"
        r"cite\s+sources"
        r")\b",
        re.IGNORECASE,
    ),
]

# Slash commands run a tool directly, bypassing the model and the confirm card.
# That bypass is intentional and is scoped to text the user typed: naming a tool
# and its arguments explicitly is itself the confirmation.
#
# send_email and send_sms are deliberately absent. Every other tool here is
# undoable or local; a sent message is neither, and the card showing the
# recipient and body is the only gate it has. There is no version of typing it
# out that replaces reading what is about to leave the machine.
TOOL_CMD = re.compile(
    r"^/(?P<tool>web_search|web_fetch|scrape|workspace|analyze|image"
    r"|inbox|schedule)(?:\s+(?P<args>.+))?$",
    re.IGNORECASE,
)


def _as_code_block(text: str) -> str:
    """Fence text so it renders verbatim.

    The fence is one backtick longer than the longest run already in the text,
    which is what keeps a markdown file that contains its own fences from
    closing this one early and spilling the rest into the chat as prose.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"

def _tokenize(args: str) -> list[str]:
    """Split slash-command arguments the way a Windows user would expect.

    Plain shlex.split gets two things wrong here, both silently:

    - POSIX escape rules make a backslash escape the next character, so
      path=C:\\Users\\you\\notes.txt arrives as path=C:Usersyounotes.txt and
      the user is told a file that plainly exists cannot be found.
    - '#' starts a comment, so url=https://host/page#section loses its fragment.

    posix=False fixes the backslashes but stops honouring quotes that begin
    mid-token, which breaks path="C:\\Program Files\\x". So the lexer is
    configured directly: POSIX quoting, no escape character, no comments.
    """
    try:
        lexer = shlex.shlex(args, posix=True)
        lexer.whitespace_split = True
        lexer.escape = ""
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        # Unbalanced quotes. Whitespace splitting still recovers most of it.
        tokens = [_unquote(token) for token in args.split()]
    return tokens

def _unquote(token: str) -> str:
    if "=" in token:
        key, value = token.split("=", 1)
        return f"{key}={_strip_quotes(value)}"
    return _strip_quotes(token)

def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value

class OrchestratorSlash:
    async def _emit_help(self) -> None:
        tools = ", ".join(t["name"] for t in self.tools.list()) or "(none)"
        msg = (
            "Just talk. Arelis can use tools from natural language "
            "(reads and web run on their own; writes and images ask first).\n\n"
            "Power-user slash commands:\n"
            "  /role fast|research\n"
            "  /project [name]\n"
            "  /rooms                       list rooms\n"
            "  /room <name>                 open one (or say \"let's work on <name>\")\n"
            "  /room new <name>             make one\n"
            "  /room set purpose|root|kind|name|result|test <value>\n"
            "  /room forget <name>          drop the room, keep its conversations\n"
            "  /leave                       back to the general conversation\n"
            "  /web_search query=...\n"
            "  /web_fetch url=...\n"
            "  /scrape url=...\n"
            "  /keep <note>                 put a note on the desk\n"
            "  /workspace action=list|read|write|edit|keep path=...\n"
            "  /analyze path=... action=summary|head|describe\n"
            "  /image prompt=...\n"
            "Slash commands run the tool directly and skip the confirm card.\n"
            "With multiple projects, paths may be `name:relative/path`.\n"
            f"Tools: {tools}"
        )
        await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": msg}))

    async def _run_tool_command(self, tool: str, args: str) -> None:
        kwargs = self._parse_args(args)
        await self.bus.publish(Event(EventType.TOOL_START, {"tool": tool, "args": kwargs}))
        await self.bus.publish(
            Event(EventType.THINKING, {"text": f"slash  Running tool `{tool}`"})
        )
        result = await self.tools.call(tool, **kwargs)
        await self.bus.publish(
            Event(
                EventType.TOOL_RESULT,
                {"tool": tool, "ok": result.ok, "output": result.output, "data": result.data},
            )
        )
        if tool == "image" and result.ok and result.data.get("path"):
            await self.bus.publish(Event(EventType.IMAGE_READY, {"path": result.data["path"]}))
        if tool in {"document", "plot"} and result.ok and result.data.get("abs_path"):
            await self.bus.publish(
                Event(
                    EventType.FILE_READY,
                    {
                        "path": str(result.data.get("path") or ""),
                        "abs_path": str(result.data.get("abs_path") or ""),
                        "format": str(result.data.get("format") or ""),
                        "title": str(result.data.get("title") or ""),
                        "show_card": True,
                        "open": False,
                    },
                )
            )
        prefix = "OK" if result.ok else "Failed"
        # Tool output is data, not prose, so it is fenced. The chat renders
        # markdown now, and an unfenced Python file would come out with *args
        # italicised and its indentation collapsed.
        summary = f"{prefix} `{tool}`\n\n{_as_code_block(redact_secrets(result.output))}"
        # Slash commands skip the agent loop, so the trace note has to be built
        # here too. Without it a "/workspace action=write" followed by "now add
        # a heading to it" has nothing to resolve "it" against.
        resolved = None
        if isinstance(result.data, dict):
            resolved = result.data.get("abs_path") or result.data.get("path")
        self.memory.add(
            "assistant",
            summary,
            note=tool_trace_note(
                [tool_trace_entry(tool, kwargs, result.ok, resolved_path=resolved)]
            ),
        )
        await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": summary}))

    def _parse_args(self, args: str) -> dict[str, Any]:
        """Parse slash-command arguments.

        Three accepted forms, in priority order: a JSON object (used by the
        workspace panel's save button, since file content cannot survive shell
        splitting), key=value pairs, and a bare URL or bare prompt text.
        """
        if not args.strip():
            return {}
        if args.strip().startswith("{"):
            try:
                data = json.loads(args)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        out: dict[str, Any] = {}
        for token in _tokenize(args):
            if "=" in token:
                k, v = token.split("=", 1)
                out[k] = v
            elif "url" not in out and token.startswith("http"):
                out["url"] = token
        if not out:
            bare = args.strip()
            # "/image prompt a spiral galaxy" is a natural thing to type, and
            # without this the word "prompt" ends up inside the prompt itself.
            if bare.lower().startswith("prompt "):
                bare = bare[len("prompt ") :].strip()
            if bare:
                out["prompt"] = bare
        return out
