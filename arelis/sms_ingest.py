"""LAN ingest for the Android notification companion.

Google Messages RCS never appears in SMSGate's inbox. The companion app reads
Messages notifications on the phone and POSTs them here while the desktop UI
is open. Auth is a shared token from data/secrets.yaml.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from arelis.contacts import load_contacts, match_contact_label, normalize_phone, resolve_contact
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.paths import state_dir
from arelis.sms_inbound import InboundSms, SeenMessageStore

log = logging.getLogger(__name__)

SECRETS_PATH = state_dir() / "secrets.yaml"
TOKEN_ENV = "ARELIS_INGEST_TOKEN"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
RECENT_LIMIT = 40


@dataclass(frozen=True)
class IngestSecrets:
    token: str


def list_lan_ipv4() -> list[str]:
    """Best-effort private IPv4 addresses for companion URL hints."""
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    # Also try the route used for outbound UDP — often the real LAN NIC.
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.insert(0, ip)
        finally:
            probe.close()
    except OSError:
        pass
    return found


def format_ingest_listen_urls(port: int, *, host: str = DEFAULT_HOST) -> str:
    """Human-readable URLs to paste into Arelis Notify."""
    ips = list_lan_ipv4()
    if ips:
        return ", ".join(f"http://{ip}:{port}" for ip in ips[:3])
    if host in {"0.0.0.0", "::", ""}:
        return f"http://<this-pc-lan-ip>:{port}"
    return f"http://{host}:{port}"


def load_ingest_token(path: Path | None = None) -> str | None:
    """Shared secret for POST /inbound/sms, or None when unset."""
    env = (os.environ.get(TOKEN_ENV) or "").strip()
    if env:
        return env
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return None
    section = raw.get("sms") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        return None
    token = str(section.get("ingest_token") or "").strip()
    return token or None


class RecentInboundLog:
    """Ring buffer of announced inbound texts for the inbound_sms tool."""

    def __init__(self, *, limit: int = RECENT_LIMIT) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=max(1, limit))
        self._lock = threading.Lock()

    def record(self, msg: InboundSms, *, source: str = "") -> None:
        item = msg.as_payload()
        item["source"] = source or None
        item["display_from"] = msg.display_from
        with self._lock:
            self._items.appendleft(item)

    def list(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)[: max(1, limit)]


# Process-wide log so the tool and ingest/watcher share one list.
RECENT_INBOUND = RecentInboundLog()


def resolve_inbound_sender(
    from_raw: str,
    *,
    contacts=None,
) -> InboundSms:
    """Build a resolved InboundSms shell for contact fields (id/body filled by caller)."""
    contacts = contacts if contacts is not None else load_contacts()
    raw = (from_raw or "").strip() or "(unknown)"
    contact = resolve_contact(raw, contacts) or match_contact_label(raw, contacts)
    # Prefer E.164 when we know the person; keep the notification label otherwise.
    sender = contact.e164 if contact and contact.e164 else raw
    return InboundSms(
        id="",
        sender=sender,
        body="",
        time="",
        contact_alias=contact.alias if contact else "",
        contact_name=contact.display_name if contact else "",
    )


def parse_ingest_payload(
    data: dict[str, Any],
    *,
    contacts=None,
) -> InboundSms | None:
    """Validate companion JSON into InboundSms, or None to drop."""
    contacts = contacts if contacts is not None else load_contacts()
    body = str(data.get("body") or data.get("text") or "").strip()
    from_raw = str(data.get("from") or data.get("title") or "").strip()
    if not body and not from_raw:
        return None
    if not from_raw:
        from_raw = "(unknown)"

    # Skip empty-body noise and obvious self notifications.
    me = contacts.get("me") if contacts else None
    label_digits = normalize_phone(from_raw)
    if me is not None:
        if me.digits and label_digits and me.digits == label_digits:
            return None
        if match_contact_label(from_raw, contacts) is me and not body:
            return None

    resolved = resolve_inbound_sender(from_raw, contacts=contacts)
    if resolved.contact_alias == "me" and not body:
        return None

    message_id = str(data.get("id") or "").strip()
    if not message_id:
        message_id = f"notif:{uuid4().hex}"
    time_text = str(data.get("time") or "").strip()
    if not time_text:
        time_text = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return InboundSms(
        id=message_id,
        sender=resolved.sender,
        body=body,
        time=time_text,
        contact_alias=resolved.contact_alias,
        contact_name=resolved.contact_name,
    )


async def publish_inbound(
    bus: EventBus,
    msg: InboundSms,
    *,
    seen: SeenMessageStore,
    source: str = "notification",
) -> bool:
    """Deduplicate, record, publish. Returns True when a new event was published."""
    if not msg.id or seen.has(msg.id):
        return False
    seen.mark([msg.id])
    payload = msg.as_payload()
    payload["source"] = source
    RECENT_INBOUND.record(msg, source=source)
    await bus.publish(Event(EventType.SMS_RECEIVED, payload))
    return True


class InboundIngestServer:
    """Threading HTTP server that posts inbound texts onto the event bus."""

    def __init__(
        self,
        bus: EventBus,
        loop: asyncio.AbstractEventLoop,
        *,
        token: str,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        seen: SeenMessageStore | None = None,
    ) -> None:
        self.bus = bus
        self.loop = loop
        self.token = token
        self.host = host
        self.port = int(port)
        self.seen = seen or SeenMessageStore()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                log.debug("ingest %s - %s", self.address_string(), fmt % args)

            def _token_ok(self) -> bool:
                auth = self.headers.get("Authorization") or ""
                if auth.lower().startswith("bearer "):
                    got = auth[7:].strip()
                else:
                    got = (self.headers.get("X-Arelis-Token") or "").strip()
                return bool(got) and got == server.token

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0]
                # No auth: lets the companion distinguish "PC unreachable" from
                # "wrong token" when Test ping fails.
                if path in {"/inbound/health", "/health"}:
                    self._reply(
                        200,
                        {
                            "ok": True,
                            "service": "arelis-inbound",
                            "auth": "required for /inbound/ping",
                        },
                    )
                    return
                if path in {"/inbound/ping", "/ping"}:
                    if not self._token_ok():
                        self._reply(401, {"ok": False, "error": "unauthorized"})
                        return
                    self._reply(200, {"ok": True, "service": "arelis-inbound"})
                    return
                self._reply(404, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                if path not in {"/inbound/sms", "/inbound/message"}:
                    self._reply(404, {"ok": False, "error": "not found"})
                    return
                if not self._token_ok():
                    self._reply(401, {"ok": False, "error": "unauthorized"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(max(0, length)) if length else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._reply(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(data, dict):
                    self._reply(400, {"ok": False, "error": "expected object"})
                    return
                msg = parse_ingest_payload(data)
                if msg is None:
                    log.info(
                        "Inbound ingest ignored (filter/empty/self) keys=%s from=%r",
                        sorted(str(k) for k in data.keys()),
                        data.get("from") or data.get("sender") or data.get("title"),
                    )
                    self._reply(202, {"ok": True, "accepted": False, "reason": "ignored"})
                    return
                source = str(data.get("source") or "notification")
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        publish_inbound(
                            server.bus, msg, seen=server.seen, source=source
                        ),
                        server.loop,
                    )
                    published = bool(fut.result(timeout=10))
                except Exception as exc:
                    log.exception("Inbound ingest publish failed")
                    self._reply(500, {"ok": False, "error": str(exc)})
                    return
                if published:
                    log.info(
                        "Inbound ingest published id=%s from=%s source=%s",
                        msg.id,
                        msg.sender,
                        source,
                    )
                else:
                    log.info(
                        "Inbound ingest duplicate id=%s (published=false) from=%s",
                        msg.id,
                        msg.sender,
                    )
                self._reply(
                    200,
                    {
                        "ok": True,
                        "accepted": True,
                        "published": published,
                        "id": msg.id,
                    },
                )

            def _reply(self, code: int, body: dict[str, Any]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="arelis-sms-ingest",
            daemon=True,
        )
        self._thread.start()
        log.info("Inbound ingest listening on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        thread = self._thread
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)
