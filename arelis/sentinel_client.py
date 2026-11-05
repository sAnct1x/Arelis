"""Synchronous, fail-soft calls to the running Sentinel bridge.

A thin wrapper over ``sentinel.bridge.client.SentinelClient``. The address and
session token come from ``sentinel_control.bridge_target()`` (the bound
loopback endpoint the child reported, and the token Arelis holds). Every call
returns a dict; when Sentinel is down, unreachable, or refuses the token the
dict is ``{"ok": False, "error": ...}`` with our own wording, never the
bridge's raw error text. No exception reaches the caller and
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
FAILED = "Sentinel could not do that"


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": message}


class _RefusedError(Exception):
    """The bridge answered 401 or 403."""


class _FailedError(Exception):
    """The bridge answered with another non-2xx status."""


async def _post(client, op: str, kwargs: dict[str, Any]) -> Any:
    """One bridge POST. Status decides the outcome before the body is read.

    SentinelClient.command returns resp.json() whatever the status, so the
    bridge's own error text would reach the caller. Post here instead, with
    the client's address and the same token header.
    """
    import httpx
    from sentinel.bridge.protocol import command_headers

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
        resp = await http.post(
            f"{client.base_url}/api/command",
            json={"op": op, **kwargs},
            headers=command_headers(client.token),
        )
    if resp.status_code in (401, 403):
        raise _RefusedError
    if not 200 <= resp.status_code < 300:
        raise _FailedError
    return resp.json()


def _run(coro_factory) -> Any:
    """Run a coroutine on a private loop in a worker thread, at most TIMEOUT_S.

    Callers may be the Qt thread or a thread that already runs a loop, so this
    never touches the caller's loop. wait_for cancels the call at the limit,
    so asyncio.run closes the loop and the thread ends; the join waits for it.
    """
    box: dict[str, Any] = {}

    async def _bounded() -> Any:
        return await asyncio.wait_for(coro_factory(), TIMEOUT_S)

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(_bounded())
        except BaseException as exc:
            box["error"] = exc

    t = threading.Thread(target=_worker, name="arelis-sentinel-call", daemon=True)
    t.start()
    t.join()
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
        result = _run(lambda: _post(client, op, kwargs))
    except _RefusedError:
        return _error(REFUSED)
    except _FailedError:
        log.info("Sentinel bridge returned an error status op=%s", op)
        return _error(FAILED)
    except (httpx.HTTPError, OSError, TimeoutError):
        log.info("Sentinel bridge did not answer op=%s", op)
        return _error(UNREACHABLE)
    except ValueError:
        # Non-JSON reply, e.g. something that is not the bridge.
        log.info("Sentinel bridge gave an unreadable reply op=%s", op)
        return _error(REFUSED)
    if not isinstance(result, dict):
        return _error(REFUSED)
    return result


def ping() -> dict[str, Any]:
    return command("ping")


def snapshot() -> dict[str, Any]:
    return command("snapshot")
