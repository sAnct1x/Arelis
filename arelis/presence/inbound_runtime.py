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
    save_ingest_token,
)
from arelis.tools.sms_send import SendSmsTool

log = logging.getLogger(__name__)

PHONE_NOTIFY_NEEDS_PAIRING = (
    "Phone notifications are turned on but not set up yet. "
    "To finish, open Settings, go to Notify, pick Create a pairing code."
)
PHONE_NOTIFY_BIND_FAILED = (
    "Phone notifications couldn't start. Restart Arelis to try again."
)
PHONE_NOTIFY_MOVED = (
    "Phone notifications moved to a new spot. Pair your phone again in Settings, Notify."
)

# Distinct unrecognized ingest.enabled values already warned about this process.
_INGEST_ENABLED_WARNED: set[str] = set()


@dataclass
class InboundRuntime:
    """Handles owned by whoever started inbound (UI or core)."""

    ingest: InboundIngestServer | None = None
    watcher: InboundSmsWatcher | None = None
    auto_reply: SmsAutoReply | None = None
    house: Any = None
    seen: SeenMessageStore = field(default_factory=SeenMessageStore)
    status_messages: list[str] = field(default_factory=list)
    # When False, close/shutdown paths must not stop these services.
    owned: bool = True

    def stop_ingest(self) -> None:
        """Drop the phone listener and house tunnel. Does not touch SMSGate or auto-reply."""
        if not self.owned:
            return
        if self.ingest is not None:
            try:
                self.ingest.stop()
            except Exception:
                log.exception("Stopping inbound ingest failed")
            self.ingest = None
        house = self.house
        if house is not None:
            try:
                house.stop()
            except Exception:
                log.exception("Stopping mailbox tunnel failed")
            self.house = None

    async def stop(self) -> None:
        if not self.owned:
            return
        self.stop_ingest()
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


def ingest_enabled_mode(raw: Any) -> str:
    """Normalize tools.sms.inbound.ingest.enabled to auto, on, or off.

    YAML booleans (true/false/yes/no/on/off) arrive as bool. The only accepted
    string is ``auto``. Quoted ``false`` / ``off`` and any other non-empty
    string do not listen.
    """
    if raw is True:
        return "on"
    if raw is False:
        return "off"
    if isinstance(raw, str):
        text = raw.strip()
        if text.lower() == "auto":
            return "auto"
        key = text.lower()
        if key not in _INGEST_ENABLED_WARNED:
            _INGEST_ENABLED_WARNED.add(key)
            log.warning(
                "Unrecognized tools.sms.inbound.ingest.enabled value %r; "
                "phone notifications will not listen",
                raw,
            )
        return "off"
    if raw is None:
        return "on"
    key = f"{type(raw).__name__}:{raw!r}"
    if key not in _INGEST_ENABLED_WARNED:
        _INGEST_ENABLED_WARNED.add(key)
        log.warning(
            "Unrecognized tools.sms.inbound.ingest.enabled value %r; "
            "phone notifications will not listen",
            raw,
        )
    return "off"


def _ingest_cfg(config: dict[str, Any]) -> dict[str, Any]:
    sms = (config.get("tools") or {}).get("sms") or {}
    inbound = sms.get("inbound") or {}
    ingest = inbound.get("ingest") or {}
    return ingest if isinstance(ingest, dict) else {}


def ingest_wants_listener(config: dict[str, Any], *, token: str | None) -> bool:
    """Whether this config should have a phone listener bound."""
    sms = (config.get("tools") or {}).get("sms") or {}
    if not sms.get("enabled", True):
        return False
    inbound = sms.get("inbound") or {}
    if not inbound.get("enabled", True):
        return False
    mode = ingest_enabled_mode(_ingest_cfg(config).get("enabled", True))
    if mode == "off":
        return False
    if mode == "auto":
        return bool(token)
    return True


