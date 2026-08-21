"""IMAP mailbox: peek to read, Allow to change.

Looking does not mark mail read (readonly select + BODY.PEEK). Attachments
are named, never downloaded. Trash / archive / move / flags need Allow, and
unattended jobs do not get those actions. Delivered mail cannot be rewritten.
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
_FROM_IN_ASK = re.compile(r"(?i)\bfrom\s+([A-Za-z0-9._%+\-@]+)")
_UID_SPLIT = re.compile(r"[\s,;]+")

INBOX_READ_ACTIONS = frozenset(
    {"list", "search", "read", "summarize", "folders"}
)
INBOX_WRITE_ACTIONS = frozenset(
    {
        "trash",
        "delete",
        "archive",
        "mark_read",
        "mark_unread",
        "move",
        "create_folder",
    }
)
_ALL_ACTIONS = INBOX_READ_ACTIONS | INBOX_WRITE_ACTIONS
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


def _inbox_schema(*, mutate: bool) -> dict[str, Any]:
    actions = ["list", "search", "read", "summarize", "folders"]
    if mutate:
        actions.extend(
            [
                "trash",
                "delete",
                "archive",
                "mark_read",
                "mark_unread",
                "move",
                "create_folder",
            ]
        )
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": actions,
                "description": (
                    "list / search / read / summarize (peek-only), folders, "
                    "or with Allow: trash, archive, mark_read, mark_unread, "
                    "move, create_folder. delete is trash (Gmail Bin)."
                ),
            },
            "id": {
                "type": "string",
                "description": (
                    "Message id from list or search. Required for read, trash, "
                    "archive, mark_read, mark_unread, move. Comma-separated ok."
                ),
            },
            "folder": {
                "type": "string",
                "description": "Mailbox or Gmail label, for move or create_folder",
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


def _inbox_description(*, mutate: bool) -> str:
    head = (
        "Read and organise the user's email. `list` shows recent unread "
        "messages by default (pass unread_only=false for everything), `search` "
        "finds them by sender, subject, or text, `read` opens one by its id, "
        "`summarize` returns a structured triage (subject/from/date/snippet) "
        "via BODY.PEEK only, and `folders` lists mailboxes/labels. Looking "
        "does not mark mail read. Attachments are named, never downloaded. "
        "Delivered mail cannot be edited — send a new message instead."
    )
    if not mutate:
        return (
            head
            + " This session cannot change the mailbox (jobs are read-only)."
        )
    return (
        head
        + " Changes need Allow: `trash` (delete is the same — Gmail Bin, not "
        "permanent), `archive` (leave Inbox), `mark_read` / `mark_unread`, "
        "`move` to a folder/label, `create_folder`. Call list or search first "
        "and pass the id in brackets. Never claim a change without a tool "
        "result this turn."
    )


class InboxTool:
    name = "inbox"
    description = _inbox_description(mutate=True)
    risk = "read"
    parameters_schema: dict[str, Any] = _inbox_schema(mutate=True)

    def __init__(
        self,
        account: MailAccount,
        *,
        host: str = "imap.gmail.com",
        port: int = 993,
        timeout_s: float = 30.0,
        max_messages: int = 20,
        max_body_chars: int = 4000,
        allow_mutate: bool = True,
    ) -> None:
        self.account = account
        self.host = host
        self.port = port
        self.timeout_s = timeout_s
        self.max_messages = max_messages
        self.max_body_chars = max_body_chars
        self.allow_mutate = allow_mutate
        self.last_hits: list[dict[str, Any]] = []
        if not allow_mutate:
            self.description = _inbox_description(mutate=False)
            self.parameters_schema = _inbox_schema(mutate=False)

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "list").strip().lower()
        if action == "delete":
            action = "trash"
            kwargs = {**kwargs, "action": "trash"}
        allowed = _ALL_ACTIONS if self.allow_mutate else INBOX_READ_ACTIONS
        if action not in allowed:
            if action in INBOX_WRITE_ACTIONS:
                return ToolResult(
                    ok=False,
                    output="Jobs cannot change the mailbox. Ask in chat so Allow can run.",
                )
            extra = ""
            if action == "edit":
                extra = (
                    " Delivered mail cannot be edited. Trash it or send a new message."
                )
            verbs = ", ".join(sorted(allowed))
            return ToolResult(
                ok=False,
                output=f"Unknown action {action!r}. Use {verbs}.{extra}",
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
        writable = action in INBOX_WRITE_ACTIONS
        with self._connect(writable=writable) as conn:
            if action == "read":
                return self._read(conn, str(kwargs.get("id") or "").strip())
            if action == "folders":
                return self._folders(conn)
            if action == "create_folder":
                return self._create_folder(conn, str(kwargs.get("folder") or "").strip())
            if action in INBOX_WRITE_ACTIONS:
                return self._change(conn, action, kwargs)
            criteria = _list_criteria(action, kwargs)
            limit = _clamp(kwargs.get("limit"), self.max_messages)
            if action == "summarize":
                return self._summarize(conn, criteria, limit)
            return self._list(conn, criteria, limit, searching=action == "search")

    def _connect(self, *, writable: bool = False) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout_s)
        conn.login(self.account.address, self.account.password)
        # readonly so the act of looking does not set the \Seen flag. Without
        # it, asking "anything new?" would answer no the second time.
        conn.select("INBOX", readonly=not writable)
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
            self.last_hits = []
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
        self.last_hits = [
            {"id": r.uid, "from": r.sender, "subject": r.subject}
            for r in found
        ]

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
        sender = _decode(message.get("From"))
        subject = _decode(message.get("Subject"))
        self.last_hits = [{"id": uid, "from": sender, "subject": subject}]
        return ToolResult(
            ok=True,
            output="\n".join(header) + "\n\n" + truncated + note,
            data={
                "id": uid,
                "from": sender,
                "subject": subject,
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
            self.last_hits = []
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

        self.last_hits = [
            {"id": r["id"], "from": r["from"], "subject": r["subject"]} for r in rows
        ]
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

    def _folders(self, conn: imaplib.IMAP4_SSL) -> ToolResult:
        boxes = _list_mailboxes(conn)
        if not boxes:
            return ToolResult(ok=False, output="Could not list folders.")
        lines = [f"{len(boxes)} folder(s):"]
        for name, flags in boxes:
            flag = f"  [{', '.join(sorted(flags))}]" if flags else ""
            lines.append(f"- {name}{flag}")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"folders": [{"name": n, "flags": sorted(f)} for n, f in boxes]},
        )

    def _create_folder(self, conn: imaplib.IMAP4_SSL, name: str) -> ToolResult:
        folder = name.strip().strip('"')
        if not folder or len(folder) > 80:
            return ToolResult(
                ok=False,
                output="create_folder needs a short folder or label name.",
            )
        if any(ch in folder for ch in "\r\n"):
            return ToolResult(ok=False, output="Folder name cannot contain a newline.")
        status, data = conn.create(_quote(folder))
        if status != "OK":
            detail = _as_text(data[0] if data else status)
            return ToolResult(
                ok=False,
                output=f"Could not create {folder}: {detail}",
            )
        return ToolResult(
            ok=True,
            output=f"Created folder {folder}.",
            data={"folder": folder, "action": "create_folder"},
        )

    def _change(
        self, conn: imaplib.IMAP4_SSL, action: str, kwargs: dict[str, Any]
    ) -> ToolResult:
        uids = _parse_uids(str(kwargs.get("id") or ""))
        if not uids:
            return ToolResult(
                ok=False,
                output=(
                    "Missing id. List or search first, then pass the number "
                    "in brackets (comma-separated is fine)."
                ),
            )
        uid_blob = ",".join(uids)
        labels = self._peek_labels(conn, uids)
        if action == "trash":
            dest = _special_mailbox(conn, "trash") or "[Gmail]/Trash"
            _uid_move(conn, uid_blob, dest)
            verb = f"Moved {len(uids)} message(s) to Trash"
        elif action == "archive":
            dest = _special_mailbox(conn, "all") or _special_mailbox(conn, "archive")
            if dest:
                _uid_move(conn, uid_blob, dest)
            else:
                _uid_store(conn, uid_blob, "+FLAGS", r"(\Deleted)")
                _uid_expunge(conn, uid_blob)
            verb = f"Archived {len(uids)} message(s) out of Inbox"
        elif action == "mark_read":
            _uid_store(conn, uid_blob, "+FLAGS", r"(\Seen)")
            verb = f"Marked {len(uids)} message(s) read"
        elif action == "mark_unread":
            _uid_store(conn, uid_blob, "-FLAGS", r"(\Seen)")
            verb = f"Marked {len(uids)} message(s) unread"
        elif action == "move":
            dest = str(kwargs.get("folder") or "").strip().strip('"')
            if not dest:
                return ToolResult(
                    ok=False,
                    output="move needs folder (a mailbox or Gmail label from folders).",
                )
            _uid_move(conn, uid_blob, dest)
            verb = f"Moved {len(uids)} message(s) to {dest}"
        else:
            return ToolResult(ok=False, output=f"Unknown action {action!r}.")
        named = "; ".join(labels) if labels else uid_blob
        return ToolResult(
            ok=True,
            output=f"{verb}: {named}.",
            data={"action": action, "ids": uids, "subjects": labels},
        )

    def _peek_labels(self, conn: imaplib.IMAP4_SSL, uids: list[str]) -> list[str]:
        out: list[str] = []
        for uid in uids[:20]:
            headers = self._headers(conn, uid)
            if headers is None:
                out.append(uid)
            else:
                out.append(f"{headers.subject} ({headers.sender})")
        return out


def fill_inbox_args(
    args: dict[str, Any],
    *,
    user_text: str = "",
    last_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Fill trash/archive/mark/move ids from the last list or search."""
    out = dict(args)
    action = str(out.get("action") or "").strip().lower()
    if action == "delete":
        out["action"] = "trash"
        action = "trash"
    if action not in {"trash", "archive", "mark_read", "mark_unread", "move"}:
        return out
    if str(out.get("id") or "").strip():
        return out
    hits = list(last_hits or [])
    sender = str(out.get("sender") or "").strip()
    if not sender:
        match = _FROM_IN_ASK.search(user_text or "")
        if match:
            sender = match.group(1)
    if sender:
        needle = sender.lower()
        filtered = [
            h
            for h in hits
            if needle in str(h.get("from") or "").lower()
            or needle in str(h.get("sender") or "").lower()
        ]
        if filtered:
            hits = filtered
    ids = [str(h.get("id") or "").strip() for h in hits if str(h.get("id") or "").strip()]
    if ids:
        out["id"] = ",".join(ids[:20])
    return out


