"""Activate an already-running glass via core IPC (second-instance path)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from arelis.identity import is_mine
from arelis.presence.ipc import (
    assert_loopback_host,
    bye_message,
    decode_line,
    encode_line,
    hello_message,
    open_ui_request_message,
)
from arelis.presence.ports import candidates

log = logging.getLogger(__name__)


def activate_existing_ui(config: dict[str, Any] | None = None) -> bool:
    """Best-effort: hello + open_ui_request + bye on this user's core IPC port.

    Returning True means "an already-running Arelis has been asked to show its
    window", and the caller exits on the strength of it. That makes a wrong True
    the worst outcome available here: on a shared PC this used to connect to
    whichever core held 8766, so the second user's launch raised the *first*
    user's window in the first user's session and then quietly exited. From the
    second user's side, double-clicking Arelis did nothing whatsoever.

    So each candidate port is asked whose core it is, and only a matching answer
    counts as activation.
    """
    presence = (config or {}).get("presence") or {}
    if not bool(presence.get("ipc_enabled", True)):
        return False
    try:
        host = assert_loopback_host(str(presence.get("ipc_host") or "127.0.0.1"))
        preferred = int(presence.get("ipc_port") or 8766)
    except ValueError:
        return False
    try:
        return asyncio.run(_activate_any(host, candidates(preferred)))
    except Exception as exc:
        log.info("Could not activate existing UI via IPC: %s", exc)
        return False


async def _activate_any(host: str, ports: list[int]) -> bool:
    for port in ports:
        if await _activate(host, port):
            return True
    return False


async def _activate(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=1.5
        )
    except Exception:
        return False
    try:
        writer.write(encode_line(hello_message(role="ui")))
        await writer.drain()
        # The ack is what names the account, so unlike before it is required
        # rather than best-effort. A core that does not answer, or answers as
        # somebody else, is not one we may raise a window in.
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            ack = decode_line(line)
        except Exception:
            return False
        if not isinstance(ack, dict) or not is_mine(ack.get("instance")):
            return False
        writer.write(
            encode_line(open_ui_request_message(reason="second_instance"))
        )
        await writer.drain()
        writer.write(encode_line(bye_message()))
        await writer.drain()
        return True
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
