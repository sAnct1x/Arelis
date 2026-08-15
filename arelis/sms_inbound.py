"""Poll SMSGate for inbound SMS while the desktop UI is open.

SMSGate's sync inbox read is Local Server only (`GET /inbox`). Cloud mode
exposes inbound only via webhooks (or export-that-fires-webhooks), which this
phase deliberately skips. Outbound may still use Cloud: put the LAN base in
`sms.inbox_base_url` and keep `sms.base_url` on the Cloud API.

GET /inbox alone is stale: the phone only fills that list after
`POST /inbox/refresh`. Each poll refreshes a recent window, then lists.
AT&T / RCS threads often land as MMS_DOWNLOADED, so we do not filter to SMS.

First launch after upgrade seeds the seen-id store from the current inbox so
old texts are not blasted as "new." Only messages that appear after that seed
(or after the last persisted seen id) are published as SMS_RECEIVED.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from arelis.config import PROJECT_ROOT
from arelis.contacts import Contact, load_contacts, normalize_phone, resolve_contact
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.sms_android import SmsGateAccount, _json

log = logging.getLogger(__name__)

SEEN_PATH = PROJECT_ROOT / "data" / "sms_inbound_seen.json"
DEFAULT_POLL_INTERVAL_S = 4.0
DEFAULT_LIMIT = 50
MAX_SEEN_IDS = 500
# Quiet hard-down reports: STATUS at most once per this many seconds.
STATUS_COOLDOWN_S = 60.0
CHAT_BODY_CHARS = 120
# How far back each poll asks the phone to re-index into GET /inbox.
REFRESH_LOOKBACK = timedelta(hours=2)
# Types that are normal "someone texted you" rows (skip DATA_SMS).
INBOUND_TYPES = frozenset({"SMS", "MMS", "MMS_DOWNLOADED"})


@dataclass(frozen=True)
class InboundSms:
    """One inbox row after contact resolution."""

    id: str
    sender: str
    body: str
    time: str
    contact_alias: str = ""
    contact_name: str = ""

    @property
    def display_from(self) -> str:
        return self.contact_name or self.sender

    def as_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "from": self.sender,
            "body": self.body,
            "time": self.time,
            "contact_alias": self.contact_alias or None,
            "contact_name": self.contact_name or None,
        }


def format_sms_chat_line(msg: InboundSms, *, max_body: int = CHAT_BODY_CHARS) -> str:
    """Chat / system line: from + truncated body."""
    body = (msg.body or "").strip().replace("\n", " ")
    if max_body > 0 and len(body) > max_body:
        body = body[: max_body - 1].rstrip() + "…"
    if not body:
        return f"Text from {msg.display_from}."
    return f"Text from {msg.display_from}: {body}"


def format_sms_voice_cue(msg: InboundSms) -> str:
    """Short TTS cue — name only, never the full body."""
    return f"Text from {msg.display_from}."


def floor_is_busy(
    *,
    turn_busy: bool = False,
    confirm_open: bool = False,
    speaking: bool = False,
) -> bool:
    """True while a chat turn, Allow card, or spoken reply owns attention."""
    return bool(turn_busy or confirm_open or speaking)


def _unique_from_names(messages: list[InboundSms]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        name = msg.display_from
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def format_held_inbound_flush(
    messages: list[InboundSms],
    *,
    max_body: int = CHAT_BODY_CHARS,
) -> str:
    """One batched system line after the floor is free. Empty if nothing held."""
    msgs = [m for m in messages if m is not None]
    if not msgs:
        return ""
    if len(msgs) == 1:
        return format_sms_chat_line(msgs[0], max_body=max_body)
    names = _unique_from_names(msgs)
    count = len(msgs)
    if len(names) == 1:
        head = f"{count} texts from {names[0]}:"
    elif len(names) == 2:
        head = f"{count} texts from {names[0]} and {names[1]}:"
    else:
        head = f"{count} texts from {', '.join(names[:-1])}, and {names[-1]}:"
    lines = [head]
    for msg in msgs:
        body = (msg.body or "").strip().replace("\n", " ")
        if max_body > 0 and len(body) > max_body:
            body = body[: max_body - 1].rstrip() + "…"
        if len(names) == 1:
            lines.append(f"- {body}" if body else "- (no body)")
        elif body:
            lines.append(f"- {msg.display_from}: {body}")
        else:
            lines.append(f"- {msg.display_from}.")
    return "\n".join(lines)


def format_held_inbound_voice_cue(messages: list[InboundSms]) -> str:
    """One short TTS cue for a held batch — names only."""
    msgs = [m for m in messages if m is not None]
    if not msgs:
        return ""
    if len(msgs) == 1:
        return format_sms_voice_cue(msgs[0])
    names = _unique_from_names(msgs)
    count = len(msgs)
    if len(names) == 1:
        return f"{count} texts from {names[0]}."
    if len(names) == 2:
        return f"Texts from {names[0]} and {names[1]}."
    return f"{count} texts from {len(names)} people."


class SeenMessageStore:
    """Persist SMSGate message ids so reopen does not re-announce old texts."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or SEEN_PATH
        self._seen: set[str] = set()
        self._seeded = False
        self._load()

    @property
    def seeded(self) -> bool:
        return self._seeded

    def has(self, message_id: str) -> bool:
        return bool(message_id) and message_id in self._seen

    def mark(self, message_ids: list[str]) -> None:
        changed = False
        for mid in message_ids:
            mid = (mid or "").strip()
            if not mid or mid in self._seen:
                continue
            self._seen.add(mid)
            changed = True
        if changed:
            self._trim()
            self._save()

    def mark_seeded(self, message_ids: list[str]) -> None:
        """Absorb the current inbox without treating it as newly arrived.

        First launch after upgrade must not dump every recent text as "new."
        """
        self.mark(message_ids)
        if not self._seeded:
            self._seeded = True
            self._save()

    def _trim(self) -> None:
        if len(self._seen) <= MAX_SEEN_IDS:
            return
        # Ids are opaque; drop an arbitrary excess. Polls only care about
        # recent ids still in the inbox window.
        overflow = len(self._seen) - MAX_SEEN_IDS
        for mid in list(self._seen)[:overflow]:
            self._seen.discard(mid)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Could not read %s: %s", self.path, exc)
            return
        if not isinstance(raw, dict):
            return
        ids = raw.get("seen_ids") or []
        if isinstance(ids, list):
            self._seen = {str(i) for i in ids if str(i).strip()}
        self._seeded = bool(raw.get("seeded"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "seeded": self._seeded,
            "seen_ids": sorted(self._seen)[-MAX_SEEN_IDS:],
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _message_type(row: dict[str, Any]) -> str:
    raw = row.get("type")
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("value") or "").strip().upper()
    return str(raw or "").strip().upper()


def _is_self_message(row: dict[str, Any], contacts: dict[str, Contact] | None) -> bool:
    """True for loopback / own-number rows that should not notify."""
    sender = normalize_phone(str(row.get("sender") or ""))
    recipient = normalize_phone(str(row.get("recipient") or ""))
    if sender and recipient and sender == recipient:
        return True
    if not sender or not contacts:
        return False
    me = contacts.get("me")
    if me is not None and me.digits and me.digits == sender:
        return True
    return False


async def refresh_inbox(
    account: SmsGateAccount,
    *,
    lookback: timedelta = REFRESH_LOOKBACK,
    timeout_s: float = 15.0,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Ask the phone to re-index recent messages into GET /inbox (202 Accepted)."""
    if not account.supports_inbox_poll():
        raise SmsInboxError(
            "SMSGate Cloud has no sync inbox list. Enable Local Server on the "
            "phone and set sms.inbox_base_url to http://PHONE_IP:8080 (outbound "
            "can stay on Cloud)."
        )
    until = datetime.now(UTC)
    since = until - lookback
    url = account.inbox_refresh_url
    payload = {
        "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "triggerWebhooks": False,
    }
    auth = account.inbox_auth
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.post(url, json=payload, auth=auth)
    finally:
        if owns_client:
            await client.aclose()
    if response.status_code in {401, 403}:
        raise SmsInboxError(
            "SMSGate rejected inbox credentials. Check username/password for "
            "Local Server (they can differ from Cloud)."
        )
    if response.status_code == 404:
        raise SmsInboxError(
            f"SMSGate returned 404 for {url}. POST /inbox/refresh is Local "
            f"Server only."
        )
    if response.status_code >= 400:
        raise SmsInboxError(
            f"SMSGate inbox refresh refused ({response.status_code}): "
            f"{_inbox_detail(response)}"
        )


async def fetch_inbox(
    account: SmsGateAccount,
    *,
    limit: int = DEFAULT_LIMIT,
    timeout_s: float = 15.0,
    client: httpx.AsyncClient | None = None,
    refresh: bool = True,
    lookback: timedelta = REFRESH_LOOKBACK,
) -> list[dict[str, Any]]:
    """Refresh recent inbox, then GET /inbox (SMS + MMS)."""
    if not account.supports_inbox_poll():
        raise SmsInboxError(
            "SMSGate Cloud has no sync inbox list. Enable Local Server on the "
            "phone and set sms.inbox_base_url to http://PHONE_IP:8080 (outbound "
            "can stay on Cloud)."
        )
    url = account.inbox_url
    params = {"limit": max(1, min(int(limit), 500))}
    auth = account.inbox_auth
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    try:
        if refresh:
            await refresh_inbox(
                account, lookback=lookback, timeout_s=timeout_s, client=client
            )
        response = await client.get(url, params=params, auth=auth)
    finally:
        if owns_client:
            await client.aclose()

    if response.status_code in {401, 403}:
        raise SmsInboxError(
            "SMSGate rejected inbox credentials. Check username/password for "
            "Local Server (they can differ from Cloud)."
        )
    if response.status_code == 404:
        raise SmsInboxError(
            f"SMSGate returned 404 for {url}. GET /inbox is Local Server only "
            f"(http://PHONE_IP:8080), not the Cloud API."
        )
    if response.status_code >= 400:
        raise SmsInboxError(
            f"SMSGate inbox refused ({response.status_code}): "
            f"{_inbox_detail(response)}"
        )
    data = _json(response)
    if not isinstance(data, list):
        raise SmsInboxError("SMSGate inbox response was not a list.")
    return [row for row in data if isinstance(row, dict)]


def parse_inbox_row(
    row: dict[str, Any],
    *,
    contacts: dict[str, Contact] | None = None,
) -> InboundSms | None:
    """Map one API row to InboundSms, or None when it should be ignored."""
    message_id = str(row.get("id") or "").strip()
    if not message_id:
        return None
    kind = _message_type(row)
    if kind and kind not in INBOUND_TYPES:
        return None
    if _is_self_message(row, contacts):
        return None
    sender = str(row.get("sender") or "").strip() or "(unknown)"
    body = str(row.get("contentPreview") or row.get("message") or "").strip()
    created = str(row.get("createdAt") or row.get("receivedAt") or "").strip()
    contact = resolve_contact(sender, contacts)
    return InboundSms(
        id=message_id,
        sender=sender,
        body=body,
        time=created,
        contact_alias=contact.alias if contact else "",
        contact_name=contact.display_name if contact else "",
    )


class SmsInboxError(RuntimeError):
    """Inbox failure already worded for STATUS / logs."""


class InboundSmsWatcher:
    """Poll Local Server inbox on a timer; publish SMS_RECEIVED for new rows."""

    def __init__(
        self,
        bus: EventBus,
        account: SmsGateAccount,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        timeout_s: float = 15.0,
        limit: int = DEFAULT_LIMIT,
        seen: SeenMessageStore | None = None,
        contacts_loader=load_contacts,
    ) -> None:
        self.bus = bus
        self.account = account
        self.poll_interval_s = max(1.0, float(poll_interval_s))
        self.timeout_s = float(timeout_s)
        self.limit = int(limit)
        self.seen = seen or SeenMessageStore()
        self._contacts_loader = contacts_loader
        self._task: asyncio.Task[Any] | None = None
        self._stop = asyncio.Event()
        self._last_status_at = 0.0
        self._hard_down_announced = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        if not self.account.supports_inbox_poll():
            await self._status_once(
                "Inbound SMS needs Local Server: Cloud cannot list inbox. "
                "Set sms.inbox_base_url to http://PHONE_IP:8080 while Local "
                "Server is Online (outbound Cloud URL can stay as-is)."
            )
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="sms-inbound-watcher")

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def poll_once(self) -> list[InboundSms]:
        """One fetch + publish cycle. Used by the loop and by tests."""
        rows = await fetch_inbox(
            self.account,
            limit=self.limit,
            timeout_s=self.timeout_s,
        )
        contacts = self._contacts_loader()
        parsed: list[InboundSms] = []
        for row in rows:
            msg = parse_inbox_row(row, contacts=contacts)
            if msg is not None:
                parsed.append(msg)

        ids = [m.id for m in parsed]
        if not self.seen.seeded:
            # First run: remember everything currently in the inbox, announce none.
            self.seen.mark_seeded(ids)
            self._hard_down_announced = False
            return []

        fresh: list[InboundSms] = []
        for msg in parsed:
            if self.seen.has(msg.id):
                continue
            fresh.append(msg)
        # Newest last so chat order matches arrival when several arrive in one poll.
        fresh.sort(key=lambda m: m.time or "")
        for msg in fresh:
            self.seen.mark([msg.id])
            payload = msg.as_payload()
            payload["source"] = "smsgate"
            try:
                from arelis.sms_ingest import RECENT_INBOUND

                RECENT_INBOUND.record(msg, source="smsgate")
            except Exception:
                log.exception(
                    "Failed to record inbound SMS %s into RECENT_INBOUND",
                    msg.id,
                )
            await self.bus.publish(Event(EventType.SMS_RECEIVED, payload))
        self._hard_down_announced = False
        return fresh

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except SmsInboxError as exc:
                log.warning("Inbound SMS poll failed: %s", exc)
                await self._status_throttled(str(exc))
            except httpx.TimeoutException:
                log.warning("Inbound SMS poll timed out contacting SMSGate")
                await self._status_throttled(
                    "Inbound SMS: SMSGate did not answer. Is Local Server Online "
                    "and the phone on this network?"
                )
            except httpx.HTTPError as exc:
                log.warning("Inbound SMS poll HTTP error: %s", exc)
                await self._status_throttled(
                    f"Inbound SMS: could not reach SMSGate ({exc})."
                )
            except Exception:
                log.exception("Inbound SMS poll crashed")
                await self._status_throttled(
                    "Inbound SMS watcher hit an unexpected error; see logs."
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_s)
            except TimeoutError:
                pass

    async def _status_throttled(self, message: str) -> None:
        now = time.monotonic()
        if self._hard_down_announced and (now - self._last_status_at) < STATUS_COOLDOWN_S:
            return
        self._hard_down_announced = True
        self._last_status_at = now
        await self.bus.publish(Event(EventType.STATUS, {"message": message}))

    async def _status_once(self, message: str) -> None:
        await self.bus.publish(Event(EventType.STATUS, {"message": message}))


def _inbox_detail(response: httpx.Response) -> str:
    data = _json(response)
    if isinstance(data, dict):
        message = data.get("message") or data.get("error")
        if message:
            return str(message)
    return response.text.strip()[:200] or "(no detail)"
