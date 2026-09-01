"""Outbound mail, and the one credential both mail features share.

Sending and reading use the same Gmail app password, so the account lives here
rather than inside either tool. It is loaded from data/secrets.yaml, which is
gitignored for the same reason data/profile.yaml is: an address and a password
do not belong in a tracked file.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import yaml

from arelis.paths import state_dir

log = logging.getLogger(__name__)

PASSWORD_ENV = "ARELIS_EMAIL_PASSWORD"
SECRETS_PATH = state_dir() / "secrets.yaml"

# Deliberately loose. Rejecting valid addresses is worse than passing a typo to
# the SMTP server, which will refuse it with a better message than this could.
_ADDRESS = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


@dataclass(frozen=True)
class MailAccount:
    address: str
    password: str
    default_recipient: str = ""

    def recipient(self, requested: str = "") -> str:
        """Where a message goes when the caller did not name someone else.

        "Email me" and jobs with a blank recipient use the user's inbox
        (profile ``user.email`` or ``default_recipient``), never the SMTP
        from-address. That from-address is Arelis — a future user saying
        "email me" must not land in her mailbox.
        """
        asked = (requested or "").strip()
        if asked:
            return asked
        return owner_inbox(self)


def owner_inbox(account: MailAccount | None = None) -> str:
    """The human's inbox: profile email, then default_recipient. Not SMTP from."""
    from arelis.profile import load_profile_email

    profile = (load_profile_email() or "").strip()
    if profile and valid_address(profile):
        return profile
    acc = account
    if acc is None:
        acc = load_account()
    if acc is None:
        return ""
    rec = (acc.default_recipient or "").strip()
    if rec and valid_address(rec):
        return rec
    return ""


def load_account(path: Path | None = None) -> MailAccount | None:
    """Read the account, or None when it has not been set up yet.

    None rather than an exception: the tools check for it and stay unregistered,
    which is how a missing config becomes "she has no email tool" instead of
    "she has one that fails every time she tries it".
    """
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return None

    section = raw.get("email") if isinstance(raw, dict) else None
    data = section if isinstance(section, dict) else {}

    address = str(data.get("address") or "").strip()
    raw_password = os.environ.get(PASSWORD_ENV) or str(data.get("app_password") or "")
    # Google displays app passwords in four groups of four. People paste them
    # exactly as shown, and the spaces are not part of the secret.
    password = "".join(raw_password.split())
    if not (address and password):
        return None
    return MailAccount(
        address=address,
        password=password,
        default_recipient=str(data.get("default_recipient") or "").strip(),
    )


def valid_address(value: str) -> bool:
    return bool(_ADDRESS.match(value.strip()))


class Mailer:
    """A single SMTP send. No connection pooling; sends are rare and far apart."""

    def __init__(
        self,
        account: MailAccount,
        *,
        host: str = "smtp.gmail.com",
        port: int = 587,
        from_name: str = "Arelis",
        timeout_s: float = 30.0,
    ) -> None:
        self.account = account
        self.host = host
        self.port = port
        self.from_name = from_name
        self.timeout_s = timeout_s

    def send(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Path] | None = None,
    ) -> str:
        """Send one message and return its Message-ID. Blocking."""
        message = build_message(
            sender=self.account.address,
            from_name=self.from_name,
            to=to,
            subject=subject,
            body=body,
            attachments=attachments,
        )
        context = ssl.create_default_context()
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(self.account.address, self.account.password)
            smtp.send_message(message)
        return str(message["Message-ID"] or "")

    async def send_async(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        attachments: list[Path] | None = None,
    ) -> str:
        """smtplib is blocking, and a slow handshake would stall the whole bus."""
        return await asyncio.to_thread(
            self.send,
            to=to,
            subject=subject,
            body=body,
            attachments=attachments,
        )