def draft_inbox_mutate_args(
    user_text: str,
    last_hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """trash when last_hits name the mail; otherwise search so the next fill can."""
    filled = fill_inbox_args(
        {"action": "trash"},
        user_text=user_text,
        last_hits=last_hits,
    )
    if str(filled.get("id") or "").strip():
        return filled
    match = _FROM_IN_ASK.search(user_text or "")
    sender = match.group(1) if match else ""
    if sender:
        return {"action": "search", "sender": sender}
    return {"action": "search", "text": " ".join((user_text or "").split())[:80]}


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
    return _clean_mail_body(body), attachments


_INVISIBLE_MAIL = re.compile(
    r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f"
    r"\u034f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]"
)


def _clean_mail_body(text: str) -> str:
    """Drop format/invisible sludge (ZWSP, CGJ) and collapse empty-line runs."""
    raw = _INVISIBLE_MAIL.sub("", text or "")
    lines: list[str] = []
    blank = 0
    for line in raw.splitlines():
        clipped = line.rstrip()
        if not clipped.strip():
            blank += 1
            if blank <= 1:
                lines.append("")
            continue
        blank = 0
        lines.append(clipped)
    return "\n".join(lines).strip()


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


def _parse_uids(raw: str) -> list[str]:
    parts = [p for p in _UID_SPLIT.split((raw or "").strip()) if p]
    return [p for p in parts if p.isdigit()][:20]


def _list_mailboxes(conn: imaplib.IMAP4_SSL) -> list[tuple[str, frozenset[str]]]:
    try:
        status, data = conn.list()
    except (imaplib.IMAP4.error, OSError):
        return []
    if status != "OK" or not data:
        return []
    out: list[tuple[str, frozenset[str]]] = []
    for raw in data:
        parsed = _parse_mailbox_list_line(raw)
        if parsed is not None:
            out.append(parsed)
    return out


def _parse_mailbox_list_line(raw: Any) -> tuple[str, frozenset[str]] | None:
    text = _as_text(raw).strip()
    if not text.startswith("("):
        return None
    close = text.find(")")
    if close < 0:
        return None
    flags = frozenset(
        a.lstrip("\\").lower() for a in text[1:close].split() if a and a != "\\noselect"
    )
    rest = text[close + 1 :].strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        rest = rest[end + 1 :].strip() if end >= 0 else rest
    name = rest.strip()
    if name.startswith('"') and name.endswith('"') and len(name) >= 2:
        name = name[1:-1]
    name = name.replace('\\"', '"')
    if not name:
        return None
    return name, flags


def _special_mailbox(conn: imaplib.IMAP4_SSL, kind: str) -> str:
    want = kind.lower()
    aliases = {
        "trash": frozenset({"trash"}),
        "all": frozenset({"all", "allmail"}),
        "archive": frozenset({"archive"}),
    }
    wanted = aliases.get(want, frozenset({want}))
    for name, flags in _list_mailboxes(conn):
        lowered = {f.replace("\\", "") for f in flags}
        if lowered & wanted:
            return name
        leaf = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if want == "trash" and leaf in {"trash", "bin"}:
            return name
        if want == "all" and leaf in {"all mail", "allmail"}:
            return name
    return ""


def _uid_store(conn: imaplib.IMAP4_SSL, uids: str, op: str, flags: str) -> None:
    status, data = conn.uid("STORE", uids, op, flags)
    if status != "OK":
        detail = _as_text(data[0] if data else status)
        raise imaplib.IMAP4.error(f"STORE failed: {detail}")


def _uid_expunge(conn: imaplib.IMAP4_SSL, uids: str) -> None:
    try:
        status, _ = conn.uid("EXPUNGE", uids)
        if status == "OK":
            return
    except (imaplib.IMAP4.error, TypeError, AttributeError):
        pass
    conn.expunge()


def _uid_move(conn: imaplib.IMAP4_SSL, uids: str, dest: str) -> None:
    quoted = _quote(dest)
    try:
        status, data = conn.uid("MOVE", uids, quoted)
    except (imaplib.IMAP4.error, TypeError, AttributeError):
        status, data = "NO", []
    if status == "OK":
        return
    status, data = conn.uid("COPY", uids, quoted)
    if status != "OK":
        detail = _as_text(data[0] if data else status)
        raise imaplib.IMAP4.error(f"Could not copy to {dest}: {detail}")
    _uid_store(conn, uids, "+FLAGS", r"(\Deleted)")
    _uid_expunge(conn, uids)


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
