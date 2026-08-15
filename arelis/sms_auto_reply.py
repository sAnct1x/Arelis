"""Phase 3 SMS auto-reply: allowlisted contacts, confirm-gated only.

When enabled, an inbound text that matches a keyword rule (or default reply)
asks for the same send_sms confirm card as a manual send. Nothing leaves the
phone until the user allows the card. Silent auto-send is intentionally absent.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from arelis.contacts import load_contacts, resolve_contact
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.sms import format_sms_confirm
from arelis.tools.base import NEVER_BATCH
from arelis.tools.sms_send import SendSmsTool

log = logging.getLogger(__name__)


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def pick_auto_reply(
    body: str,
    rules: list[dict[str, Any]],
    *,
    default_reply: str = "",
) -> str | None:
    """Return the reply text for this body, or None when nothing matches."""
    text = body or ""
    lowered = text.lower()
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        match = str(rule.get("match") or "").strip()
        reply = str(rule.get("reply") or "").strip()
        if not match or not reply:
            continue
        if match.lower() in lowered:
            return reply
    fallback = (default_reply or "").strip()
    return fallback or None


def contact_allowlisted(
    *,
    contact_alias: str,
    sender: str,
    allow: list[str],
    contacts_loader: Callable[[], dict[str, Any]] = load_contacts,
) -> str | None:
    """Return the book alias to send as when the inbound sender is allowlisted."""
    allowed = {_norm(item) for item in allow if str(item).strip()}
    if not allowed:
        return None
    alias = _norm(contact_alias)
    if alias and alias in allowed:
        # Prefer the primary id from the book when the payload used a nickname.
        book = contacts_loader()
        resolved = resolve_contact(contact_alias, book)
        if resolved is not None:
            return resolved.alias
        return contact_alias.strip()
    book = contacts_loader()
    # Match by phone / name / any nickname when the payload had no alias.
    for key in (sender, contact_alias):
        if not (key or "").strip():
            continue
        resolved = resolve_contact(key, book)
        if resolved is None:
            continue
        keys = {_norm(resolved.alias), *resolved.keys}
        if keys & allowed:
            return resolved.alias
    return None


class SmsAutoReply:
    """Subscribe to SMS_RECEIVED and propose confirm-gated replies."""

    def __init__(
        self,
        bus: EventBus,
        config: dict[str, Any],
        *,
        send_tool: SendSmsTool | None = None,
        contacts_loader: Callable[[], dict[str, Any]] = load_contacts,
        # When True (arelis --core), persist the confirm and return without
        # waiting — the UI executes Allow later via PendingConfirmStore.
        headless: bool = False,
    ) -> None:
        self.bus = bus
        self.config = config
        self.send_tool = send_tool
        self._load_contacts = contacts_loader
        self.headless = headless
        self._confirm_waiters: dict[str, asyncio.Future[str]] = {}
        self._pending_args: dict[str, dict[str, str]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._started = False
        self._turn_held = False
        self._held_replies: list[tuple[str, str, str]] = []
        self._drain_running = False

    def _cfg(self) -> dict[str, Any]:
        sms = (self.config.get("tools") or {}).get("sms") or {}
        raw = sms.get("auto_reply") or {}
        return raw if isinstance(raw, dict) else {}

    def start(self) -> None:
        if self._started:
            return
        self.bus.subscribe(EventType.SMS_RECEIVED, self.on_sms_received)
        self.bus.subscribe(EventType.USER_MESSAGE, self.on_user_message)
        self.bus.subscribe(EventType.ASSISTANT_DONE, self.on_assistant_done)
        self.bus.subscribe(EventType.ERROR, self.on_error)
        self.bus.subscribe(EventType.TOOL_CONFIRM_REPLY, self.on_confirm_reply)
        self.bus.subscribe(EventType.TURN_CANCEL, self.on_turn_cancel)
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        # EventBus has no unsubscribe in this codebase; clear waiters only.
        for fut in list(self._confirm_waiters.values()):
            if not fut.done():
                fut.set_result("skip")
        self._confirm_waiters.clear()
        self._pending_args.clear()
        self._held_replies.clear()
        self._turn_held = False
        self._started = False

    async def on_sms_received(self, event: Event) -> None:
        cfg = self._cfg()
        if not bool(cfg.get("enabled", False)):
            return
        if self.send_tool is None:
            log.info("SMS auto-reply skipped: send_sms is not configured")
            return
        payload = event.payload or {}
        body = str(payload.get("body") or "")
        alias = contact_allowlisted(
            contact_alias=str(payload.get("contact_alias") or ""),
            sender=str(payload.get("from") or ""),
            allow=list(cfg.get("contacts") or []),
            contacts_loader=self._load_contacts,
        )
        if alias is None:
            return
        rules = cfg.get("rules") or []
        if not isinstance(rules, list):
            rules = []
        reply = pick_auto_reply(
            body,
            rules,
            default_reply=str(cfg.get("default_reply") or ""),
        )
        if not reply:
            return
        if self._turn_held:
            self._held_replies.append((alias, reply, str(payload.get("id") or "")))
            return
        # Fire-and-forget so the bus handler returns; confirm waits inside.
        inbound_id = str(payload.get("id") or "")
        task = asyncio.create_task(
            self._propose_reply(alias, reply, inbound_id=inbound_id),
            name="sms-auto-reply",
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_user_message(self, event: Event) -> None:
        self._turn_held = True

    async def on_assistant_done(self, event: Event) -> None:
        self._turn_held = False
        self._kick_held_replies()

    async def on_error(self, event: Event) -> None:
        if (event.payload or {}).get("scope") == "voice":
            return
        self._turn_held = False
        self._kick_held_replies()

    def _kick_held_replies(self) -> None:
        if self._turn_held or not self._held_replies or self._drain_running:
            return
        task = asyncio.create_task(
            self._drain_held_replies(), name="sms-auto-reply-held"
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drain_held_replies(self) -> None:
        self._drain_running = True
        try:
            while self._held_replies and not self._turn_held:
                alias, reply, inbound_id = self._held_replies.pop(0)
                await self._propose_reply(alias, reply, inbound_id=inbound_id)
        finally:
            self._drain_running = False

    async def _propose_reply(self, to_alias: str, body: str, *, inbound_id: str) -> None:
        args = {"to": to_alias, "body": body}
        confirm_id = f"sms-auto-{uuid.uuid4().hex[:12]}"
        summary = f"send_sms(to={to_alias}, body={body[:60]}{'…' if len(body) > 60 else ''})"
        detail = format_sms_confirm(to_alias, body, contacts=self._load_contacts())
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._confirm_waiters[confirm_id] = fut
        self._pending_args[confirm_id] = args
        await self.bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        f"Auto-reply draft for {to_alias}"
                        + (f" (re: {inbound_id})" if inbound_id else "")
                        + " — confirm to send."
                    )
                },
            )
        )
        await self.bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {
                    "id": confirm_id,
                    "tool": "send_sms",
                    "args": {k: v[:200] for k, v in args.items()},
                    # Full body for PendingConfirmStore / restored Allow.
                    "full_args": dict(args),
                    "summary": summary,
                    "detail": detail,
                    "note": "Suggested auto-reply. Nothing is sent until you allow.",
                    "batch_ok": "send_sms" not in NEVER_BATCH,
                    "source": "sms_auto_reply",
                },
            )
        )
        if self.headless:
            # Core has no confirm card. Store + UI handle Allow; do not send.
            self._confirm_waiters.pop(confirm_id, None)
            self._pending_args.pop(confirm_id, None)
            if not fut.done():
                fut.set_result("parked")
            await self.bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            f"Auto-reply draft for {to_alias} saved — open Arelis "
                            "to allow or skip (nothing sent)."
                        )
                    },
                )
            )
            return
        try:
            decision = await fut
        finally:
            self._confirm_waiters.pop(confirm_id, None)
            self._pending_args.pop(confirm_id, None)
        if decision not in {"allow", "allow_turn"}:
            await self.bus.publish(
                Event(
                    EventType.STATUS,
                    {"message": f"Auto-reply to {to_alias} skipped."},
                )
            )
            return
        assert self.send_tool is not None
        result = await self.send_tool.run(**args)
        await self.bus.publish(
            Event(
                EventType.TOOL_RESULT,
                {
                    "tool": "send_sms",
                    "ok": result.ok,
                    "output": result.output,
                    "data": result.data or {},
                    "source": "sms_auto_reply",
                },
            )
        )
        await self.bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        result.output
                        if result.ok
                        else f"Auto-reply failed: {result.output}"
                    )
                },
            )
        )

    async def on_confirm_reply(self, event: Event) -> None:
        confirm_id = str((event.payload or {}).get("id") or "")
        decision = str((event.payload or {}).get("decision") or "skip").lower()
        if (event.payload or {}).get("allow_turn"):
            decision = "allow_turn"
        fut = self._confirm_waiters.get(confirm_id)
        if fut and not fut.done():
            fut.set_result(decision)

    async def on_turn_cancel(self, event: Event) -> None:
        self._turn_held = False
        for fut in list(self._confirm_waiters.values()):
            if not fut.done():
                fut.set_result("skip")
        self._kick_held_replies()
