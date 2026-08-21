"""Inner HTTP envelopes. Ciphertext to the mailbox, plaintext only on the ends."""

from __future__ import annotations

import base64
import json
from typing import Any


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=False)


def encode_request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes = b"",
    stream: bool = False,
) -> bytes:
    payload: dict[str, Any] = {
        "v": 1,
        "method": method.upper(),
        "path": path,
        "headers": dict(headers or {}),
        "stream": bool(stream),
    }
    if body:
        payload["body_b64"] = b64(body)
    return json.dumps(payload, separators=(",", ":")).encode()


def decode_request(raw: bytes) -> dict[str, Any]:
    obj = json.loads(raw.decode())
    if not isinstance(obj, dict) or int(obj.get("v") or 0) != 1:
        raise ValueError("bad request envelope")
    method = str(obj.get("method") or "GET").upper()
    path = str(obj.get("path") or "")
    if not path.startswith("/"):
        raise ValueError("path must be absolute")
    headers = obj.get("headers") if isinstance(obj.get("headers"), dict) else {}
    body = unb64(str(obj.get("body_b64") or "")) if obj.get("body_b64") else b""
    return {
        "method": method,
        "path": path,
        "headers": {str(k): str(v) for k, v in headers.items()},
        "body": body,
        "stream": bool(obj.get("stream")),
    }


def encode_response(status: int, body: bytes, *, content_type: str = "") -> bytes:
    payload: dict[str, Any] = {"v": 1, "kind": "once", "status": int(status)}
    if content_type:
        payload["content_type"] = content_type
    if body:
        payload["body_b64"] = b64(body)
    return json.dumps(payload, separators=(",", ":")).encode()


def decode_response(raw: bytes) -> dict[str, Any]:
    obj = json.loads(raw.decode())
    if not isinstance(obj, dict) or int(obj.get("v") or 0) != 1:
        raise ValueError("bad response envelope")
    body = unb64(str(obj.get("body_b64") or "")) if obj.get("body_b64") else b""
    return {
        "kind": str(obj.get("kind") or "once"),
        "status": int(obj.get("status") or 0),
        "content_type": str(obj.get("content_type") or ""),
        "body": body,
        "text": str(obj.get("text") or ""),
    }


def encode_chunk(text: str) -> bytes:
    return json.dumps(
        {"v": 1, "kind": "chunk", "text": text},
        separators=(",", ":"),
    ).encode()


def encode_end(status: int) -> bytes:
    return json.dumps(
        {"v": 1, "kind": "end", "status": int(status)},
        separators=(",", ":"),
    ).encode()
