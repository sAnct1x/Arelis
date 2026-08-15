"""Read-only access to the user's mailbox over IMAP.

Read-only in three separate senses, because this is the first input source a
stranger controls and the blast radius should be as small as it can be:

- The mailbox is opened with readonly=True and every fetch uses BODY.PEEK, so
  asking Arelis what arrived does not mark anything as read.
- There is no delete, archive, or move action. A bug or an injected instruction
  cannot lose your mail because there is no code here that could.
- Attachments are named, never downloaded.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from arelis.mail import MailAccount
from arelis.tools.base import ToolResult
from arelis.tools.html_text import extract_text
from arelis.tools.safety import redact_secrets

log = logging.getLogger(__name__)

_SNIPPET_CHARS = 160
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


@dataclass(frozen=True)
class Headers:
    uid: str
    sender: str
    subject: str
    date: str
    unread: bool


class InboxTool:
    name = "inbox"
    description = (
        "Read the user's email. `list` shows recent unread messages by default "
        "(pass unread_only=false for everything), `search` finds them by "
        "sender, subject, or text, `read` opens one by its id, and `summarize` "
        "returns a structured triage of recent mail (subject/from/date/snippet) "
        "via BODY.PEEK only. Strictly read-only: there is no delete, trash, "
        "archive, move, or mark-as-read action. If asked to change the mailbox, "
        "refuse and say the user must do that in Gmail."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "search", "read", "summarize"],
                "description": (
                    "list recent mail, search it, read one message, or summarize "
                    "recent mail (peek-only subject/from/date/snippet)"
                ),
            },
            "id": {
                "type": "string",
                "description": "Message id, for action=read. Comes from list or search.",
            },
            "sender": {
                "type": "string",
                "description": "Filter by sender, for search or summarize",
            },
            "subject": {
                "type": "string",
                "description": "Filter by subject, for search or summarize",
            },
            "text": {
                "type": "string",
                "description": "Filter by body text, for search or summarize",
            },
            "since": {
                "type": "string",
                "description": "Only mail on or after this date, as YYYY-MM-DD",
            },
            "unread_only": {
                "type": "boolean",
                "description": (
                    "Only unread messages. For list and summarize this defaults "
                    "to true; set false to see all mail. For search it defaults "
                    "to false."
                ),
            },
            "limit": {"type": "integer", "description": "How many messages to return"},
        },
        "required": ["action"],
    }

    def __init__(
        self,
        account: MailAccount,
        *,
        host: str = "imap.gmail.com",
        port: int = 993,
        timeout_s: float = 30.0,
        max_messages: int = 20,
        max_body_chars: int = 4000,
    ) -> None:
        self.account = account
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.max_messages = max_messages
        self.max_body_chars = max_body_chars

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "list").strip().lower()
        if action not in {"list", "search", "read", "summarize"}:
            return ToolResult(
                ok=False,
                output=(
                    f"Unknown action {action!r}. "
                    "Use list, search, read, or summarize."
                ),
            )
        try:
            # imaplib is blocking and a slow mailbox would stall the bus, which
            # also carries stop and confirm traffic.
            return await asyncio.to_thread(self._run_sync, action, kwargs)
        except imaplib.IMAP4.error as exc:
            return ToolResult(ok=False, output=_explain_imap_error(exc))
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not reach the mail server: {exc}")

    # ------------------------------------------------------------- blocking

    def _run_sync(self, action: str, kwargs: dict[str, Any]) -> ToolResult:
        with self._connect() as conn:
            if action == "read":
                return self._read(conn, str(kwargs.get("id") or "").strip())
            criteria = _list_criteria(action, kwargs)
            limit = _clamp(kwargs.get("limit"), self.max_messages)
            if action == "summarize":
                return self._summarize(conn, criteria, limit)
            return self._list(conn, criteria, limit, searching=action == "search")

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout_s)
        conn.login(self.account.address, self.account.password)
        # readonly so the act of looking does not set the \Seen flag. Without
        # it, asking "anything new?" would answer no the second time.
        conn.select("INBOX", readonly=True)
        return conn

    def _list(
        self,
        conn: imaplib.IMAP4_SSL,
        criteria: list[str],
        limit: int,
        *,
        searching: bool,
    ) -> ToolResult:
        status, data = conn.uid("SEARCH", None, *criteria)
        if status != "OK":
            return ToolResult(ok=False, output=f"Mailbox search failed: {status}")
        uids = (data[0] or b"").split()
        match_count = len(uids)
        total, unread = _mailbox_counts(conn)
        unread_only = "UNSEEN" in criteria
        scope = "unread" if unread_only else ("matching" if searching else "all")

        if not uids:
            where = "matching that" if searching else ("unread" if unread_only else "in the inbox")
            summary = f"No messages {where}."
            if total or unread:
                summary += f" Mailbox has {total} messages, {unread} unread."
            return ToolResult(
                ok=True,
                output=summary,
                data={
                    "messages": [],
                    "matched": 0,
                    "total": total,
                    "unread": unread,
                    "unread_only": unread_only,
                },
            )

        # Newest last in IMAP order, and newest is what anyone means by recent.
        chosen = [u.decode() for u in uids[-limit:]][::-1]
        rows = [self._headers(conn, uid) for uid in chosen]
        found = [r for r in rows if r is not None]

        lines: list[str] = []
        for item in found:
            flag = "unread" if item.unread else "read"
            lines.append(f"[{item.uid}] {item.subject}")
            lines.append(f"      from {item.sender}  ·  {item.date}  ·  {flag}")
        lines.append("")
        lines.append(
            f"Showing {len(found)} of {match_count} {scope} "
            f"(mailbox: {total} messages, {unread} unread)."
        )
        lines.append("Open one with inbox(action='read', id='<the number in brackets>').")

        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={
                "messages": [
                    {
                        "id": r.uid,
                        "from": r.sender,
                        "subject": r.subject,
                        "date": r.date,
                        "unread": r.unread,
                    }
                    for r in found
                ],
                "matched": match_count,
                "total": total,
                "unread": unread,
                "unread_only": unread_only,
            },
        )

    def _headers(self, conn: imaplib.IMAP4_SSL, uid: str) -> Headers | None:
        status, data = conn.uid(
            "FETCH", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
        )
        if status != "OK" or not data:
            return None
        raw_flags = ""
        raw_header = b""
        for part in data:
            if isinstance(part, tuple) and len(part) >= 2:
                raw_flags += _as_text(part[0])
                raw_header += part[1] or b""
            elif isinstance(part, bytes | bytearray):
                raw_flags += _as_text(part)
        message = email.message_from_bytes(bytes(raw_header))
        return Headers(
            uid=uid,
            sender=_decode(message.get("From")) or "(unknown sender)",
            subject=_decode(message.get("Subject")) or "(no subject)",
            date=_format_date(message.get("Date")),
            unread="\\Seen" not in raw_flags,
        )

    def _read(self, conn: imaplib.IMAP4_SSL, uid: str) -> ToolResult:
        if not uid.isdigit():
            return ToolResult(
                ok=False,
                output="Missing or malformed id. Use the number from list or search.",
            )
        status, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return ToolResult(ok=False, output=f"No message with id {uid}.")
        message = email.message_from_bytes(data[0][1])
        body, attachments = extract_body(message)

        body = redact_secrets(body).strip()
        truncated = body[: self.max_body_chars]
        note = "" if len(body) <= self.max_body_chars else "\n\n[truncated]"

        header = [
            f"From:    {_decode(message.get('From'))}",
            f"To:      {_decode(message.get('To'))}",
            f"Date:    {_format_date(message.get('Date'))}",
            f"Subject: {_decode(message.get('Subject'))}",
        ]
        if attachments:
            header.append(f"Files:   {', '.join(attachments)} (not downloaded)")
        return ToolResult(
            ok=True,
            output="\n".join(header) + "\n\n" + truncated + note,
            data={
                "id": uid,
                "from": _decode(message.get("From")),
                "subject": _decode(message.get("Subject")),
                "attachments": attachments,
            },
        )

    def _summarize(
        self,
        conn: imaplib.IMAP4_SSL,
        criteria: list[str],
        limit: int,
    ) -> ToolResult:
        """Triage recent mail: headers + short BODY.PEEK snippet, never \\Seen."""
        status, data = conn.uid("SEARCH", None, *criteria)
        if status != "OK":
            return ToolResult(ok=False, output=f"Mailbox search failed: {status}")
        uids = (data[0] or b"").split()
        match_count = len(uids)
        total, unread = _mailbox_counts(conn)
        unread_only = "UNSEEN" in criteria

        if not uids:
            where = "unread" if unread_only else "in the inbox"
            summary = f"No messages {where} to summarize."
            if total or unread:
                summary += f" Mailbox has {total} messages, {unread} unread."
            return ToolResult(
                ok=True,
                output=summary,
                data={
                    "messages": [],
                    "matched": 0,
                    "total": total,
                    "unread": unread,
                    "unread_only": unread_only,
                },
            )

        chosen = [u.decode() for u in uids[-limit:]][::-1]
        rows: list[dict[str, Any]] = []
        lines: list[str] = []
        for uid in chosen:
            headers = self._headers(conn, uid)
            if headers is None:
                continue
            snippet = self._peek_snippet(conn, uid)
            rows.append(
                {
                    "id": headers.uid,
                    "from": headers.sender,
                    "subject": headers.subject,
                    "date": headers.date,
                    "unread": headers.unread,
                    "snippet": snippet,
                }
            )
            flag = "unread" if headers.unread else "read"
            lines.append(f"[{headers.uid}] {headers.subject}")
            lines.append(f"      from {headers.sender}  ·  {headers.date}  ·  {flag}")
            if snippet:
                lines.append(f"      {snippet}")

        lines.append("")
        scope = "unread" if unread_only else "matching"
        lines.append(
            f"Summarized {len(rows)} of {match_count} {scope} "
            f"(mailbox: {total} messages, {unread} unread)."
        )
        lines.append(
            "Peek-only (BODY.PEEK); nothing was marked read. "
            "Open one with inbox(action='read', id='<the number in brackets>')."
        )
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={
                "messages": rows,
                "matched": match_count,
                "total": total,
                "unread": unread,
                "unread_only": unread_only,
            },
        )

    def _peek_snippet(self, conn: imaplib.IMAP4_SSL, uid: str) -> str:
        """Short body preview via BODY.PEEK — never sets \\Seen."""
        status, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return ""
        message = email.message_from_bytes(data[0][1])
        body, _attachments = extract_body(message)
        text = redact_secrets(body).strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) <= _SNIPPET_CHARS:
            return text
        return text[: _SNIPPET_CHARS - 1] + "…"


# ------------------------------------------------------------------ helpers


def extract_body(message: Message) -> tuple[str, list[str]]:
    """Plain text if the sender provided it, otherwise the HTML reduced to text."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[str] = []

    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = str(part.get("Content-Disposition") or "").lower()
        if filename or "attachment" in disposition:
            attachments.append(_decode(filename) or "(unnamed)")
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            # A charset Python does not know is common in spam and in very old
            # mail. Falling back beats dropping the message.
            text = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain":
            text_parts.append(text)
        elif part.get_content_type() == "text/html":
            html_parts.append(text)

    if text_parts:
        body = "\n".join(text_parts)
    elif html_parts:
        _, body = extract_text("\n".join(html_parts))
    else:
        body = ""
    return body.strip(), attachments


