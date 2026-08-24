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
import queue
import socket
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

import yaml

from arelis.contacts import load_contacts, match_contact_label, normalize_phone, resolve_contact
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.identity import instance_id
from arelis.mobile import TURN_WAIT_S, MobileHub, decode_data_url_or_b64, ndjson_line
from arelis.paths import state_dir
from arelis.sms_inbound import InboundSms, SeenMessageStore, hydrate_inbound_media

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
    """Human-readable LAN URLs for the phone companion."""
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
    from arelis.sms_media import looks_like_photo_body, save_image_b64

    contacts = contacts if contacts is not None else load_contacts()
    body = str(data.get("body") or data.get("text") or "").strip()
    from_raw = str(data.get("from") or data.get("title") or "").strip()
    image_b64 = str(
        data.get("image_jpeg") or data.get("image_b64") or data.get("media_b64") or ""
    ).strip()
    media_url = str(data.get("media_url") or data.get("image_url") or "").strip()
    if not body and not from_raw and not image_b64 and not media_url:
        return None
    if not from_raw:
        from_raw = "(unknown)"

    # Skip empty-body noise and obvious self notifications.
    me = contacts.get("me") if contacts else None
    label_digits = normalize_phone(from_raw)
    if me is not None:
        if me.digits and label_digits and me.digits == label_digits:
            return None
        if match_contact_label(from_raw, contacts) is me and not body and not image_b64:
            return None

    resolved = resolve_inbound_sender(from_raw, contacts=contacts)
    if resolved.contact_alias == "me" and not body and not image_b64:
        return None

    message_id = str(data.get("id") or "").strip()
    if not message_id:
        message_id = f"notif:{uuid4().hex}"
    time_text = str(data.get("time") or "").strip()
    if not time_text:
        time_text = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    media_path = ""
    media_kind = ""
    if image_b64:
        saved = save_image_b64(image_b64, message_id=message_id)
        if saved is not None:
            media_path = str(saved)
            media_kind = "image"
    if not media_path and media_url.startswith("http"):
        media_kind = media_kind or "image"
    if not body and (media_path or image_b64 or media_url):
        body = "Photo"
        media_kind = media_kind or "photo_chip"
    elif looks_like_photo_body(body) and not media_path:
        media_kind = media_kind or "photo_chip"

    return InboundSms(
        id=message_id,
        sender=resolved.sender,
        body=body,
        time=time_text,
        contact_alias=resolved.contact_alias,
        contact_name=resolved.contact_name,
        media_path=media_path,
        media_url=media_url if media_url.startswith("http") else "",
        media_kind=media_kind,
    )


async def publish_inbound(
    bus: EventBus,
    msg: InboundSms,
    *,
    seen: SeenMessageStore,
    source: str = "notification",
) -> bool:
    """Deduplicate, record, publish. Returns True when a new event was published."""
    from arelis.sms_media import (
        already_published_recent,
        inbound_fingerprint,
        remember_published,
    )

    msg = hydrate_inbound_media(msg)
    if not msg.id or seen.has(msg.id):
        return False
    fp = inbound_fingerprint(
        sender=msg.sender,
        body=msg.body,
        media=msg.media_path or msg.media_url or msg.media_kind,
    )
    if already_published_recent(fp):
        seen.mark([msg.id])
        return False
    seen.mark([msg.id])
    remember_published(fp)
    payload = msg.as_payload()
    payload["source"] = source
    RECENT_INBOUND.record(msg, source=source)
    await bus.publish(Event(EventType.SMS_RECEIVED, payload))
    return True


