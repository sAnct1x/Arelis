"""Execute a restored pending send confirm after the user Allows in the UI."""

from __future__ import annotations

import logging
from typing import Any

from arelis.core.event_audit import log_side_effect
from arelis.core.receipts import action_receipt, append_action_ledger
from arelis.core.turn_telemetry import log_span, turn_telemetry_enabled
from arelis.mail import Mailer, load_account
from arelis.presence.pending_confirms import PendingConfirm
from arelis.sms import DEFAULT_MAX_BODY_CHARS
from arelis.sms_android import AndroidSmsProvider, load_sms_account
from arelis.tools.email_send import SendEmailTool
from arelis.tools.sms_send import SendSmsTool

log = logging.getLogger(__name__)


async def execute_pending_confirm(
    item: PendingConfirm,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Run the tool for a stored confirm. Never called without an Allow click."""
    tool = item.tool
    args = dict(item.args)
    confirm_id = str(getattr(item, "id", "") or "")
    log.info(
        "Executing restored confirm id=%s tool=%s",
        confirm_id or "?",
        tool,
    )
    try:
        if tool == "send_sms":
            account = load_sms_account()
            if account is None:
                return _finish(
                    False,
                    "SMS is not configured (data/secrets.yaml sms block).",
                    tool=tool,
                    confirm_id=confirm_id,
                    config=config,
                )
            sms_cfg = (config.get("tools") or {}).get("sms") or {}
            send = SendSmsTool(
            AndroidSmsProvider(
                account,
                timeout_s=float(sms_cfg.get("timeout_s", 30)),
                live=True,
            ),
                max_body_chars=int(sms_cfg.get("max_body_chars", DEFAULT_MAX_BODY_CHARS)),
            )
            result = await send.run(**args)
            return _finish(
                result.ok,
                result.output,
                tool=tool,
                confirm_id=confirm_id,
                config=config,
                args=args,
                data=dict(result.data or {}),
            )
        if tool == "send_email":
            account = load_account()
            if account is None:
                return _finish(
                    False,
                    "Email is not configured.",
                    tool=tool,
                    confirm_id=confirm_id,
                    config=config,
                )
            email_cfg = (config.get("tools") or {}).get("email") or {}
            mailer = Mailer(
                account,
                host=email_cfg.get("smtp_host", "smtp.gmail.com"),
                port=int(email_cfg.get("smtp_port", 587)),
                from_name=email_cfg.get("from_name", "Arelis"),
                timeout_s=float(email_cfg.get("timeout_s", 30)),
            )
            send = SendEmailTool(account, mailer)
            result = await send.run(**args)
            return _finish(
                result.ok,
                result.output,
                tool=tool,
                confirm_id=confirm_id,
                config=config,
                args=args,
                data=dict(result.data or {}),
            )
        return _finish(
            False,
            f"Cannot restore confirm for tool {tool!r}.",
            tool=tool,
            confirm_id=confirm_id,
            config=config,
        )
    except Exception:
        log.exception(
            "Restored confirm failed id=%s tool=%s", confirm_id or "?", tool
        )
        raise


def _finish(
    ok: bool,
    output: str,
    *,
    tool: str,
    confirm_id: str,
    config: dict[str, Any],
    args: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    level = log.info if ok else log.warning
    level(
        "Restored confirm id=%s tool=%s ok=%s: %s",
        confirm_id or "?",
        tool,
        ok,
        (output or "")[:200],
    )
    log_side_effect(
        "restored_send",
        tool=tool,
        ok=ok,
        confirm_id=confirm_id,
        detail=output,
    )
    if turn_telemetry_enabled(config):
        log_span(
            "restored_send",
            tool=tool,
            ok=ok,
            confirm=confirm_id or "-",
        )
    # Same operational truth as in-loop sends — restored Allow must leave a
    # ledger line when SMTP/SMS actually succeeded.
    if ok:
        receipt = action_receipt(tool, ok=True, args=args or {}, data=data or {})
        if receipt is not None:
            append_action_ledger(receipt)
    return ok, output