def _list_criteria(action: str, kwargs: dict[str, Any]) -> list[str]:
    """IMAP SEARCH terms for list/search/summarize.

    list and summarize default to unread-only so a 20k mailbox is not a
    firehose. Pass unread_only=false for the whole inbox. search stays
    opt-in for UNSEEN. summarize may also take sender/subject/text/since.
    """
    if action == "search":
        criteria = _build_criteria(kwargs)
        if bool(kwargs.get("unread_only")):
            criteria.append("UNSEEN")
        return criteria
    if action == "summarize":
        has_filter = any(
            str(kwargs.get(k) or "").strip()
            for k in ("sender", "subject", "text", "since")
        )
        if has_filter:
            criteria = _build_criteria(kwargs)
        else:
            criteria = ["ALL"]
        if "unread_only" in kwargs:
            unread_only = bool(kwargs.get("unread_only"))
        else:
            unread_only = True
        if unread_only and "UNSEEN" not in criteria:
            criteria = [*criteria, "UNSEEN"] if criteria != ["ALL"] else ["UNSEEN"]
        elif not unread_only and criteria == ["ALL"]:
            pass
        return criteria
    if "unread_only" in kwargs:
        unread_only = bool(kwargs.get("unread_only"))
    else:
        unread_only = True
    return ["UNSEEN"] if unread_only else ["ALL"]


