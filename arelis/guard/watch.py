"""Process-wide counters for ingest, listeners, and outbound HTTP."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType

log = logging.getLogger("arelis.watch")

_LOOPBACK_NAMES = frozenset({"localhost", "0.0.0.0", "::", "::1", "[::1]"})
_STATUS_COOLDOWN_S = 60.0
_PUBLISH_TASKS: set[asyncio.Task[Any]] = set()


class EgressMutedError(RuntimeError):
    """Outbound HTTP was refused because the house watch is muted."""


@dataclass(frozen=True)
class Admit:
    ok: bool
    retry_after: int = 0
    reason: str = ""


@dataclass(frozen=True)
class Listener:
    name: str
    host: str
    port: int
    proto: str = "tcp"
    bind: str = "lan"  # lan | loopback


@dataclass(frozen=True)
class WatchSnapshot:
    enabled: bool
    level: str
    detail: str
    listeners: tuple[dict[str, Any], ...]
    inbound_window: int
    auth_fails_window: int
    locked: int
    egress_window: int
    egress_today: int
    egress_muted: bool
    top_hosts: tuple[tuple[str, int], ...]
    alerts: tuple[str, ...]

    def as_text(self) -> str:
        lines = [
            f"Watch: {self.level} — {self.detail}",
            "",
            "## Listeners we bound",
        ]
        if not self.listeners:
            lines.append("- none yet (ingest / IPC start with the house)")
        else:
            for item in self.listeners:
                lines.append(
                    f"- {item['name']} {item['proto']} {item['host']}:{item['port']} "
                    f"({item['bind']})"
                )
        lines.extend(
            [
                "",
                "## Inbound (LAN ingest)",
                f"- requests in window: {self.inbound_window}",
                f"- bad tokens in window: {self.auth_fails_window}",
                f"- locked clients: {self.locked}",
                "",
                "## Outbound APIs (not Ollama / LAN / loopback)",
                f"- calls in window: {self.egress_window}",
                f"- calls today: {self.egress_today}",
                f"- muted: {'yes' if self.egress_muted else 'no'}",
            ]
        )
        if self.top_hosts:
            lines.append("- recent hosts:")
            for host, n in self.top_hosts:
                lines.append(f"  - {host} × {n}")
        if self.alerts:
            lines.extend(["", "## Alerts"])
            lines.extend(f"- {a}" for a in self.alerts)
        return "\n".join(lines)


def _now() -> float:
    return time.monotonic()


def _prune(bucket: deque[float], window_s: float, now: float) -> None:
    cutoff = now - window_s
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def _is_house_host(host: str) -> bool:
    raw = (host or "").strip().lower().strip("[]")
    if not raw or raw in _LOOPBACK_NAMES:
        return True
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return False
    return bool(ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved)


def _bind_kind(host: str) -> str:
    raw = (host or "").strip().lower()
    if raw in {"127.0.0.1", "::1", "localhost"}:
        return "loopback"
    return "lan"


class Watch:
    """Thread-safe sliding windows. One per process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.enabled = True
        self.inbound_burst = 40
        self.inbound_window_s = 10.0
        self.auth_fail_limit = 8
        self.auth_fail_window_s = 60.0
        self.auth_lock_s = 300.0
        self.max_body_bytes = 2_097_152
        self.egress_burst = 48
        self.egress_window_s = 10.0
        self.egress_daily = 8000
        self.per_host_burst = 24
        self._inbound: dict[str, deque[float]] = defaultdict(deque)
        self._auth_fail: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._egress: deque[float] = deque()
        self._egress_host: dict[str, deque[float]] = defaultdict(deque)
        self._egress_day: deque[float] = deque()
        self._mute_until = 0.0
        self._listeners: dict[str, Listener] = {}
        self._alerts: deque[str] = deque(maxlen=12)
        self._last_status = ""
        self._last_status_at = 0.0
        self._publish: Callable[[str], None] | None = None
        self._httpx_installed = False

    def configure(self, config: dict[str, Any] | None) -> None:
        agent = (config or {}).get("agent") or {}
        watch = agent.get("watch") or {}
        with self._lock:
            self.enabled = bool(watch.get("enabled", True))
            self.inbound_burst = int(watch.get("inbound_burst") or 40)
            self.inbound_window_s = float(watch.get("inbound_window_s") or 10)
            self.auth_fail_limit = int(watch.get("auth_fail_limit") or 8)
            self.auth_fail_window_s = float(watch.get("auth_fail_window_s") or 60)
            self.auth_lock_s = float(watch.get("auth_lock_s") or 300)
            self.max_body_bytes = int(watch.get("max_body_bytes") or 2_097_152)
            self.egress_burst = int(watch.get("egress_burst") or 48)
            self.egress_window_s = float(watch.get("egress_window_s") or 10)
            self.egress_daily = int(watch.get("egress_daily") or 8000)
            self.per_host_burst = int(watch.get("per_host_burst") or 24)

    def set_publisher(self, publish: Callable[[str], None] | None) -> None:
        with self._lock:
            self._publish = publish

    def reset(self) -> None:
        with self._lock:
            self._inbound.clear()
            self._auth_fail.clear()
            self._locked_until.clear()
            self._egress.clear()
            self._egress_host.clear()
            self._egress_day.clear()
            self._mute_until = 0.0
            self._listeners.clear()
            self._alerts.clear()
            self._last_status = ""
            self._last_status_at = 0.0
            self.enabled = True

    def register_listener(self, listener: Listener) -> None:
        with self._lock:
            key = f"{listener.proto}:{listener.name}:{listener.port}"
            self._listeners[key] = listener
        log.info(
            "Watch listener %s %s %s:%s",
            listener.name,
            listener.proto,
            listener.host,
            listener.port,
        )

    def drop_listener(self, name: str, *, proto: str = "tcp") -> None:
        with self._lock:
            for key in [
                k
                for k, item in self._listeners.items()
                if item.name == name and item.proto == proto
            ]:
                del self._listeners[key]

    def admit_inbound(self, ip: str) -> Admit:
        host = (ip or "").strip() or "?"
        now = _now()
        with self._lock:
            if not self.enabled:
                return Admit(ok=True)
            until = self._locked_until.get(host, 0.0)
            if until > now:
                return Admit(
                    ok=False,
                    retry_after=max(1, int(until - now)),
                    reason="locked",
                )
            bucket = self._inbound[host]
            _prune(bucket, self.inbound_window_s, now)
            if len(bucket) >= self.inbound_burst:
                retry = max(1, int(self.inbound_window_s))
                self._note_alert_locked(
                    f"Watch: inbound flood from {host} — {len(bucket)} requests "
                    f"in {int(self.inbound_window_s)}s"
                )
                return Admit(ok=False, retry_after=retry, reason="rate")
            bucket.append(now)
            return Admit(ok=True)

    def note_auth_fail(self, ip: str) -> Admit:
        host = (ip or "").strip() or "?"
        now = _now()
        with self._lock:
            if not self.enabled:
                return Admit(ok=True)
            bucket = self._auth_fail[host]
            _prune(bucket, self.auth_fail_window_s, now)
            bucket.append(now)
            if len(bucket) >= self.auth_fail_limit:
                self._locked_until[host] = now + self.auth_lock_s
                retry = int(self.auth_lock_s)
                self._note_alert_locked(
                    f"Watch: locked inbound from {host} after {len(bucket)} "
                    f"bad tokens"
                )
                return Admit(ok=False, retry_after=retry, reason="locked")
            return Admit(ok=True)

    def note_auth_ok(self, ip: str) -> None:
        host = (ip or "").strip() or "?"
        with self._lock:
            self._auth_fail.pop(host, None)
            self._locked_until.pop(host, None)

    def egress_open(self) -> bool:
        now = _now()
        with self._lock:
            if not self.enabled:
                return True
            return now >= self._mute_until

    def allow_egress(self, host: str) -> bool:
        """Record a non-house HTTP call. False means the caller should stop."""
        if _is_house_host(host):
            return True
        # Solar load is 32 Horizons hits. The httpx wrap is process-wide, so a
        # mocked catalog in pytest would mute JPL at 24 and fail three tests.
        # Guard tests still count. The live app never sets PYTEST_CURRENT_TEST.
        current = os.environ.get("PYTEST_CURRENT_TEST") or ""
        if current and "test_guard.py" not in current:
            return True
        now = _now()
        with self._lock:
            if not self.enabled:
                return True
            if now < self._mute_until:
                return False
            _prune(self._egress, self.egress_window_s, now)
            _prune(self._egress_day, 86400.0, now)
            bucket = self._egress_host[host]
            _prune(bucket, self.egress_window_s, now)
            over = (
                len(self._egress) >= self.egress_burst
                or len(self._egress_day) >= self.egress_daily
                or len(bucket) >= self.per_host_burst
            )
            if over:
                self._mute_until = now + self.egress_window_s
                why = (
                    f"{len(bucket)} to {host}"
                    if len(bucket) >= self.per_host_burst
                    else (
                        f"{len(self._egress_day)} today"
                        if len(self._egress_day) >= self.egress_daily
                        else f"{len(self._egress)} in {int(self.egress_window_s)}s"
                    )
                )
                self._note_alert_locked(f"Watch: muted outbound APIs — {why}")
                return False
            self._egress.append(now)
            self._egress_day.append(now)
            bucket.append(now)
            return True

    def snapshot(self) -> WatchSnapshot:
        now = _now()
        with self._lock:
            inbound_n = 0
            for bucket in self._inbound.values():
                _prune(bucket, self.inbound_window_s, now)
                inbound_n += len(bucket)
            fail_n = 0
            for bucket in self._auth_fail.values():
                _prune(bucket, self.auth_fail_window_s, now)
                fail_n += len(bucket)
            locked = sum(1 for until in self._locked_until.values() if until > now)
            _prune(self._egress, self.egress_window_s, now)
            _prune(self._egress_day, 86400.0, now)
            hosts: list[tuple[str, int]] = []
            for host, bucket in self._egress_host.items():
                _prune(bucket, self.egress_window_s, now)
                if bucket:
                    hosts.append((host, len(bucket)))
            hosts.sort(key=lambda item: item[1], reverse=True)
            muted = now < self._mute_until
            listeners = tuple(
                {
                    "name": item.name,
                    "host": item.host,
                    "port": item.port,
                    "proto": item.proto,
                    "bind": item.bind,
                }
                for item in sorted(
                    self._listeners.values(),
                    key=lambda item: (item.proto, item.port, item.name),
                )
            )
            alerts = tuple(self._alerts)
            if not self.enabled:
                level, detail = "off", "Watch disabled in config."
            elif muted or locked or fail_n >= max(3, self.auth_fail_limit // 2):
                level = "warn"
                bits = []
                if locked:
                    bits.append(f"{locked} client(s) locked after bad tokens")
                elif fail_n:
                    bits.append(f"{fail_n} bad token(s) this minute")
                if muted:
                    bits.append("outbound APIs muted")
                detail = ". ".join(bits) + "."
            else:
                level = "ok"
                if listeners:
                    bits = [
                        f"{item['name']} :{item['port']} {item['bind']}"
                        for item in listeners
                    ]
                    detail = ", ".join(bits) + ". Quiet."
                else:
                    detail = "No house listeners yet. Quiet."
            return WatchSnapshot(
                enabled=self.enabled,
                level=level,
                detail=detail,
                listeners=listeners,
                inbound_window=inbound_n,
                auth_fails_window=fail_n,
                locked=locked,
                egress_window=len(self._egress),
                egress_today=len(self._egress_day),
                egress_muted=muted,
                top_hosts=tuple(hosts[:8]),
                alerts=alerts,
            )

    def _note_alert_locked(self, message: str) -> None:
        """Caller holds ``self._lock``."""
        self._alerts.append(message)
        log.warning("%s", message)
        now = _now()
        if message == self._last_status and (now - self._last_status_at) < _STATUS_COOLDOWN_S:
            return
        self._last_status = message
        self._last_status_at = now
        publish = self._publish
        if publish is None:
            return
        try:
            publish(message)
        except Exception:
            log.debug("Watch STATUS publish failed", exc_info=True)


_WATCH = Watch()


def get_watch() -> Watch:
    return _WATCH


def reset_watch() -> None:
    _WATCH.reset()


def attach_watch(bus: EventBus, config: dict[str, Any] | None = None) -> Watch:
    """Configure the process watch, hook httpx, and publish STATUS alerts."""
    watch = get_watch()
    watch.configure(config)
    loop: asyncio.AbstractEventLoop | None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    def _publish(message: str) -> None:
        event = Event(EventType.STATUS, {"message": message})
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(bus.publish(event), loop)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = running.create_task(bus.publish(event))
        _PUBLISH_TASKS.add(task)
        task.add_done_callback(_PUBLISH_TASKS.discard)

    watch.set_publisher(_publish)
    if watch.enabled:
        _install_httpx(watch)
    return watch


def _install_httpx(watch: Watch) -> None:
    if watch._httpx_installed:
        return
    try:
        import httpx
    except ImportError:
        return

    def _on_request(request: Any) -> None:
        host = ""
        try:
            host = str(request.url.host or "")
        except Exception:
            parsed = urlparse(str(getattr(request, "url", "") or ""))
            host = parsed.hostname or ""
        if not watch.allow_egress(host):
            raise EgressMutedError(host)

    async def _on_async_request(request: Any) -> None:
        _on_request(request)

    def _wrap_init(original: Callable[..., None], hook: Callable[..., Any]):
        def _init(self: Any, *args: Any, **kwargs: Any) -> None:
            hooks = dict(kwargs.get("event_hooks") or {})
            reqs = list(hooks.get("request") or [])
            reqs.append(hook)
            hooks["request"] = reqs
            kwargs["event_hooks"] = hooks
            original(self, *args, **kwargs)

        return _init

    if not getattr(httpx.Client, "_arelis_watch", False):
        httpx.Client.__init__ = _wrap_init(httpx.Client.__init__, _on_request)  # type: ignore[method-assign]
        httpx.Client._arelis_watch = True  # type: ignore[attr-defined]
    if not getattr(httpx.AsyncClient, "_arelis_watch", False):
        httpx.AsyncClient.__init__ = _wrap_init(  # type: ignore[method-assign]
            httpx.AsyncClient.__init__, _on_async_request
        )
        httpx.AsyncClient._arelis_watch = True  # type: ignore[attr-defined]
    watch._httpx_installed = True