def _start_house(runtime: InboundRuntime, token: str, port: int) -> None:
    if runtime.house is not None:
        try:
            runtime.house.stop()
        except Exception:
            log.exception("Stopping mailbox tunnel failed")
        runtime.house = None
    try:
        from arelis.relay.config import load_relay_settings
        from arelis.relay.house import start_house_tunnel

        mailbox = load_relay_settings()
        if mailbox.url and mailbox.token:
            runtime.house = start_house_tunnel(
                relay_url=mailbox.url,
                relay_token=mailbox.token,
                ingest_token=token,
                local_port=port,
            )
            if runtime.house is not None:
                log.info("House tunnel started")
    except Exception:
        log.exception("Mailbox house tunnel failed to start")


def _bind_and_announce(
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    runtime: InboundRuntime,
    token: str,
) -> None:
    ingest_cfg = _ingest_cfg(config)
    ingest_port = int(ingest_cfg.get("port") or 8765)
    ingest_host = str(ingest_cfg.get("host") or "0.0.0.0")
    server, last_error = _bind_ingest(
        bus,
        loop,
        token=token,
        host=ingest_host,
        preferred_port=ingest_port,
        seen=runtime.seen,
    )
    if server is None:
        tried = candidates(ingest_port)
        log.error(
            "Inbound notify could not bind any port from %s to %s: %s",
            tried[0],
            tried[-1],
            last_error,
        )
        runtime.status_messages.append(PHONE_NOTIFY_BIND_FAILED)
        return
    runtime.ingest = server
    urls = format_ingest_listen_urls(server.port, host=ingest_host)
    primary = urls.split(",")[0].strip() if urls else urls
    if server.port == ingest_port:
        runtime.status_messages.append(f"Phone notifications: {primary}")
    else:
        log.info(
            "Port %s was already in use, so inbound notify is on %s instead; "
            "update the phone companion to %s",
            ingest_port,
            server.port,
            primary,
        )
        runtime.status_messages.append(PHONE_NOTIFY_MOVED)
    _start_house(runtime, token, server.port)


def sync_ingest_listener(
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    runtime: InboundRuntime,
) -> InboundRuntime:
    """Start, refresh, or stop owned ingest so this process has at most one listener."""
    token = load_ingest_token()
    want = ingest_wants_listener(config, token=token)
    if not want:
        runtime.stop_ingest()
        return runtime
    if not token:
        ingest_cfg = _ingest_cfg(config)
        if ingest_enabled_mode(ingest_cfg.get("enabled", True)) == "on":
            runtime.status_messages.append(PHONE_NOTIFY_NEEDS_PAIRING)
        return runtime
    if not runtime.owned:
        return runtime
    existing = runtime.ingest
    if existing is not None and existing.running:
        existing.token = token
        if runtime.house is not None:
            _start_house(runtime, token, existing.port)
        return runtime
    if existing is not None:
        runtime.stop_ingest()
    from arelis.presence.lock import find_my_ingest_port

    if find_my_ingest_port(config) is not None:
        return runtime
    _bind_and_announce(bus, loop, config, runtime, token)
    return runtime


def create_pairing_code(
    bus: EventBus,
    loop: asyncio.AbstractEventLoop,
    config: dict[str, Any],
    runtime: InboundRuntime | None = None,
) -> InboundRuntime:
    """Mint a new ingest token and start or refresh the phone listener.

    This is what Settings → Notify → Create a pairing code calls, so a phone
    can pair without restarting Arelis.
    """
    import secrets

    save_ingest_token(secrets.token_urlsafe(24))
    if runtime is None:
        runtime = InboundRuntime(owned=True)
    return sync_ingest_listener(bus, loop, config, runtime)


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
    ingest_mode = ingest_enabled_mode(ingest_cfg.get("enabled", True))

    if inbound_cfg.get("enabled", True) and ingest_mode != "off":
        sync_ingest_listener(bus, loop, config, runtime)

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
                live=True,
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
