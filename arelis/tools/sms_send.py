from __future__ import annotations

from typing import Any

from arelis.contacts import load_contacts
from arelis.sms import (
    DEFAULT_MAX_BODY_CHARS,
    SmsProvider,
    explain_sms_error,
    prepare_body,
    resolve_sms_target,
)
from arelis.tools.base import ToolResult


class SendSmsTool:
    """Text a named contact from the user's own phone, once they approve the card.

    Same capability boundary as send_email: only registered when a person is
    present (allow_send=True). Scheduled jobs never get this tool.
    """

    name = "send_sms"
    description = (
        "Send a text message (SMS) to a named contact from data/contacts.yaml. "
        "Pass to as any of their nicknames (wife, me, myself, my phone, mom, "
        "…). The text goes out through the user's own Android phone, so it "
        "arrives from their number and replies come back to that phone. Never "
        "invent a phone number or alias — if the contact is missing, ask the "
        "user for the number and add them first. The user sees and approves "
        "every message before it goes."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": (
                    "Any nickname for the contact: wife, me, myself, my phone, "
                    "mom, brother, … from data/contacts.yaml."
                ),
            },
            "body": {
                "type": "string",
                "description": "SMS text. Keep it short; very long texts are truncated.",
            },
        },
        "required": ["to", "body"],
    }

    def __init__(
        self,
        provider: SmsProvider,
        *,
        max_body_chars: int = DEFAULT_MAX_BODY_CHARS,
        contacts_loader=load_contacts,
    ) -> None:
        self.provider = provider
        self.max_body_chars = max_body_chars
        self._load_contacts = contacts_loader

    async def run(self, **kwargs: Any) -> ToolResult:
        from arelis.core.sms_complete import normalize_sms_args

        kwargs = normalize_sms_args(dict(kwargs))
        to = str(kwargs.get("to") or "").strip()
        body_raw = str(kwargs.get("body") or "")
        body, truncated = prepare_body(body_raw, max_chars=self.max_body_chars)
        if not to:
            return ToolResult(
                ok=False,
                output=(
                    "[fail:send_sms] Missing recipient. Pass a contact alias. "
                    "Do not claim the text was sent."
                ),
            )
        if not body:
            return ToolResult(
                ok=False,
                output="[fail:send_sms] Missing body. Do not claim the text was sent.",
            )

        contacts = self._load_contacts()
        resolved = resolve_sms_target(to, contacts)
        if isinstance(resolved, str):
            return ToolResult(
                ok=False,
                output=f"[fail:send_sms] {resolved} Do not claim the text was sent.",
            )

        try:
            message_id = await self.provider.send(phone=resolved.phone_e164, body=body)
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=(
                    f"[fail:send_sms] {explain_sms_error(exc)} "
                    "Do not claim the text was sent."
                ),
            )

        note = " (truncated to fit)" if truncated else ""
        return ToolResult(
            ok=True,
            output=(
                f"Sent SMS to {resolved.label} "
                f"({resolved.phone_display}) from your phone.{note}"
            ),
            data={
                "to": resolved.label,
                "alias": resolved.contact.alias if resolved.contact else "",
                "phone": resolved.phone_e164,
                "body": body,
                "message_id": message_id,
                "truncated": truncated,
            },
        )