def _build_criteria(kwargs: dict[str, Any]) -> list[str]:
    criteria: list[str] = []
    for key, field in (("sender", "FROM"), ("subject", "SUBJECT"), ("text", "TEXT")):
        value = str(kwargs.get(key) or "").strip()
        if value:
            criteria.extend([field, _quote(value)])
    since = _imap_date(str(kwargs.get("since") or "").strip())
    if since:
        criteria.extend(["SINCE", since])
    return criteria or ["ALL"]


def _mailbox_counts(conn: imaplib.IMAP4_SSL) -> tuple[int, int]:
    """(total messages, unread). Best effort; zeros if the server omits STATUS."""
    try:
        status, data = conn.status("INBOX", "(MESSAGES UNSEEN)")
    except (imaplib.IMAP4.error, OSError):
        return 0, 0
    if status != "OK" or not data:
        return 0, 0
    text = _as_text(data[0])
    messages = _status_int(text, "MESSAGES")
    unseen = _status_int(text, "UNSEEN")
    return messages, unseen


def _status_int(text: str, key: str) -> int:
    match = re.search(rf"{key}\s+(\d+)", text, flags=re.IGNORECASE)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def _quote(value: str) -> str:
    """IMAP quoted string. Backslash and quote are the only specials."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _imap_date(value: str) -> str:
    """IMAP wants 06-Aug-2026, everyone else writes 2026-08-06."""
    match = _ISO_DATE.match(value)
    if not match:
        return ""
    year, month, day = (int(g) for g in match.groups())
    if not 1 <= month <= 12:
        return ""
    return f"{day:02d}-{_MONTHS[month - 1]}-{year}"


def _clamp(raw: Any, default: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(default, value))


def _decode(raw: Any) -> str:
    """Undo RFC 2047 header encoding, the =?utf-8?B?...?= form."""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(str(raw)))).strip()
    except (UnicodeDecodeError, LookupError, ValueError):
        return str(raw).strip()


def _format_date(raw: Any) -> str:
    if not raw:
        return "(no date)"
    try:
        parsed = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return str(raw)
    if not isinstance(parsed, datetime):
        return str(raw)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _as_text(raw: Any) -> str:
    if isinstance(raw, bytes | bytearray):
        return bytes(raw).decode("utf-8", errors="replace")
    return str(raw or "")


def _explain_imap_error(exc: Exception) -> str:
    text = str(exc)
    if "AUTHENTICATIONFAILED" in text.upper() or "Invalid credentials" in text:
        return (
            "Gmail rejected the login. It needs an app password rather than "
            "your normal password, and IMAP must be enabled in Gmail settings "
            "under Forwarding and POP/IMAP."
        )
    return f"Mailbox error: {text}"