class _ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """A server that refuses a port somebody else is already listening on.

    ``http.server.HTTPServer`` sets ``allow_reuse_address``, which becomes
    SO_REUSEADDR -- and on Windows that flag permits binding a port another
    socket is already listening on, leaving which of the two receives any given
    connection undefined. That is the worst available outcome for a service whose
    job is to receive text messages: on a shared PC, two accounts' Arelis would
    silently share :8765 and inbound texts would arrive at whichever one the
    operating system felt like, with no error anywhere.

    Refusing instead is what makes the collision visible, and a visible collision
    is what lets the caller fall forward to a port that is genuinely free (see
    ``arelis.presence.ports``).
    """

    allow_reuse_address = False


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
        self.mobile = MobileHub()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._announce = None
        self._mobile_hooked = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        server = self

        def await_session_load(payload: dict[str, Any]) -> dict[str, Any]:
            waiter = server.mobile.begin_load_wait()
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    server.bus.publish(Event(EventType.SESSION_LOAD, payload)),
                    server.loop,
                )
                fut.result(timeout=10)
                result = waiter.get(timeout=15)
            except Exception:
                server.mobile.abandon_load_wait()
                raise
            server.mobile.abandon_load_wait()
            return result if isinstance(result, dict) else {}

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
                            # Which account's Arelis this is. On a shared PC the
                            # port alone cannot answer that, and treating any
                            # reply as our own is how one user's UI ended up
                            # attached to another user's core.
                            "instance": instance_id(),
                            "port": server.port,
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
                if path in {"/mobile/status", "/mobile/persona", "/mobile/chats"}:
                    if not self._token_ok():
                        self._reply(401, {"ok": False, "error": "unauthorized"})
                        return
                    if path == "/mobile/status":
                        qs = parse_qs(urlparse(self.path).query)
                        focus = unquote((qs.get("chat") or [""])[0] or "")
                        self._reply(200, server.mobile.status(focus=focus))
                        return
                    if path == "/mobile/chats":
                        if server.mobile.chats_fn is None:
                            self._reply(
                                503,
                                {
                                    "ok": False,
                                    "error": "Chats wait until the house is back.",
                                },
                            )
                            return
                        current = server.mobile.status().get("chat") or {}
                        self._reply(
                            200,
                            {
                                "ok": True,
                                "chats": server.mobile.list_chats(),
                                "current": current,
                            },
                        )
                        return
                    self._reply(200, server.mobile.persona_payload())
                    return
                if path.startswith("/mobile/file/"):
                    if not self._token_ok():
                        self._reply(401, {"ok": False, "error": "unauthorized"})
                        return
                    glance_id = path.rsplit("/", 1)[-1].strip()
                    got = server.mobile.file_bytes(glance_id)
                    if got is None:
                        self._reply(404, {"ok": False, "error": "gone"})
                        return
                    self._send_bytes(*got)
                    return
                if path in {"/mobile/files", "/mobile/open"}:
                    if not self._token_ok():
                        self._reply(401, {"ok": False, "error": "unauthorized"})
                        return
                    qs = parse_qs(urlparse(self.path).query)
                    rel = unquote((qs.get("path") or [""])[0] or "")
                    if path == "/mobile/files":
                        scope = unquote((qs.get("scope") or ["workspace"])[0] or "workspace")
                        fn = server.mobile.files_fn
                        if fn is None:
                            self._reply(
                                503,
                                {
                                    "ok": False,
                                    "error": "open Arelis on the PC — files live there",
                                },
                            )
                            return
                        try:
                            try:
                                body = fn(
                                    scope,
                                    rel,
                                    unquote((qs.get("room") or [""])[0] or ""),
                                )
                            except TypeError:
                                body = fn(scope, rel)
                        except PermissionError:
                            self._reply(403, {"ok": False, "error": "outside the workspace"})
                            return
                        except FileNotFoundError:
                            self._reply(404, {"ok": False, "error": "not found"})
                            return
                        except Exception as exc:
                            log.exception("mobile files failed")
                            self._reply(500, {"ok": False, "error": str(exc)})
                            return
                        self._reply(200, body)
                        return
                    opener = server.mobile.open_fn
                    if opener is None:
                        self._reply(
                            503,
                            {
                                "ok": False,
                                "error": "open Arelis on the PC — files live there",
                            },
                        )
                        return
                    if not rel.strip():
                        self._reply(400, {"ok": False, "error": "missing path"})
                        return
                    try:
                        got = opener(rel)
                    except PermissionError:
                        self._reply(403, {"ok": False, "error": "outside the workspace"})
                        return
                    except FileNotFoundError:
                        self._reply(404, {"ok": False, "error": "not found"})
                        return
                    except ValueError as exc:
                        self._reply(413, {"ok": False, "error": str(exc)})
                        return
                    except Exception as exc:
                        log.exception("mobile open failed")
                        self._reply(500, {"ok": False, "error": str(exc)})
                        return
                    if got is None:
                        self._reply(404, {"ok": False, "error": "not found"})
                        return
                    self._send_bytes(*got)
                    return
                self._reply(404, {"ok": False, "error": "not found"})

            def do_POST(self) -> None:
                path = self.path.split("?", 1)[0]
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(max(0, length)) if length else b"{}"
                if path in {
                    "/inbound/sms",
                    "/inbound/message",
                    "/inbound/pair",
                    "/mobile/turn",
                    "/mobile/confirm",
                    "/mobile/sync",
                    "/mobile/ack",
                    "/mobile/chat",
                }:
                    pass
                else:
                    self._reply(404, {"ok": False, "error": "not found"})
                    return
                if not self._token_ok():
                    self._reply(401, {"ok": False, "error": "unauthorized"})
                    return
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._reply(400, {"ok": False, "error": "invalid json"})
                    return
                if not isinstance(data, dict):
                    self._reply(400, {"ok": False, "error": "expected object"})
                    return
                if path == "/inbound/pair":
                    from arelis.sms_pairing import apply_pair

                    code, body = apply_pair(data)
                    if code == 200:
                        log.info(
                            "Companion radio %s listen_url=%s",
                            "updated" if body.get("updated") else "paired",
                            body.get("listen_url"),
                        )
                    self._reply(code, body)
                    return
                if path.startswith("/mobile/"):
                    self._handle_mobile_post(path, data)
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

            def _handle_mobile_post(self, path: str, data: dict[str, Any]) -> None:
                if path == "/mobile/ack":
                    server.mobile.ack_notice(str(data.get("id") or ""))
                    self._reply(200, {"ok": True})
                    return
                if path == "/mobile/chat":
                    action = str(data.get("action") or "").strip().lower()
                    session_id = str(data.get("id") or "").strip()
                    steal = bool(data.get("steal"))
                    if action not in {"new", "open"}:
                        self._reply(400, {"ok": False, "error": "action must be new or open"})
                        return
                    if action == "open" and not session_id:
                        self._reply(400, {"ok": False, "error": "id required"})
                        return
                    if not steal:
                        if action == "new":
                            mint = server.mobile.mint_chat_fn
                            if mint is None:
                                self._reply(
                                    503,
                                    {
                                        "ok": False,
                                        "error": "Chats wait until the house is back.",
                                    },
                                )
                                return
                            try:
                                minted = mint() or {}
                            except Exception as exc:
                                self._reply(500, {"ok": False, "error": str(exc)})
                                return
                            focus = str((minted.get("chat") or {}).get("id") or "")
                            body = server.mobile.status(focus=focus)
                            body["ok"] = True
                            self._reply(200, body)
                            return
                        body = server.mobile.status(focus=session_id)
                        if not (body.get("chat") or {}).get("id"):
                            self._reply(404, {"ok": False, "error": "Could not open that chat."})
                            return
                        body["ok"] = True
                        self._reply(200, body)
                        return
                    if server.mobile.busy():
                        self._reply(
                            409,
                            {
                                "ok": False,
                                "error": "Finish or stop the current turn first.",
                            },
                        )
                        return
                    if not server.mobile.session_ready():
                        self._reply(
                            503,
                            {
                                "ok": False,
                                "error": "Chats wait until the house is back.",
                            },
                        )
                        return
                    payload: dict[str, Any] = (
                        {"new": True} if action == "new" else {"session_id": session_id}
                    )
                    try:
                        result = await_session_load(payload)
                    except Exception as exc:
                        self._reply(500, {"ok": False, "error": str(exc)})
                        return
                    if not isinstance(result, dict) or not result.get("ok"):
                        err = ""
                        if isinstance(result, dict):
                            err = str(result.get("error") or "")
                        self._reply(
                            409 if "turn" in err.lower() else 404,
                            {"ok": False, "error": err or "Could not open that chat."},
                        )
                        return
                    self._reply(200, server.mobile.status())
                    return
                if path == "/mobile/confirm":
                    confirm_id = str(data.get("id") or "").strip()
                    raw_decision = str(data.get("decision") or "").strip().lower()
                    decision = "allow" if raw_decision in {"allow", "yes"} else "skip"
                    if not confirm_id:
                        self._reply(400, {"ok": False, "error": "id required"})
                        return
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            server.bus.publish(
                                Event(
                                    EventType.TOOL_CONFIRM_REPLY,
                                    {
                                        "id": confirm_id,
                                        "decision": decision,
                                        "allow_turn": False,
                                        "source": "mobile",
                                    },
                                )
                            ),
                            server.loop,
                        )
                        fut.result(timeout=10)
                    except Exception as exc:
                        self._reply(500, {"ok": False, "error": str(exc)})
                        return
                    server.mobile.clear_confirm(confirm_id)
                    self._reply(200, {"ok": True, "decision": decision})
                    return
                if path == "/mobile/sync":
                    rows = data.get("messages") or []
                    if not isinstance(rows, list):
                        self._reply(400, {"ok": False, "error": "messages must be a list"})
                        return
                    normalized = server.mobile.normalize_sync(rows)
                    if not normalized:
                        self._reply(200, {"ok": True, "copied": 0})
                        return
                    if not server.mobile.session_ready():
                        self._reply(
                            503,
                            {
                                "ok": False,
                                "error": "open Arelis on the PC to copy that talk in",
                            },
                        )
                        return
                    session_id = str(data.get("session_id") or "").strip()
                    current = str(
                        (server.mobile.current_chat() or {}).get("id") or ""
                    )
                    if not session_id:
                        mint = server.mobile.mint_chat_fn
                        if mint is not None:
                            try:
                                minted = mint() or {}
                            except Exception as exc:
                                self._reply(500, {"ok": False, "error": str(exc)})
                                return
                            session_id = str((minted.get("chat") or {}).get("id") or "")
                        else:
                            try:
                                result = await_session_load({"new": True})
                            except Exception as exc:
                                self._reply(500, {"ok": False, "error": str(exc)})
                                return
                            if not result.get("ok"):
                                err = str(result.get("error") or "Could not open that chat.")
                                self._reply(
                                    409 if "turn" in err.lower() else 404,
                                    {"ok": False, "error": err},
                                )
                                return
                            session_id = str(
                                (server.mobile.current_chat() or {}).get("id") or ""
                            )
                    foreign = bool(session_id) and session_id != current
                    if foreign:
                        try:
                            fut = asyncio.run_coroutine_threadsafe(
                                server.bus.publish(
                                    Event(
                                        EventType.MOBILE_SYNC,
                                        {
                                            "messages": normalized,
                                            "session_id": session_id,
                                        },
                                    )
                                ),
                                server.loop,
                            )
                            fut.result(timeout=10)
                        except Exception as exc:
                            self._reply(500, {"ok": False, "error": str(exc)})
                            return
                        body = server.mobile.status(focus=session_id)
                        body["ok"] = True
                        body["copied"] = len(normalized)
                        self._reply(200, body)
                        return
                    if server.mobile.busy():
                        self._reply(
                            409,
                            {
                                "ok": False,
                                "error": "Finish or stop the current turn first.",
                            },
                        )
                        return
                    server.mobile.apply_sync(normalized)
                    try:
                        fut = asyncio.run_coroutine_threadsafe(
                            server.bus.publish(
                                Event(
                                    EventType.MOBILE_SYNC,
                                    {
                                        "messages": normalized,
                                        "session_id": session_id or current,
                                    },
                                )
                            ),
                            server.loop,
                        )
                        fut.result(timeout=10)
                    except Exception as exc:
                        self._reply(500, {"ok": False, "error": str(exc)})
                        return
                    body = server.mobile.status(focus=session_id or current)
                    body["ok"] = True
                    body["copied"] = len(normalized)
                    self._reply(200, body)
                    return
                if path == "/mobile/turn":
                    self._handle_mobile_turn(data)
                    return
                self._reply(404, {"ok": False, "error": "not found"})

            def _handle_mobile_turn(self, data: dict[str, Any]) -> None:
                if not server.mobile.session_ready():
                    self._reply(
                        503,
                        {
                            "ok": False,
                            "error": "open Arelis on the PC — the house is not thinking yet",
                        },
                    )
                    return
                if server.mobile.busy_fn is not None:
                    try:
                        busy = bool(server.mobile.busy_fn())
                    except Exception:
                        busy = False
                    if busy:
                        self._reply(
                            409,
                            {"ok": False, "error": "already in a turn — wait or stop on the PC"},
                        )
                        return
                text = str(data.get("text") or "").strip()
                attachments: list[dict[str, Any]] = []
                image_raw = str(
                    data.get("image_jpeg") or data.get("image_b64") or ""
                ).strip()
                if image_raw:
                    from arelis.attachments import stage_image_bytes

                    blob = decode_data_url_or_b64(image_raw)
                    staged = stage_image_bytes(blob, suffix=".jpg")
                    if staged.errors:
                        self._reply(400, {"ok": False, "error": staged.errors[0]})
                        return
                    attachments = [item.as_dict() for item in staged.ok]
                file_raw = str(data.get("file_b64") or "").strip()
                if file_raw:
                    from arelis.attachments import stage_bytes

                    blob = decode_data_url_or_b64(file_raw)
                    name = str(data.get("file_name") or "upload.bin")
                    staged = stage_bytes(blob, name)
                    if staged.errors:
                        self._reply(400, {"ok": False, "error": staged.errors[0]})
                        return
                    attachments.extend(item.as_dict() for item in staged.ok)
                audio_raw = str(data.get("audio_wav_b64") or data.get("audio_b64") or "").strip()
                if audio_raw:
                    wav = decode_data_url_or_b64(audio_raw)
                    if not wav:
                        self._reply(400, {"ok": False, "error": "audio was empty"})
                        return
                    transcribe = server.mobile.transcribe_fn
                    if transcribe is None:
                        self._reply(
                            501,
                            {"ok": False, "error": "voice is off on the PC — type instead"},
                        )
                        return
                    clip = state_dir() / "drops" / "mobile-voice.wav"
                    try:
                        clip.parent.mkdir(parents=True, exist_ok=True)
                        clip.write_bytes(wav)
                        spoken = transcribe(clip)
                    except Exception as exc:
                        log.exception("mobile transcribe failed")
                        self._reply(500, {"ok": False, "error": str(exc)})
                        return
                    spoken = (spoken or "").strip()
                    if not spoken and not text and not attachments:
                        self._reply(400, {"ok": False, "error": "no speech detected"})
                        return
                    if spoken:
                        text = spoken if not text else f"{text}\n{spoken}"
                if not text and not attachments:
                    self._reply(400, {"ok": False, "error": "empty turn"})
                    return
                payload: dict[str, Any] = {"text": text, "source": "mobile"}
                from arelis.talk_language import normalize as normalize_talk_language

                lang = normalize_talk_language(data.get("language"))
                if lang:
                    payload["language"] = lang
                if data.get("speak") is True:
                    payload["speak"] = True
                if attachments:
                    payload["attachments"] = attachments
                session_id = str(data.get("session_id") or "").strip()
                current = str((server.mobile.current_chat() or {}).get("id") or "")
                restore_id = ""
                if session_id:
                    payload["session_id"] = session_id
                if session_id and current and session_id != current:
                    try:
                        result = await_session_load(
                            {"session_id": session_id, "silent": True}
                        )
                    except Exception as exc:
                        self._reply(500, {"ok": False, "error": str(exc)})
                        return
                    if not result.get("ok"):
                        err = str(result.get("error") or "Could not open that chat.")
                        gone = "no conversation" in err.lower()
                        self._reply(
                            409 if "turn" in err.lower() else 404,
                            {
                                "ok": False,
                                "error": "That chat is gone." if gone else err,
                                "code": "missing_chat" if gone else "",
                            },
                        )
                        return
                    restore_id = current
                    payload["foreign"] = True
                waiter = server.mobile.begin_turn_wait()
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        server.bus.publish(Event(EventType.USER_MESSAGE, payload)),
                        server.loop,
                    )
                    fut.result(timeout=10)
                except Exception as exc:
                    server.mobile.abandon_turn_wait()
                    if restore_id:
                        try:
                            await_session_load({"session_id": restore_id, "silent": True})
                        except Exception:
                            pass
                    self._reply(500, {"ok": False, "error": str(exc)})
                    return
                self.protocol_version = "HTTP/1.0"
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    while True:
                        try:
                            item = waiter.get(timeout=TURN_WAIT_S)
                        except queue.Empty:
                            self.wfile.write(
                                ndjson_line(
                                    {"type": "error", "message": "turn timed out"}
                                )
                            )
                            break
                        if item is None:
                            break
                        self.wfile.write(ndjson_line(item))
                        self.wfile.flush()
                finally:
                    server.mobile.abandon_turn_wait()
                    if restore_id:
                        try:
                            await_session_load(
                                {"session_id": restore_id, "silent": True}
                            )
                        except Exception:
                            log.exception("restore pc seat after phone turn failed")

            def _send_bytes(self, data: bytes, mime: str, name: str) -> None:
                safe = name.replace('"', "")
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header(
                    "Content-Disposition",
                    f'inline; filename="{safe}"',
                )
                self.end_headers()
                self.wfile.write(data)

            def _reply(self, code: int, body: dict[str, Any]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._httpd = _ExclusiveThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="arelis-sms-ingest",
            daemon=True,
        )
        self._thread.start()
        if not self._mobile_hooked:
            for kind in (
                EventType.USER_MESSAGE,
                EventType.ASSISTANT_DELTA,
                EventType.ASSISTANT_RETRACT,
                EventType.ASSISTANT_DONE,
                EventType.ERROR,
                EventType.TOOL_CONFIRM,
                EventType.TOOL_CONFIRM_REPLY,
                EventType.IMAGE_READY,
                EventType.FILE_READY,
                EventType.SESSION_LOADED,
            ):
                self.bus.subscribe(kind, self.mobile.observe)
            self._mobile_hooked = True
        log.info("Inbound ingest listening on http://%s:%s", self.host, self.port)
        try:
            from arelis.lan_announce import LanAnnouncer

            self._announce = LanAnnouncer(instance=instance_id(), http_port=self.port)
            self._announce.start()
        except Exception:
            log.warning("LAN announce did not start; the phone can still use stored IPs", exc_info=True)

    def stop(self) -> None:
        announcer = self._announce
        self._announce = None
        if announcer is not None:
            try:
                announcer.stop()
            except Exception:
                pass
        httpd = self._httpd
        self._httpd = None
        thread = self._thread
        self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)
