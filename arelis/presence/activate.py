"""Activate an already-running glass via core IPC (second-instance path)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from arelis.presence.ipc import (
    assert_loopback_host,
    bye_message,
    decode_line,
    encode_line,
    hello_message,
    open_ui_request_message,
)

log = logging.getLogger(__name__)


def activate_existing_ui(config: dict[str, Any] | None = None) -> bool:
    """Best-effort: hello + open_ui_request + bye on the core IPC port."""
    presence = (config or {}).get("presence") or {}
    if not bool(presence.get("ipc_enabled", True)):
        return False
    try:
        host = assert_loopback_host(str(presence.get("ipc_host") or "127.0.0.1"))
        port = int(presence.get("ipc_port") or 8766)
    except ValueError:
        return False
    try:
        return asyncio.run(_activate(host, port))
    except Exception as exc:
        log.info("Could not activate existing UI via IPC: %s", exc)
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
        # Wait briefly for hello_ack (optional).
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            decode_line(line)
        except Exception:
            pass
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
