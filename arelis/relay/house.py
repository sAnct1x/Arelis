"""PC side of the mailbox. Outbound only; local ingest stays on loopback."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from arelis.identity import instance_id
from arelis.relay.crypto import e2e_key, open_box, seal
from arelis.relay.protocol import (
    b64,
    decode_request,
    encode_chunk,
    encode_end,
    encode_response,
    unb64,
)

log = logging.getLogger(__name__)


class HouseTunnel:
    def __init__(
        self,
        *,
        relay_url: str,
        relay_token: str,
        ingest_token: str,
        local_port: int,
        instance: str | None = None,
    ) -> None:
        self.relay_url = relay_url.rstrip("/")
        self.relay_token = relay_token
        self.ingest_token = ingest_token
        self.local_port = int(local_port)
        self.instance = instance or instance_id()
        self.key = e2e_key(ingest_token, self.instance)
        self.aad = self.instance.encode()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="arelis-house")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="arelis-house-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.relay_token}",
            "Content-Type": "application/json",
        }

    def _loop(self) -> None:
        client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))
        local = httpx.Client(
            base_url=f"http://127.0.0.1:{self.local_port}",
            timeout=httpx.Timeout(600.0, connect=2.0),
        )
        try:
            while not self._stop.is_set():
                try:
                    resp = client.post(
                        f"{self.relay_url}/v1/house/poll",
                        headers=self._headers(),
                        json={"instance": self.instance},
                    )
                except httpx.HTTPError as exc:
                    log.debug("mailbox poll failed: %s", exc)
                    self._stop.wait(2.0)
                    continue
                if resp.status_code == 204:
                    continue
                if resp.status_code == 401:
                    log.warning("Mailbox rejected the relay token.")
                    self._stop.wait(15.0)
                    continue
                if resp.status_code != 200:
                    self._stop.wait(2.0)
                    continue
                try:
                    body = resp.json()
                except ValueError:
                    continue
                if not isinstance(body, dict) or not body.get("call_id"):
                    continue
                self._pool.submit(self._handle, client, local, body)
        finally:
            client.close()
            local.close()

    def _handle(
        self,
        relay: httpx.Client,
        local: httpx.Client,
        body: dict[str, Any],
    ) -> None:
        call_id = str(body.get("call_id") or "")
        stream = bool(body.get("stream"))
        try:
            plaintext = open_box(self.key, unb64(str(body.get("blob") or "")), aad=self.aad)
            req = decode_request(plaintext)
        except Exception:
            log.debug("mailbox call %s was not for this house", call_id)
            self._fail(relay, call_id, stream)
            return
        path = req["path"]
        headers = dict(req["headers"])
        headers.setdefault("X-Arelis-Token", self.ingest_token)
        try:
            if stream:
                with local.stream(
                    req["method"],
                    path,
                    headers=headers,
                    content=req["body"] or None,
                ) as resp:
                    for line in resp.iter_lines():
                        if self._stop.is_set():
                            break
                        if not line:
                            continue
                        text = line.decode() if isinstance(line, bytes) else str(line)
                        chunk = seal(self.key, encode_chunk(text), aad=self.aad)
                        relay.post(
                            f"{self.relay_url}/v1/house/chunk",
                            headers=self._headers(),
                            json={"call_id": call_id, "blob": b64(chunk)},
                        )
                    end = seal(self.key, encode_end(resp.status_code), aad=self.aad)
                    relay.post(
                        f"{self.relay_url}/v1/house/chunk",
                        headers=self._headers(),
                        json={"call_id": call_id, "blob": b64(end)},
                    )
                    relay.post(
                        f"{self.relay_url}/v1/house/chunk",
                        headers=self._headers(),
                        json={"call_id": call_id, "blob": ""},
                    )
                return
            resp = local.request(
                req["method"],
                path,
                headers=headers,
                content=req["body"] or None,
            )
            packed = encode_response(
                resp.status_code,
                resp.content,
                content_type=resp.headers.get("content-type") or "",
            )
            blob = b64(seal(self.key, packed, aad=self.aad))
            relay.post(
                f"{self.relay_url}/v1/house/reply",
                headers=self._headers(),
                json={"call_id": call_id, "blob": blob},
            )
        except Exception:
            log.exception("mailbox call %s failed on the house", call_id)
            self._fail(relay, call_id, stream)

    def _fail(self, relay: httpx.Client, call_id: str, stream: bool) -> None:
        try:
            if stream:
                relay.post(
                    f"{self.relay_url}/v1/house/chunk",
                    headers=self._headers(),
                    json={"call_id": call_id, "blob": ""},
                )
            else:
                relay.post(
                    f"{self.relay_url}/v1/house/reply",
                    headers=self._headers(),
                    json={"call_id": call_id, "blob": ""},
                )
        except httpx.HTTPError:
            return


def start_house_tunnel(
    *,
    relay_url: str,
    relay_token: str,
    ingest_token: str,
    local_port: int,
) -> HouseTunnel | None:
    if not relay_url or not relay_token:
        return None
    tunnel = HouseTunnel(
        relay_url=relay_url,
        relay_token=relay_token,
        ingest_token=ingest_token,
        local_port=local_port,
    )
    tunnel.start()
    log.info("Mailbox house tunnel up")
    return tunnel