def build_message(
    *,
    sender: str,
    from_name: str,
    to: str,
    subject: str,
    body: str,
    attachments: list[Path] | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((from_name, sender))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    # Markdown is legible as-is, so plain text stays the real body and the HTML
    # is the alternative. A client that refuses HTML still shows something good.
    message.add_alternative(markdown_to_html(body), subtype="html")
    for path in attachments or ():
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Attachment not found: {p}")
        data = p.read_bytes()
        # Guess a basic MIME type from suffix; EmailMessage accepts maintype/subtype.
        suffix = p.suffix.lower().lstrip(".")
        maintype, subtype = "application", "octet-stream"
        if suffix == "pdf":
            maintype, subtype = "application", "pdf"
        elif suffix in {"png", "jpg", "jpeg", "gif", "webp"}:
            maintype = "image"
            subtype = "jpeg" if suffix == "jpg" else suffix
        elif suffix in {"txt", "md", "csv"}:
            maintype, subtype = "text", "plain"
        message.add_attachment(
            data,
            maintype=maintype,
            subtype=subtype,
            filename=p.name,
        )
    return message


def explain_smtp_error(exc: Exception) -> str:
    """Turn an SMTP failure into something the user can act on."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return (
            "Gmail rejected the login. It requires an app password, not your "
            "normal password, and app passwords need 2-Step Verification "
            "switched on. Generate one under Google Account, Security, "
            "App passwords."
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "The mail server refused the recipient address."
    # TimeoutError is an OSError subclass, so this covers a dead network too.
    if isinstance(exc, OSError):
        return f"Could not reach the mail server: {exc}"
    return f"Send failed: {exc}"


# --------------------------------------------------------------- html rendering

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])\s*(?:\1\s*){2,}$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])")
_CODE = re.compile(r"`([^`\n]+)`")
_BARE_URL = re.compile(r"(?<![\"'>=])\bhttps?://[^\s<>\"')]+")

_BODY_STYLE = (
    "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "font-size:15px;line-height:1.5;color:#1a1a1a;max-width:40em"
)


def markdown_to_html(text: str) -> str:
    """A small markdown subset, styled for a mail client rather than for Qt.

    `arelis.ui.markdown` exists but renders Qt rich text with dark-theme colours
    baked into the tags, which would be unreadable on a white background. This
    covers what actually turns up in an answer and nothing else.

    Nothing from the source reaches the output as markup: every span is escaped
    before a tag goes near it. An answer can quote a page she scraped, and that
    page's HTML must not render itself inside your inbox.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    list_tag = ""

    def close_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{'<br/>'.join(paragraph)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = ""

    for line in lines:
        if not line.strip():
            close_paragraph()
            close_list()
            continue
        if _RULE.match(line):
            close_paragraph()
            close_list()
            out.append('<hr style="border:none;border-top:1px solid #ddd" />')
            continue

        heading = _HEADING.match(line)
        if heading:
            close_paragraph()
            close_list()
            level = min(len(heading.group(1)) + 1, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = _BULLET.match(line)
        numbered = None if bullet else _NUMBERED.match(line)
        if bullet or numbered:
            close_paragraph()
            wanted = "ul" if bullet else "ol"
            if list_tag != wanted:
                close_list()
                out.append(f"<{wanted}>")
                list_tag = wanted
            item = (bullet or numbered).group(1)
            out.append(f"<li>{_inline(item)}</li>")
            continue

        close_list()
        paragraph.append(_inline(line.strip()))

    close_paragraph()
    close_list()
    return f'<div style="{_BODY_STYLE}">{"".join(out)}</div>'


def _inline(text: str) -> str:
    escaped = html_lib.escape(text)
    escaped = _CODE.sub(
        lambda m: (
            '<code style="background:#f2f2f2;padding:1px 4px;'
            f'border-radius:3px">{m.group(1)}</code>'
        ),
        escaped,
    )
    escaped = _LINK.sub(lambda m: _anchor(m.group(2), m.group(1)), escaped)
    escaped = _BARE_URL.sub(lambda m: _anchor(m.group(0), m.group(0)), escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    return escaped


def _anchor(href: str, label: str) -> str:
    # Escaping happened before this ran, so the only way a scheme other than
    # http(s) gets here is if the model wrote one. javascript: in a mail client
    # is inert, but a link that goes somewhere unexpected is still worth not
    # making clickable.
    if not href.lower().startswith(("http://", "https://")):
        return label
    return f'<a href="{href}" style="color:#0b5cad">{label}</a>'
