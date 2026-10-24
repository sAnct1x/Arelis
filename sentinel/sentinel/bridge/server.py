"""Loopback HTTP and RFC 6455 WebSocket telemetry and command server.

assert_loopback_host rejects non-loopback bind hosts. The default listen
address is 127.0.0.1:8790. ::1 is accepted. No third-party web framework.
Serves:
- GET  / or /overseer        -> 3D Overseer WebGL2 viewport (HTML/CSS/JS), public
- GET  /api/snapshot         -> Current world and swarm telemetry snapshot
- POST /api/command          -> Command execution
- POST /api/overseer/emp     -> Software emergency stop from the Overseer HUD
- POST /api/overseer/theme   -> Theme switcher (sodium | filament | night | matrix)
- GET  /ws/telemetry         -> WebSocket stream of world state to the 3D viewport

Every non-static route goes through one session-token check. HTTP clients send
X-Sentinel-Token. The websocket sends the token as its first hello frame.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import mimetypes
import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from sentinel.bridge.protocol import (
    PROTOCOL_VERSION,
    assert_loopback_host,
    ensure_session_token,
    format_command_response,
    port_candidates,
    token_from_headers,
    verify_session_token,
)
from sentinel.paths import harvest_dir, logs_dir, overseer_static_dir, quarantine_dir

if TYPE_CHECKING:
    from sentinel.core.hive import SwarmHive

log = logging.getLogger("sentinel.bridge")

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_WS_FRAME_BYTES = 262_144  # 256 KiB max inbound WS frame
_MAX_HTTP_BODY_BYTES = 2_097_152  # 2 MiB max HTTP POST body
_MAX_HEADER_COUNT = 64
_MAX_HEADER_LINE = 8192


def _is_public_static(method: str, path: str) -> bool:
    """Static Overseer HTML, CSS, and JS stay public. Command routes do not."""
    if method != "GET":
        return False
    if path in {"/", "/overseer", "/overseer/"}:
        return True
    return path.startswith("/overseer/")


def _is_loopback_origin_and_host(headers: dict[str, str]) -> tuple[bool, str]:
    """Reject Host and Origin header values that are not loopback names."""
    host_hdr = (headers.get("host") or "").strip().lower()
    if host_hdr:
        host_only = host_hdr.split(":")[0].strip("[]")
        if host_only not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return False, f"DNS rebinding / non-loopback Host header blocked: {host_hdr}"

    origin_hdr = (headers.get("origin") or "").strip().lower()
    if origin_hdr and origin_hdr not in {"null", "file://"}:
        parsed = urlparse(origin_hdr)
        orig_host = (parsed.hostname or "").lower()
        if orig_host not in {"127.0.0.1", "localhost", "::1"}:
            return False, f"Cross-Origin browser attack blocked from Origin: {origin_hdr}"
    return True, "ok"


def _ws_encode_text(text: str) -> bytes:
    payload = text.encode("utf-8")
    length = len(payload)
    header = bytearray([0x81])  # FIN + Text frame
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    return bytes(header) + payload


async def _ws_read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes] | None:
    try:
        head = await reader.readexactly(2)
    except (asyncio.IncompleteReadError, ConnectionError):
        return None
    b1, b2 = head[0], head[1]
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    length = b2 & 0x7F
    if length == 126:
        ext = await reader.readexactly(2)
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = await reader.readexactly(8)
        length = struct.unpack("!Q", ext)[0]
    if length > _MAX_WS_FRAME_BYTES:
        return None
    mask_key = await reader.readexactly(4) if masked else b""
    data = await reader.readexactly(length) if length > 0 else b""
    if masked and data:
        unmasked = bytearray(length)
        for i in range(length):
            unmasked[i] = data[i] ^ mask_key[i % 4]
        data = bytes(unmasked)
    return opcode, data


class SentinelBridgeServer:
    """Loopback-only HTTP + 60 Hz WebSocket server connecting Arelis and the 3D Overseer."""

    def __init__(
        self,
        hive: SwarmHive,
        *,
        host: str = "127.0.0.1",
        preferred_port: int = 8790,
        telemetry_hz: int = 30,
        token: str | None = None,
    ) -> None:
        self.hive = hive
        self.host = assert_loopback_host(host)
        self.preferred_port = int(preferred_port)
        self.bound_port: int = 0
        self.telemetry_hz = max(10, min(int(telemetry_hz), 60))
        self.session_token = token or ensure_session_token()
        self._server: asyncio.AbstractServer | None = None
        self._ws_clients: set[asyncio.StreamWriter] = set()
        self._broadcast_task: asyncio.Task[Any] | None = None
        self._static_dir: Path = overseer_static_dir()

    @property
    def overseer_url(self) -> str:
        return f"http://{self.host}:{self.bound_port}/overseer"

    def _session_ok(self, candidate: str | None) -> bool:
        """The one session-token check every command-bridge route uses."""
        return verify_session_token(candidate, self.session_token)

    def _note_auth_fail(self) -> None:
        with contextlib.suppress(Exception):
            wrd = self.hive.registry.get("warden")
            wrd.note_auth_fail("127.0.0.1", port=self.bound_port)  # type: ignore[union-attr]

    def _reject_unauthorized(self, writer: asyncio.StreamWriter) -> None:
        self._note_auth_fail()
        self._write_json(
            401,
            format_command_response(False, error="Unauthorized session token"),
            writer,
        )

    async def start(self) -> int:
        await self.hive.start_background_loops(hz=60)
        last_err: Exception | None = None
        for port in port_candidates(self.preferred_port):
            try:
                self._server = await asyncio.start_server(
                    self._handle_connection,
                    host=self.host,
                    port=port,
                )
                sockets: list[Any] = list(self._server.sockets or [])
                self.bound_port = sockets[0].getsockname()[1] if sockets else port
                break
            except OSError as exc:
                last_err = exc
                continue
        else:
            raise RuntimeError(f"Could not bind Sentinel Bridge near {self.preferred_port}: {last_err}")

        self._broadcast_task = asyncio.create_task(self._telemetry_broadcast_loop())
        log.info("Sentinel Bridge online at %s", self.overseer_url)
        return self.bound_port

    async def stop(self) -> None:
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            await asyncio.gather(self._broadcast_task, return_exceptions=True)
        for writer in list(self._ws_clients):
            with contextlib.suppress(OSError, RuntimeError):
                writer.close()
        self._ws_clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        await self.hive.stop_background_loops()

    async def _telemetry_broadcast_loop(self) -> None:
        interval = 1.0 / self.telemetry_hz
        while True:
            await asyncio.sleep(interval)
            if not self._ws_clients:
                continue
            try:
                snap = self.hive.world_snapshot()
                frame = _ws_encode_text(json.dumps({"op": "world_snapshot", "data": snap}, default=str))
            except Exception:
                log.exception("World snapshot serialization failed; skipping frame")
                continue
            dead: list[asyncio.StreamWriter] = []
            for writer in list(self._ws_clients):
                try:
                    writer.write(frame)
                    await asyncio.wait_for(writer.drain(), timeout=2.0)
                except (OSError, RuntimeError, TimeoutError):
                    dead.append(writer)
            for d in dead:
                self._ws_clients.discard(d)
                with contextlib.suppress(OSError, RuntimeError):
                    d.close()

    async def execute_command(self, cmd_data: dict[str, Any]) -> dict[str, Any]:
        """Execute a sovereign Arelis command against the SwarmHive."""
        op = str(cmd_data.get("op") or "").strip().lower()

        if op == "ping":
            return format_command_response(True, {"pong": True, "port": self.bound_port})

        if op == "snapshot":
            return format_command_response(True, {"snapshot": self.hive.world_snapshot()})

        if op == "spawn_units":
            caste = str(cmd_data.get("caste") or "harvester")
            count = int(cmd_data.get("count", 1))
            tier = cmd_data.get("tier")
            units = self.hive.spawn_units(caste, count, tier=tier)
            return format_command_response(
                True,
                {"spawned": [u.to_dict() for u in units], "total_units": len(self.hive.units)},
            )

        if op == "retire_unit":
            uid = str(cmd_data.get("unit_id") or "")
            ok = self.hive.retire_unit(uid)
            return format_command_response(ok, {"unit_id": uid, "retired": ok})

        if op == "scale_caste":
            caste = str(cmd_data.get("caste") or "harvester")
            target_count = int(cmd_data.get("target_count", 4))
            tier = cmd_data.get("tier")
            res = self.hive.scale_caste(caste, target_count, tier=tier)
            return format_command_response(True, res)

        if op == "upgrade_unit":
            uid = str(cmd_data.get("unit_id") or "")
            tier = str(cmd_data.get("tier") or "mk2")
            version = cmd_data.get("version")
            unit = self.hive.upgrade_unit(uid, tier, version=version)
            return format_command_response(True, {"unit": unit.to_dict()})

        if op == "upgrade_caste":
            caste = str(cmd_data.get("caste") or "harvester")
            tier = str(cmd_data.get("tier") or "mk2")
            version = cmd_data.get("version")
            upgraded = self.hive.upgrade_caste(caste, tier, version=version)
            return format_command_response(
                True,
                {"caste": caste, "tier": tier, "upgraded_count": len(upgraded), "units": upgraded},
            )

        if op == "dispatch_task":
            caste = str(cmd_data.get("caste") or "harvester")
            payload = dict(cmd_data.get("payload") or {})
            unit_id = cmd_data.get("unit_id")
            res = await self.hive.dispatch_task(caste, payload, unit_id=unit_id)
            return format_command_response(bool(res.get("ok")), {"result": res})

        if op == "deploy_harvest_swarm":
            question = str(cmd_data.get("question") or "Arelis Research Swarm Mission")
            targets = list(cmd_data.get("targets") or [])
            save_report = bool(cmd_data.get("save_report", True))
            animate = bool(cmd_data.get("animate", True))
            res = await self.hive.dispatch_harvest_swarm(
                question,
                targets,
                save_report=save_report,
                animate=animate,
            )
            return format_command_response(bool(res.get("ok")), {"mission": res})

        if op == "set_theme":
            theme_id = str(cmd_data.get("theme") or "sodium")
            theme = await self.hive.set_theme(theme_id)
            return format_command_response(True, {"theme": theme})

        if op == "emp_halt":
            reason = str(cmd_data.get("reason") or "Sovereign EMP Halt")
            res = await self.hive.trigger_emp(reason=reason)
            return format_command_response(True, {"emp": res})

        if op == "emp_restore":
            res = await self.hive.restore_from_emp()
            return format_command_response(True, {"emp": res})

        if op == "arelis_demo_wave":
            scenario_id = str(cmd_data.get("scenario") or "zion_siege")
            res = await self.hive.simulator.run_scenario(scenario_id)
            return format_command_response(bool(res.get("ok")), res)

        if op == "run_scenario":
            scenario_id = str(cmd_data.get("scenario") or "zion_siege")
            query = str(cmd_data.get("query") or "")
            res = await self.hive.simulator.run_scenario(scenario_id, query=query)
            return format_command_response(bool(res.get("ok")), res)

        if op == "run_live_mission":
            mode = str(cmd_data.get("mode") or "multi")
            query = str(cmd_data.get("query") or "")
            res = await self.hive.simulator.run_live_mission(mode, query)
            return format_command_response(bool(res.get("ok")), res)

        if op == "neutralize_target":
            res = await self.hive.neutralize_target(
                node_id=cmd_data.get("node_id"),
                ip=cmd_data.get("ip"),
                sha256_digest=cmd_data.get("sha256"),
                reason=str(cmd_data.get("reason") or "Sovereign Hunter-Killer Neutralization"),
            )
            return format_command_response(bool(res.get("ok")), res)

        if op == "register_caste":
            caste_id = str(cmd_data.get("caste_id") or "").strip().lower()
            code_prefix = str(cmd_data.get("code_prefix") or caste_id[:3]).strip().upper()
            title = str(cmd_data.get("title") or f"{caste_id.title()} Sentinel")
            single_purpose = str(cmd_data.get("single_purpose") or "Custom autonomous Sentinel FSM task")
            caps = list(cmd_data.get("allowed_capabilities") or [f"{caste_id}:execute"])
            initial_pool = int(cmd_data.get("initial_pool", 0))
            tier = cmd_data.get("tier")
            res = self.hive.register_dynamic_caste(
                caste_id=caste_id,
                code_prefix=code_prefix,
                title=title,
                single_purpose=single_purpose,
                allowed_capabilities=caps,
                version=str(cmd_data.get("version", "1.0.0")),
                orbit_radius=float(cmd_data.get("orbit_radius", 20.0)),
                orbit_y_band=float(cmd_data.get("orbit_y_band", 0.0)),
                speed_mult=float(cmd_data.get("speed_mult", 1.0)),
                eye_color=str(cmd_data.get("eye_color", "#00e5ff")),
                laser_kind=str(cmd_data.get("laser_kind", "harvest")),
                doctrine=str(cmd_data.get("doctrine", "HUNTER-SEEKER")),
                rules=cmd_data.get("rules"),
                initial_pool=initial_pool,
                tier=tier,
            )
            return format_command_response(True, res)

        if op == "unregister_caste":
            caste_id = str(cmd_data.get("caste_id") or "").strip().lower()
            res = self.hive.unregister_caste(caste_id)
            return format_command_response(bool(res.get("ok")), res)

        if op == "list_castes":
            descriptors = self.hive.registry.descriptors()
            by_caste: dict[str, int] = {}
            for u in self.hive.units.values():
                by_caste[u.caste] = by_caste.get(u.caste, 0) + 1
            return format_command_response(True, {"castes": descriptors, "counts": by_caste})

        if op == "authority_status":
            return format_command_response(
                True,
                {
                    "pending_approvals": self.hive.authority.list_pending_approvals(),
                    "active_leases": self.hive.authority.list_active_leases(),
                },
            )

        if op == "operator_sign_off":
            req_id = str(cmd_data.get("request_id") or "").strip()
            approve = bool(cmd_data.get("approve", False))
            try:
                decided = self.hive.authority.operator_sign_off(req_id, approve=approve)
                return format_command_response(True, {"request": decided.model_dump()})
            except KeyError as exc:
                return format_command_response(False, error=str(exc))

        if op == "prune_storage":
            res = await asyncio.to_thread(self.hive.prune_runtime_storage)
            return format_command_response(True, res)

        return format_command_response(False, error=f"Unknown command op: {op!r}")




    async def _run_arelis_showcase_wave(self, scenario_id: str = "zion_siege") -> dict[str, Any]:
        """Launch a multi-stage SimulationDirector scenario across the swarm."""
        return await self.hive.simulator.run_scenario(scenario_id)


    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not request_line or len(request_line) > _MAX_HEADER_LINE:
                writer.close()
                return
            parts = request_line.decode("utf-8", errors="replace").strip().split(" ")
            if len(parts) < 2:
                writer.close()
                return
            method, raw_target = parts[0].upper(), parts[1]
            parsed_url = urlparse(raw_target)
            path = parsed_url.path

            headers: dict[str, str] = {}
            for _ in range(_MAX_HEADER_COUNT):
                hline = await asyncio.wait_for(reader.readline(), timeout=10.0)
                if not hline or hline in {b"\r\n", b"\n"}:
                    break
                if len(hline) > _MAX_HEADER_LINE:
                    self._write_json(400, {"ok": False, "error": "Header line too large"}, writer)
                    return
                decoded = hline.decode("utf-8", errors="replace").strip()
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            # Reject non-loopback Host and Origin headers
            ok_origin, origin_reason = _is_loopback_origin_and_host(headers)
            if not ok_origin:
                self.hive.telemetry.record(
                    "CRITICAL",
                    unit_id="SNT-WRD-001",
                    caste="warden",
                    phase="CSWSH / DNS REBIND BLOCKED",
                    message=origin_reason,
                    details={"path": path, "host": headers.get("host"), "origin": headers.get("origin")},
                )
                self._write_json(403, {"ok": False, "error": origin_reason}, writer)
                return

            # WebSocket upgrade: token arrives as the first hello, not a header.
            if headers.get("upgrade", "").lower() == "websocket" and path == "/ws/telemetry":
                await self._handle_websocket(reader, writer, headers)
                return

            if not _is_public_static(method, path) and not self._session_ok(
                token_from_headers(headers)
            ):
                self._reject_unauthorized(writer)
                return

            content_len = int(headers.get("content-length", "0") or "0")
            if content_len < 0 or content_len > _MAX_HTTP_BODY_BYTES:
                self.hive.telemetry.record(
                    "THREAT",
                    unit_id="SNT-WRD-001",
                    caste="warden",
                    phase="HTTP PAYLOAD FLOOD BLOCKED",
                    message=f"Rejected oversized HTTP body ({content_len} bytes > {_MAX_HTTP_BODY_BYTES} limit) on {path}",
                    details={"content_length": content_len, "path": path},
                )
                self._write_json(413, {"ok": False, "error": "Payload Too Large"}, writer)
                return

            body_bytes = await reader.readexactly(content_len) if content_len > 0 else b""

            await self._route_http(method, path, parsed_url.query, headers, body_bytes, writer)
        except (TimeoutError, OSError, RuntimeError, ValueError):
            log.debug("Connection closed or malformed HTTP request")
        finally:
            if writer not in self._ws_clients:
                with contextlib.suppress(OSError, RuntimeError):
                    writer.close()

    async def _handle_websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        ws_key = headers.get("sec-websocket-key", "")
        if not ws_key:
            writer.close()
            return
        accept_raw = hashlib.sha1((ws_key + _WS_GUID).encode("ascii")).digest()
        accept_key = base64.b64encode(accept_raw).decode("ascii")
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
        )
        writer.write(handshake.encode("ascii"))
        await writer.drain()

        greeted = False
        try:
            while True:
                frame = await _ws_read_frame(reader)
                if frame is None:
                    break
                opcode, data = frame
                if opcode == 0x8:  # Close
                    break
                if opcode == 0x9:  # Ping -> Pong
                    pong = bytearray([0x8A, len(data)]) + data
                    writer.write(bytes(pong))
                    await writer.drain()
                    continue
                if opcode != 0x1:
                    continue
                try:
                    msg = json.loads(data.decode("utf-8", errors="replace"))
                except (ValueError, TypeError):
                    break
                if not isinstance(msg, dict):
                    break
                if not greeted:
                    token = msg.get("token")
                    candidate = token if isinstance(token, str) else None
                    if msg.get("op") != "hello" or not self._session_ok(candidate):
                        self._note_auth_fail()
                        writer.write(
                            _ws_encode_text(json.dumps({"op": "error", "reason": "auth"}))
                        )
                        await writer.drain()
                        break
                    greeted = True
                    self._ws_clients.add(writer)
                    writer.write(
                        _ws_encode_text(
                            json.dumps({"op": "hello_ack", "version": PROTOCOL_VERSION})
                        )
                    )
                    snap = self.hive.world_snapshot()
                    writer.write(
                        _ws_encode_text(json.dumps({"op": "world_snapshot", "data": snap}))
                    )
                    await writer.drain()
                    continue
                action = msg.get("op")
                if action == "emp_halt":
                    await self.hive.trigger_emp(
                        reason=str(msg.get("reason") or "Overseer HUD EMP Trigger")
                    )
                elif action == "emp_restore":
                    await self.hive.restore_from_emp()
                elif action == "set_theme":
                    await self.hive.set_theme(str(msg.get("theme") or "sodium"))
                elif action in {"arelis_demo_wave", "run_scenario"}:
                    scenario_id = str(msg.get("scenario") or "zion_siege")
                    await self.hive.simulator.run_scenario(scenario_id)
        finally:
            self._ws_clients.discard(writer)
            with contextlib.suppress(OSError, RuntimeError):
                writer.close()

    async def _route_http(
        self,
        method: str,
        path: str,
        query: str,
        headers: dict[str, str],
        body_bytes: bytes,
        writer: asyncio.StreamWriter,
    ) -> None:
        if method == "GET" and path in {"/", "/overseer", "/overseer/"}:
            self._serve_static_file("index.html", writer)
            return

        if method == "GET" and path.startswith("/overseer/"):
            rel = path[len("/overseer/") :]
            self._serve_static_file(rel, writer)
            return

        if method == "GET" and path == "/api/snapshot":
            self._write_json(200, self.hive.world_snapshot(), writer)
            return

        if method == "POST" and path == "/api/overseer/emp":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            if payload.get("restore"):
                res = await self.hive.restore_from_emp()
            else:
                res = await self.hive.trigger_emp(
                    reason=str(payload.get("reason") or "Overseer HUD Emergency EMP")
                )
            self._write_json(200, res, writer)
            return

        if method == "POST" and path == "/api/overseer/theme":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            theme = await self.hive.set_theme(str(payload.get("theme") or "sodium"))
            self._write_json(200, {"ok": True, "theme": theme}, writer)
            return

        if method == "POST" and path in {"/api/overseer/demo", "/api/overseer/scenario"}:
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            scenario_id = str(payload.get("scenario") or "zion_siege")
            q_str = str(payload.get("query") or "")
            res = await self.hive.simulator.run_scenario(scenario_id, query=q_str)
            self._write_json(200, res, writer)
            return

        if method == "POST" and path == "/api/overseer/mission":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            mode = str(payload.get("mode") or "multi")
            q_str = str(payload.get("query") or "")
            res = await self.hive.simulator.run_live_mission(mode, q_str)
            self._write_json(200, res, writer)
            return

        if method == "POST" and path == "/api/overseer/scale":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            caste = str(payload.get("caste") or "harvester")
            try:
                if "delta" in payload:
                    res = self.hive.scale_caste_delta(caste, int(payload.get("delta", 1)))
                else:
                    res = self.hive.scale_caste(caste, int(payload.get("count", 4)))
                self._write_json(200, res, writer)
            except (KeyError, ValueError, RuntimeError) as exc:
                self._write_json(400, {"ok": False, "error": str(exc)}, writer)
            return

        if method == "POST" and path == "/api/overseer/upgrade":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            tier = str(payload.get("tier") or "mk1")
            caste_opt = payload.get("caste")
            try:
                res = self.hive.upgrade_swarm(tier, caste=str(caste_opt) if caste_opt else None)
                self._write_json(200, res, writer)
            except (KeyError, ValueError) as exc:
                self._write_json(400, {"ok": False, "error": str(exc)}, writer)
            return

        if method == "POST" and path == "/api/overseer/heal":
            res = await asyncio.to_thread(self.hive.heal_tripwire_roots)
            pending = getattr(self.hive, "_pending_merkle_verdict", None)
            trp_h = self.hive.registry.get("tripwire")
            if pending and hasattr(trp_h, "apply_merkle_verdict"):
                trp_h.apply_merkle_verdict(self.hive.nodes, pending)  # type: ignore[attr-defined]
            self._write_json(200, res, writer)
            return

        if method == "GET" and path == "/api/overseer/file":
            qs = parse_qs(query)
            kind = (qs.get("kind") or ["harvest"])[0].strip().lower()
            name = (qs.get("name") or qs.get("id") or [""])[0].strip()
            if kind == "receipt":
                found = next((r.to_dict() for r in self.hive.ledger.items if r.receipt_id == name), None)
                if not found:
                    self._write_json(404, {"ok": False, "error": f"Receipt not found: {name}"}, writer)
                    return
                self._write_json(
                    200,
                    {
                        "ok": True,
                        "kind": "receipt",
                        "title": f"WARRANT RECEIPT // {found['receipt_id']}",
                        "subtitle": f"Unit: {found['unit_id']} ({found['caste'].upper()}) • SHA-256: {found['sha256']}",
                        "content": json.dumps(found, indent=2, ensure_ascii=False),
                        "receipt": found,
                    },
                    writer,
                )
                return

            base_dir = harvest_dir() if kind == "harvest" else quarantine_dir()
            safe_name = Path(name).name
            target = (base_dir / safe_name).resolve()
            if not safe_name or not str(target).startswith(str(base_dir.resolve())) or not target.is_file():
                self._write_json(404, {"ok": False, "error": f"File not found: {safe_name}"}, writer)
                return
            raw_text = target.read_text(encoding="utf-8", errors="replace")
            self._write_json(
                200,
                {
                    "ok": True,
                    "kind": kind,
                    "name": safe_name,
                    "path": str(target),
                    "title": f"{'HARVEST DOSSIER' if kind == 'harvest' else 'QUARANTINE FORENSICS'} // {safe_name}",
                    "subtitle": f"Disk Path: {target}",
                    "content": raw_text,
                },
                writer,
            )
            return

        if method == "POST" and path == "/api/overseer/open_folder":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            folder_kind = str(payload.get("folder") or "harvest").strip().lower()
            folder_map = {
                "harvest": harvest_dir(),
                "quarantine": quarantine_dir(),
                "logs": logs_dir(),
            }
            target_dir = folder_map.get(folder_kind, harvest_dir())
            opened = False
            if hasattr(os, "startfile"):
                with contextlib.suppress(OSError):
                    os.startfile(str(target_dir))  # type: ignore[attr-defined]
                    opened = True
            self._write_json(200, {"ok": True, "opened": opened, "path": str(target_dir)}, writer)
            return

        if method == "POST" and path == "/api/overseer/neutralize":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            res = await self.hive.neutralize_target(
                node_id=payload.get("node_id"),
                ip=payload.get("ip"),
                sha256_digest=payload.get("sha256"),
                reason=str(payload.get("reason") or "Overseer Hunter-Killer Neutralization"),
            )
            self._write_json(200 if res.get("ok") else 400, res, writer)
            return

        if method == "POST" and path == "/api/overseer/unban":
            payload = json.loads(body_bytes.decode("utf-8") or "{}") if body_bytes else {}
            ip_val = str(payload.get("ip") or "").strip()
            wrd_h = self.hive.registry.get("warden")
            unbanned = wrd_h.unban_peer(ip_val) if hasattr(wrd_h, "unban_peer") else False  # type: ignore[attr-defined]
            self.hive.host_telemetry = await asyncio.to_thread(self.hive._collect_host_telemetry)
            self._write_json(200, {"ok": True, "unbanned": unbanned, "ip": ip_val}, writer)
            return

        if method == "POST" and path == "/api/overseer/prune":
            res = await asyncio.to_thread(self.hive.prune_runtime_storage)
            self._write_json(200, res, writer)
            return

        if method == "POST" and path == "/api/command":
            wrd = self.hive.registry.get("warden")
            admit = wrd.admit_inbound("127.0.0.1", port=self.bound_port)  # type: ignore[attr-defined]
            if not admit.get("ok"):
                self._write_json(429, format_command_response(False, error="Rate limited"), writer)
                return

            try:
                cmd_data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except json.JSONDecodeError:
                self._write_json(400, format_command_response(False, error="Invalid JSON body"), writer)
                return

            result = await self.execute_command(cmd_data)
            status_code = 200 if result.get("ok") else 400
            self._write_json(status_code, result, writer)
            return

        self._write_json(404, {"ok": False, "error": f"Not found: {path}"}, writer)

    def _serve_static_file(self, rel_path: str, writer: asyncio.StreamWriter) -> None:
        clean_rel = (rel_path or "index.html").lstrip("/\\")
        target = (self._static_dir / clean_rel).resolve()
        if not str(target).startswith(str(self._static_dir.resolve())) or not target.is_file():
            self._write_json(404, {"ok": False, "error": "Static asset not found"}, writer)
            return
        content = target.read_bytes()
        ctype, _ = mimetypes.guess_type(str(target))
        ctype = ctype or "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        hdr = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: {ctype}\r\n"
            f"Content-Length: {len(content)}\r\n"
            f"Cache-Control: no-store\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(hdr + content)

    def _write_json(self, status: int, obj: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        phrases = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            413: "Payload Too Large",
            429: "Too Many Requests",
        }
        phrase = phrases.get(status, "OK")
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        hdr = (
            f"HTTP/1.1 {status} {phrase}\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(raw)}\r\n"
            f"Cache-Control: no-store\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        writer.write(hdr + raw)
