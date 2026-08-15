"""Peek recent mail into the archive for recall.

Opt-in (memory.mail.enabled). Uses readonly IMAP + BODY.PEEK so indexing never
marks messages read. Retention is a sliding window of the newest N messages
(optionally limited by SINCE), not a forever mirror of the mailbox.

Inbox helpers are imported inside methods so this module can load without
pulling arelis.tools (which imports arelis.memory).
"""

from __future__ import annotations

import email
import imaplib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from arelis.mail import MailAccount
from arelis.memory.store import MemoryStore

log = logging.getLogger(__name__)

DEFAULT_MAX_MESSAGES = 40
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_BODY_CHARS = 4000
DEFAULT_MIN_INTERVAL_S = 900.0

_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

FetchFn = Callable[[], list["MailPeek"]]


@dataclass(frozen=True)
class MailPeek:
    uid: str
    sender: str
    subject: str
    date_text: str
    unread: bool
    body: str


class MailIndexer:
    """Sync a bounded window of peeked mail into memory.db."""

    def __init__(
        self,
        store: MemoryStore,
        account: MailAccount,
        *,
        host: str = "imap.gmail.com",
        port: int = 993,
        timeout_s: float = 30.0,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        fetch: FetchFn | None = None,
    ) -> None:
        self.store = store
        self.account = account
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.max_messages = max(1, int(max_messages))
        self.retention_days = max(1, int(retention_days))
        self.max_body_chars = max(200, int(max_body_chars))
        self.min_interval_s = max(60.0, float(min_interval_s))
        self._fetch = fetch
        self._last_sync = 0.0

    def sync_batch(self, *, force: bool = False) -> int:
        """Fetch and upsert up to one window of mail. Returns how many were written."""
        now = time.monotonic()
        if not force and (now - self._last_sync) < self.min_interval_s:
            return 0
        try:
            peeks = self._fetch() if self._fetch is not None else self._fetch_imap()
        except Exception:
            log.exception("Mail index sync failed")
            self._last_sync = now
            return 0

        written = 0
        keep: set[str] = set()
        for item in peeks:
            keep.add(item.uid)
            self.store.upsert_mail_message(
                uid=item.uid,
                sender=item.sender,
                subject=item.subject,
                date_text=item.date_text,
                unread=item.unread,
                body=item.body,
            )
            written += 1
        removed = self.store.delete_mail_not_in(keep)
        self._last_sync = now
        if written or removed:
            log.info(
                "Mail index: upserted %d, pruned %d (window=%d, days=%d)",
                written,
                removed,
                self.max_messages,
                self.retention_days,
            )
        return written

    def _fetch_imap(self) -> list[MailPeek]:
        conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout_s)
        try:
            conn.login(self.account.address, self.account.password)
            # readonly + BODY.PEEK: indexing must never set \Seen.
            conn.select("INBOX", readonly=True)
            since = _imap_since(self.retention_days)
            status, data = conn.uid("SEARCH", None, "SINCE", since)
            if status != "OK":
                raise RuntimeError(f"IMAP SEARCH failed: {status}")
            uids = (data[0] or b"").split()
            chosen = [u.decode() for u in uids[-self.max_messages :]][::-1]
            out: list[MailPeek] = []
            for uid in chosen:
                peek = self._peek_one(conn, uid)
                if peek is not None:
                    out.append(peek)
            return out
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def _peek_one(self, conn: imaplib.IMAP4_SSL, uid: str) -> MailPeek | None:
        from arelis.tools.inbox import _as_text, _decode, _format_date, extract_body
        from arelis.tools.safety import redact_secrets

        status, data = conn.uid("FETCH", uid, "(FLAGS BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return None
        raw_flags = ""
        raw_bytes = b""
        for part in data:
            if isinstance(part, tuple) and len(part) >= 2:
                raw_flags += _as_text(part[0])
                raw_bytes += part[1] or b""
            elif isinstance(part, bytes | bytearray):
                raw_flags += _as_text(part)
        message = email.message_from_bytes(bytes(raw_bytes))
        body, _attachments = extract_body(message)
        body = redact_secrets(body).strip()[: self.max_body_chars]
        return MailPeek(
            uid=uid,
            sender=_decode(message.get("From")) or "(unknown sender)",
            subject=_decode(message.get("Subject")) or "(no subject)",
            date_text=_format_date(message.get("Date")),
            unread="\\Seen" not in raw_flags,
            body=body,
        )


def _imap_since(retention_days: int) -> str:
    when = date.today() - timedelta(days=retention_days)
    return f"{when.day:02d}-{_MONTHS[when.month - 1]}-{when.year}"
