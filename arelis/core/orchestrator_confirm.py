"""Allow-card waiters. Voice control stays on Orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from arelis.core.events import Event, EventType
from arelis.core.untrusted import confirm_note_after_external
from arelis.tools.base import NEVER_BATCH
from arelis.tools.confirm_copy import confirm_headline
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
        r"deeply\s+research|"
        r"deep\s+research|"
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


class OrchestratorConfirm:
    async def _request_confirm(
        self, confirm_id: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        """Ask the UI to approve a call and wait for the answer.

        The future is registered before the event is published so a reply that
        arrives immediately, as it does in the CLI and in the e2e probes, cannot
        land before there is anything to resolve.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._confirm_waiters[confirm_id] = fut
        self._confirm_live[confirm_id] = {
            "tool": tool,
            "args": args,
            "summary": summary,
        }
        preview_args = {k: redact_secrets(str(v))[:200] for k, v in args.items()}
        await self.bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {
                    "id": confirm_id,
                    "tool": tool,
                    "args": preview_args,
                    # Parked/restarted Allow must send these, not the 200-char
                    # preview. Live turns still execute in-memory full args.
                    "full_args": {str(k): v for k, v in args.items()},
                    "summary": summary,
                    "headline": confirm_headline(tool, args),
                    # Full rendering for the card. summary stays as it was, for
                    # the thinking dock and the CLI, which want one line.
                    "detail": self.tools.describe_call(tool, args),
                    "note": self._confirm_note(tool),
                    "batch_ok": tool not in NEVER_BATCH,
                },
            )
        )
        agent_cfg = self.config.get("agent") or {}
        timeout_s = float(agent_cfg.get("confirm_timeout_s", 300) or 0)
        try:
            if timeout_s > 0:
                # asyncio.wait (not wait_for): do not cancel the Future on timeout.
                done, _pending = await asyncio.wait({fut}, timeout=timeout_s)
                if fut in done:
                    return fut.result()
                # L10: don't leave wall-clock looking like a hung model forever.
                if not fut.done():
                    fut.set_result("skip")
                mins = max(1, int(timeout_s // 60))
                await self.bus.publish(
                    Event(
                        EventType.STATUS,
                        {
                            "message": (
                                f"Confirm timed out after {mins}m — skipped `{tool}`."
                            )
                        },
                    )
                )
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"phase=confirm timeout_skip tool={tool} "
                                f"after_s={int(timeout_s)}"
                            )
                        },
                    )
                )
                await self.bus.publish(
                    Event(
                        EventType.TOOL_CONFIRM_REPLY,
                        {
                            "id": confirm_id,
                            "decision": "skip",
                            "allow_turn": False,
                            "reason": "timeout",
                        },
                    )
                )
                return "skip"
            return await fut
        finally:
            self._confirm_waiters.pop(confirm_id, None)
            self._confirm_live.pop(confirm_id, None)

    def _confirm_note(self, tool: str) -> str:
        """A warning to put on the card, when this particular call deserves one.

        Read straight off the running loop rather than off the bus. This is
        called from inside the agent loop's own coroutine, so the set is exactly
        up to date; a TOOL_RESULT subscriber would race with it.
        """
        used = set()
        loop = self._agent_loop
        if loop is not None:
            used = set(loop.tools_used)
        return confirm_note_after_external(tool, used)
