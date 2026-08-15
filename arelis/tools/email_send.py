from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.mail import MailAccount, Mailer, explain_smtp_error, valid_address
from arelis.tools.base import ToolResult


class SendEmailTool:
    """Send mail to anyone, once the user has approved this particular message.

    There is no recipient allowlist, deliberately. The boundary that keeps a
    scraped page or an injected email from mailing a stranger is capability,
    not configuration: this tool is only registered when a person is present to
    read the confirm card, and the scheduled job runner never registers it at
    all -- it mails the answer itself, to an address fixed when the job was
    created.
    """

    name = "send_email"
    description = (
        "Send an email. Use this when the user asks you to email something, "
        "to them or to anyone else. Leave `to` empty to send it to the user. "
        "Optional `attach` is a file path the user named (PDF, etc.). "
        "The user sees and approves every message before it goes."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient address. Omit to send to the user.",
            },
            "subject": {"type": "string", "description": "Subject line"},
            "body": {
                "type": "string",
                "description": "Message body. Markdown is fine and renders.",
            },
            "attach": {
                "type": "string",
                "description": (
                    "Optional absolute or workspace path to attach (PDF, image, …). "
                    "Only use a path the user named or that was Allowed for read."
                ),
            },
            "path": {
                "type": "string",
                "description": "Alias for attach.",
            },
        },
        "required": ["subject", "body"],
    }

    def __init__(self, account: MailAccount, mailer: Mailer) -> None:
        self.account = account
        self.mailer = mailer

    async def run(self, **kwargs: Any) -> ToolResult:
        subject = str(kwargs.get("subject") or "").strip()
        body = str(kwargs.get("body") or "").strip()
        attach_raw = str(kwargs.get("attach") or kwargs.get("path") or "").strip()
        if not body and not attach_raw:
            return ToolResult(
                ok=False,
                output="[fail:send_email] Missing body. Do not claim the email was sent.",
            )
        if not subject:
            subject = (
                Path(attach_raw).name if attach_raw else "A message from Arelis"
            )
        if not body and attach_raw:
            body = f"Please see the attached file ({Path(attach_raw).name})."

        from arelis.core.email_complete import repair_email_address

        requested = repair_email_address(str(kwargs.get("to") or ""))
        if requested:
            to = requested
        else:
            to = self.account.recipient("")
        if not valid_address(to):
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:send_email] {to!r} is not a usable email address. "
                    "Ask the user for the address rather than guessing one. "
                    "Do not claim the email was sent."
                ),
            )

        attachments: list[Path] = []
        if attach_raw:
            from arelis.core.email_complete import resolve_attach_path

            resolved = resolve_attach_path(attach_raw)
            path = Path(resolved) if resolved else Path(attach_raw)
            if not path.is_file():
                return ToolResult(
                    ok=False,
                    output=(
                        f"[fail:send_email] Attachment not found: {attach_raw}. "
                        "Ask for an absolute path that exists on disk "
                        "(or re-attach the file). Do not claim the email was sent."
                    ),
                )
            attachments.append(path)

        try:
            message_id = await self.mailer.send_async(
                to=to,
                subject=subject,
                body=body,
                attachments=attachments or None,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:send_email] {explain_smtp_error(exc)} "
                    "Do not claim the email was sent."
                ),
            )

        note = ""
        if attachments:
            note = f" Attachment: {attachments[0].name}."
        return ToolResult(
            ok=True,
            output=f"Sent email to {to}.{note}",
            data={
                "to": to,
                "subject": subject,
                "message_id": message_id,
                "attach": str(attachments[0]) if attachments else "",
            },
        )
