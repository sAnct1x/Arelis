"""Synchronous, fail-soft calls to the running Sentinel bridge.

A thin wrapper over ``sentinel.bridge.client.SentinelClient``. The address and
session token come from ``sentinel_control.bridge_target()`` (the bound
loopback endpoint the child reported, and the token Arelis holds). Every call
returns a dict; when Sentinel is down, unreachable, or refuses the token the
dict is ``{"ok": False, "error": ...}``. No exception reaches the caller and
the token is never logged. No model tool uses this yet.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from arelis import sentinel_control

log = logging.getLogger(__name__)

TIMEOUT_S = 3.0

OFFLINE = "Sentinel is offline"
UNREACHABLE = "Sentinel did not answer"
REFUSED = "Sentinel refused the request"


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


def _run(coro_factory) -> Any:
    """Run a coroutine on a private loop in a worker thread.

    Callers may be the Qt thread or a thread that already runs a loop, so this
    never touches the caller's loop.
    """
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(coro_factory())
        except BaseException as exc:
            box["error"] = exc

    t = threading.Thread(target=_worker, name="arelis-sentinel-call", daemon=True)
    t.start()
    t.join(TIMEOUT_S + 1.0)
    if t.is_alive():
        raise TimeoutError("sentinel call did not finish")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def command(op: str, **kwargs: Any) -> dict[str, Any]:
    """Send one bridge op with the held token. Always returns a dict."""
    target = sentinel_control.bridge_target()
    if target is None:
        return _error(OFFLINE)
    host, port, token = target
    try:
        import httpx
        from sentinel.bridge.client import SentinelClient
    except ImportError:
        log.warning("Sentinel client is not installed")
        return _error(OFFLINE)

    client = SentinelClient(host=host, port=port, token=token, timeout_s=TIMEOUT_S)
    if ":" in host:
        client.host = f"[{host}]"
    try:
        result = _run(lambda: client.command(op, **kwargs))
    except (httpx.HTTPError, OSError, TimeoutError):
        log.info("Sentinel bridge did not answer op=%s", op)
        return _error(UNREACHABLE)
    except ValueError:
        # Non-JSON reply, e.g. a refusal page or something that is not the bridge.
        log.info("Sentinel bridge gave an unreadable reply op=%s", op)
        return _error(REFUSED)
    if not isinstance(result, dict):
        return _error(REFUSED)
    return result


def ping() -> dict[str, Any]:
    return command("ping")


def snapshot() -> dict[str, Any]:
    return command("snapshot")
