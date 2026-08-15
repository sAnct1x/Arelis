"""Start/stop inbound SMS ingest, optional SMSGate poll, and auto-reply.

Shared by the desktop UI and `arelis --core` so closing a window is not the
only way to keep port 8765 alive.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from arelis.core.bus import EventBus
from arelis.presence.ports import candidates
from arelis.sms import DEFAULT_MAX_BODY_CHARS
from arelis.sms_android import AndroidSmsProvider, load_sms_account
from arelis.sms_auto_reply import SmsAutoReply
from arelis.sms_inbound import InboundSmsWatcher, SeenMessageStore
from arelis.sms_ingest import (
    InboundIngestServer,
    format_ingest_listen_urls,
    load_ingest_token,
)
from arelis.tools.sms_send import SendSmsTool

log = logging.getLogger(__name__)


@dataclass
class InboundRuntime:
    """Handles owned by whoever started inbound (UI or core)."""

    ingest: InboundIngestServer | None = None
    watcher: InboundSmsWatcher | None = None
    auto_reply: SmsAutoReply | None = None
    seen: SeenMessageStore = field(default_factory=SeenMessageStore)
    status_messages: list[str] = field(default_factory=list)
    # When False, close/shutdown paths must not stop these services.
    owned: bool = True

    async def stop(self) -> None:
        if not self.owned:
            return
        if self.ingest is not None:
            try:
                self.ingest.stop()
            except Exception:
                log.exception("Stopping inbound ingest failed")
            self.ingest = None
        if self.watcher is not None:
            try:
                await self.watcher.stop()
            except Exception:
                log.exception("Stopping SMSGate inbox watcher failed")
            self.watcher = None
        if self.auto_reply is not None:
            try:
                self.auto_reply.stop()
            except Exception:
                log.exception("Stopping SMS auto-reply failed")
            self.auto_reply = None


def _bind_ingest(
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    *,
    token: str,
    host: str,
    preferred_port: int,
    seen: SeenMessageStore,
) -> tuple[InboundIngestServer | None, OSError | None]:
    """Start ingest on the preferred port, or the next free one above it.

    A server is constructed per attempt because binding happens in ``start()``,
    so a failed candidate leaves nothing to reset. Only the successful one is
    ever returned, and the caller learns which port it got from ``server.port``.
    """
    last_error: OSError | None = None
    for candidate in candidates(preferred_port):
        server = InboundIngestServer(
            bus,
            loop,
            token=token,
            host=host,
            port=candidate,
            seen=seen,
        )
        try:
            server.start()
        except OSError as exc:
            last_error = exc
            continue
        return server, None
    return None, last_error


def attach_inbound(
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    *,
    owned: bool = True,
    stay_open_hint: str | None = None,
    headless: bool = False,
) -> InboundRuntime:
    """Create and start inbound services. Does not publish status events."""
    runtime = InboundRuntime(owned=owned)
    sms_cfg = (config.get("tools") or {}).get("sms") or {}
    if not sms_cfg.get("enabled", True):
        return runtime

    inbound_cfg = sms_cfg.get("inbound") or {}
    ingest_cfg = inbound_cfg.get("ingest") or {}
    shared_seen = runtime.seen

    if inbound_cfg.get("enabled", True) and ingest_cfg.get("enabled", True):
        token = load_ingest_token()
        ingest_port = int(ingest_cfg.get("port") or 8765)
        ingest_host = str(ingest_cfg.get("host") or "0.0.0.0")
        if token:
            server, last_error = _bind_ingest(
                bus,
                loop,
                token=token,
                host=ingest_host,
                preferred_port=ingest_port,
                seen=shared_seen,
            )
            if server is None:
                tried = candidates(ingest_port)
                runtime.status_messages.append(
                    f"Inbound notify could not bind any port from {tried[0]} to "
                    f"{tried[-1]}: {last_error}"
                )
            else:
                runtime.ingest = server
                urls = format_ingest_listen_urls(server.port, host=ingest_host)
                # Keep this short: long STATUS used to paint into chat like a
                # Sources line (R6). Full setup lives in docs / Settings help.
                primary = urls.split(",")[0].strip() if urls else urls
                if server.port == ingest_port:
                    runtime.status_messages.append(
                        f"Inbound notify ready — Phone Notify URL: {primary}"
                    )
                else:
                    # The one case worth spending extra words on: the URL the
                    # user already typed into their phone now points at somebody
                    # else's Arelis, and no error will ever be shown for that.
                    runtime.status_messages.append(
                        f"Port {ingest_port} was already in use, so inbound "
                        f"notify is on {server.port} instead — update the phone "
                        f"companion to {primary}"
                    )
        else:
            runtime.status_messages.append(
                "Inbound notify companion needs sms.ingest_token "
                "in data/secrets.yaml (see secrets.example.yaml)."
            )

        if inbound_cfg.get("fallback_smsgate", True):
            sms_account = load_sms_account()
            if sms_account is not None and sms_account.supports_inbox_poll():
                runtime.watcher = InboundSmsWatcher(
                    bus,
                    sms_account,
                    poll_interval_s=float(inbound_cfg.get("poll_interval_s", 4)),
                    timeout_s=float(sms_cfg.get("timeout_s", 30)),
                    seen=shared_seen,
                )
                asyncio.run_coroutine_threadsafe(runtime.watcher.start(), loop)

    # Auto-reply: still confirm-gated. Starts even when disabled so a config
    # flip is enough; handlers no-op until enabled and allowlisted.
    auto_cfg = sms_cfg.get("auto_reply") or {}
    sms_account = load_sms_account()
    send_tool = None
    if sms_account is not None:
        send_tool = SendSmsTool(
            AndroidSmsProvider(
                sms_account,
                timeout_s=float(sms_cfg.get("timeout_s", 30)),
            ),
            max_body_chars=int(sms_cfg.get("max_body_chars", DEFAULT_MAX_BODY_CHARS)),
        )
    runtime.auto_reply = SmsAutoReply(
        bus, config, send_tool=send_tool, headless=headless
    )
    runtime.auto_reply.start()
    if bool(auto_cfg.get("enabled", False)):
        runtime.status_messages.append(
            "SMS auto-reply on for allowlisted contacts "
            "(every draft still needs the confirm card)."
        )
    return runtime
