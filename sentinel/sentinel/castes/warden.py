"""Caste 02: WardenSentinel. Socket and port observation, admission counters, and peer ban records.

ban_peer writes data/banned_peers.json and stores a netsh command string. That string is not executed.
is_inviolable_address refuses bans of loopback, link-local, and the four public DNS addresses.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import math
import os
import threading
import time
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

import psutil

from sentinel.castes.base import CasteDescriptor
from sentinel.core.authority import is_inviolable_address
from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger
from sentinel.paths import banned_peers_path
from sentinel.safety.network import ALLOWED_EGRESS_HOSTS, check_url_allowed

_DEFAULT_WATCHED_PORTS = (
    {"port": 8765, "name": "Arelis LAN Ingest", "bind": "lan"},
    {"port": 8766, "name": "Arelis Core IPC", "bind": "loopback"},
    {"port": 11434, "name": "Ollama Local Engine", "bind": "loopback"},
    {"port": 8790, "name": "Sentinel Command Bridge", "bind": "loopback"},
)


def _prune(bucket: deque[float], window_s: float, now: float) -> None:
    cutoff = now - window_s
    while bucket and bucket[0] < cutoff:
        bucket.popleft()


def classify_ip_scope(ip_str: str) -> str:
    """Classify an IP address into 'loopback', 'lan', or 'wan'."""
    clean = (ip_str or "").strip()
    if not clean or clean in {"*", "0.0.0.0", "::"}:
        return "wildcard"
    clean = clean.removeprefix("::ffff:")
    try:
        addr = ipaddress.ip_address(clean)
        if addr.is_loopback:
            return "loopback"
        if addr.is_private or addr.is_link_local:
            return "lan"
        return "wan"
    except ValueError:
        return "unknown"


def build_windows_firewall_block_cmd(ip_str: str) -> str:
    """Return an auditable Windows Defender Firewall command to block a hostile remote IP.
    
    Strictly validates the IP via ipaddress to prevent command injection into netsh.
    """
    clean = (ip_str or "").strip()
    clean_ip = clean.removeprefix("::ffff:")
    # Validate strictly as IP or CIDR network
    if "/" in clean_ip:
        ipaddress.ip_network(clean_ip, strict=False)
    else:
        ipaddress.ip_address(clean_ip)
    return (
        f'netsh advfirewall firewall add rule name="ArelisSentinel_Block_{clean_ip}" '
        f"dir=in action=block remoteip={clean_ip}"
    )



class WardenCaste:
    """Narrow Caste 02: Watches sockets and bastion ports, counts inbound and auth failures, and checks URLs with check_url_allowed."""

    descriptor = CasteDescriptor(
        caste_id="warden",
        code_prefix="WRD",
        title="Perimeter & Firewall Warden",
        single_purpose="Patrol active network sockets and bastion ports; intercept flood, auth, and egress violations.",
        allowed_capabilities=frozenset(
            {"scan_sockets", "admit_inbound", "note_auth_fail", "verify_egress", "intercept_threat", "ban_peer"}
        ),
        version="1.2.0",
        orbit_radius=28.0,
        eye_color="#ff2a3a",
        laser_kind="defense",
    )

    def __init__(self, config: dict[str, Any] | None = None, *, banlist_file: Path | None = None) -> None:
        cfg = (config or {}).get("warden") or {}
        self.watched_ports: list[dict[str, Any]] = list(
            cfg.get("watched_ports") or _DEFAULT_WATCHED_PORTS
        )
        self.inbound_burst = int(cfg.get("inbound_burst", 40))
        self.inbound_window_s = float(cfg.get("inbound_window_s", 10.0))
        self.auth_fail_limit = int(cfg.get("auth_fail_limit", 8))
        self.auth_fail_window_s = float(cfg.get("auth_fail_window_s", 60.0))
        self.auth_lock_s = float(cfg.get("auth_lock_s", 300.0))
        self.egress_burst = int(cfg.get("egress_burst", 64))
        self.egress_window_s = float(cfg.get("egress_window_s", 10.0))
        self.conn_flood_per_ip = int(cfg.get("conn_flood_per_ip", 24))

        self._lock = threading.RLock()
        self._inbound: dict[str, deque[float]] = defaultdict(deque)
        self._auth_fail: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._egress_events: deque[float] = deque()
        self._alerts: deque[dict[str, Any]] = deque(maxlen=50)
        self._baseline_listening_ports: set[int] | None = None
        self._threat_seq = 0
        self._banlist_path = banlist_file or banned_peers_path()
        self._banned_peers: dict[str, dict[str, Any]] = {}
        self._authorize_work: Any = None
        self._load_banlist()

    def _load_banlist(self) -> None:
        if not self._banlist_path.is_file():
            return
        with contextlib.suppress(OSError, ValueError, TypeError):
            raw = json.loads(self._banlist_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                with self._lock:
                    for k, v in raw.items():
                        if isinstance(k, str) and isinstance(v, dict):
                            self._banned_peers[k] = v

    def _save_banlist_locked(self) -> None:
        with contextlib.suppress(OSError):
            self._banlist_path.parent.mkdir(parents=True, exist_ok=True)
            self._banlist_path.write_text(
                json.dumps(self._banned_peers, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    @property
    def banned_count(self) -> int:
        with self._lock:
            return len(self._banned_peers)

    def list_banned_peers(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._banned_peers.values())[-20:]

    def ban_peer(
        self,
        ip: str,
        *,
        reason: str = "Hunter-Killer Neutralization",
        port: int = 8765,
        unit_id: str = "SNT-WRD-001",
    ) -> dict[str, Any]:
        """Record a peer in data/banned_peers.json, including a netsh string that is not executed."""
        self.descriptor.assert_capability("ban_peer")
        host = (ip or "").strip()
        if not host:
            raise ValueError("Cannot ban empty IP/peer identifier")
        if is_inviolable_address(host):
            raise PermissionError(
                f"Warden ban rejected: {host!r} is protected by the Inviolable Safety Policy "
                "(loopback, DNS, or gateway infrastructure)."
            )
        if self._authorize_work is not None:
            parked = self._authorize_work("PERMANENT_BAN_PEER", host, reason)
            if parked is not None:
                return parked
        fw_cmd = build_windows_firewall_block_cmd(host)

        with self._lock:
            existing = self._banned_peers.get(host)
            entry = {
                "ip": host,
                "scope": classify_ip_scope(host),
                "reason": reason[:200],
                "port": int(port),
                "unit_id": unit_id,
                "banned_at": existing["banned_at"] if existing else int(time.time()),
                "hits_blocked": int(existing.get("hits_blocked", 0)) + 1 if existing else 1,
                "firewall_cmd": fw_cmd,
            }
            self._banned_peers[host] = entry
            self._save_banlist_locked()
            self._alerts.append(
                {
                    "kind": "permanent_ban",
                    "ip": host,
                    "port": port,
                    "reason": reason,
                    "firewall_cmd": fw_cmd,
                    "at": time.time(),
                }
            )
        return entry

    def unban_peer(self, ip: str) -> bool:
        host = (ip or "").strip()
        with self._lock:
            removed = self._banned_peers.pop(host, None) is not None
            self._locked_until.pop(host, None)
            if removed:
                self._save_banlist_locked()
            return removed

    def is_banned(self, ip: str) -> tuple[bool, dict[str, Any] | None]:
        """Check if an IP address is banned, either directly or via a CIDR subnet block."""
        host = (ip or "").strip()
        if not host:
            return False, None
        with self._lock:
            if host in self._banned_peers:
                return True, self._banned_peers[host]
            try:
                target_addr = ipaddress.ip_address(host.removeprefix("::ffff:"))
                for banned_key, entry in self._banned_peers.items():
                    if "/" in banned_key:
                        with contextlib.suppress(ValueError):
                            net = ipaddress.ip_network(banned_key, strict=False)
                            if target_addr in net:
                                return True, entry
            except ValueError:
                pass
        return False, None

    def create_bastion_nodes(self) -> dict[str, WorldNode]:

        """Create 3D Bastion Gate nodes positioned along the Perimeter Wall (R=28) at diagonal angles."""
        bastions: dict[str, WorldNode] = {}
        total = max(1, len(self.watched_ports))
        for idx, item in enumerate(self.watched_ports):
            angle = (idx / total) * (math.pi * 2.0) + (math.pi / 4.0)
            r = 28.0
            port = int(item["port"])
            node_id = f"bastion-port-{port}"
            bastions[node_id] = WorldNode(
                node_id=node_id,
                kind="bastion",
                label=f":{port} {item['name']}",
                position=[math.cos(angle) * r, 0.0, math.sin(angle) * r],
                status="active",
                progress=1.0,
                severity="none",
                metadata={"port": port, "name": item["name"], "bind": item.get("bind", "loopback")},
            )
        return bastions

    def scan_listening_sockets(self) -> list[dict[str, Any]]:
        """Return a list of real active TCP listening sockets on the host OS via psutil."""
        self.descriptor.assert_capability("scan_sockets")
        results: list[dict[str, Any]] = []
        try:
            for c in psutil.net_connections(kind="tcp"):
                if not c.laddr or c.status != psutil.CONN_LISTEN:
                    continue
                pname = "system"
                if c.pid:
                    try:
                        pname = psutil.Process(c.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                        pname = f"pid:{c.pid}"
                results.append(
                    {
                        "ip": c.laddr.ip,
                        "port": c.laddr.port,
                        "pid": c.pid,
                        "process": pname,
                    }
                )
        except (psutil.AccessDenied, OSError):
            pass
        results.sort(key=lambda x: int(x.get("port") or 0))
        return results

    def scan_sockets(self) -> dict[str, Any]:
        """Inspect live OS TCP sockets, remote WAN/LAN peers, and new port bindings via psutil."""
        self.descriptor.assert_capability("scan_sockets")
        own_pid = os.getpid()
        watched_set = {int(p["port"]) for p in self.watched_ports}
        port_states: dict[int, dict[str, Any]] = {
            int(p["port"]): {
                "port": int(p["port"]),
                "name": p["name"],
                "expected_bind": p.get("bind", "loopback"),
                "listening": False,
                "pid": None,
                "process": "none",
                "bind_addresses": [],
                "established_peers": 0,
                "peer_endpoints": [],
                "exposure_warning": False,
            }
            for p in self.watched_ports
        }

        total_established = 0
        total_listening = 0
        current_listening_ports: set[int] = set()
        own_listening_ports: set[int] = set()
        listening_port_owner: dict[int, str] = {}
        inbound_ip_counter: Counter[str] = Counter()
        wan_peers_count = 0
        lan_peers_count = 0
        loopback_peers_count = 0
        remote_peers_sample: list[str] = []
        seen_peer_keys: set[tuple[str, str]] = set()
        inbound_non_loopback_hits: list[dict[str, Any]] = []
        pid_name_cache: dict[int, str] = {}

        def _proc_name(pid: int | None) -> str:
            if not pid:
                return "system"
            if pid in pid_name_cache:
                return pid_name_cache[pid]
            try:
                name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                name = f"pid:{pid}"
            pid_name_cache[pid] = name
            return name

        try:
            conns = psutil.net_connections(kind="tcp")
            # Pass 1: record all listening ports
            for c in conns:
                if not c.laddr:
                    continue
                lport = c.laddr.port
                lip = c.laddr.ip
                if c.status == psutil.CONN_LISTEN:
                    total_listening += 1
                    current_listening_ports.add(lport)
                    if c.pid == own_pid or lport in watched_set:
                        own_listening_ports.add(lport)
                    pname = _proc_name(c.pid)
                    listening_port_owner[lport] = f":{lport} ({pname} on {lip})"
                    if lport in watched_set:
                        entry = port_states[lport]
                        entry["listening"] = True
                        if c.pid and not entry["pid"]:
                            entry["pid"] = c.pid
                            entry["process"] = pname
                        if lip not in entry["bind_addresses"]:
                            entry["bind_addresses"].append(lip)
                        if entry["expected_bind"] == "loopback" and lip in {"0.0.0.0", "::"}:
                            entry["exposure_warning"] = True

            # Pass 2: inspect all active/established connections and remote peers
            for c in conns:
                if not c.laddr or c.status == psutil.CONN_LISTEN:
                    continue
                lport = c.laddr.port
                if c.status == psutil.CONN_ESTABLISHED:
                    total_established += 1

                if c.raddr:
                    rip = c.raddr.ip
                    rport = c.raddr.port
                    scope = classify_ip_scope(rip)
                    pname = _proc_name(c.pid)
                    if scope == "wan":
                        wan_peers_count += 1
                    elif scope == "lan":
                        lan_peers_count += 1
                    else:
                        loopback_peers_count += 1

                    if scope in {"wan", "lan"} and len(remote_peers_sample) < 6:
                        dedup_key = (rip, pname)
                        if dedup_key not in seen_peer_keys:
                            seen_peer_keys.add(dedup_key)
                            remote_peers_sample.append(f"{rip}:{rport} ({pname} {scope.upper()})")

                    # Detect external/LAN connection hitting a local listening server port (inbound)
                    if lport in current_listening_ports and scope in {"wan", "lan"}:
                        inbound_ip_counter[rip] += 1
                        inbound_non_loopback_hits.append(
                            {
                                "remote_ip": rip,
                                "remote_port": rport,
                                "local_port": lport,
                                "process": pname,
                                "scope": scope,
                                "firewall_cmd": build_windows_firewall_block_cmd(rip),
                            }
                        )

                if lport in watched_set and c.status == psutil.CONN_ESTABLISHED:
                    entry = port_states[lport]
                    entry["established_peers"] += 1
                    if c.raddr and len(entry["peer_endpoints"]) < 5:
                        peer_str = f"{c.raddr.ip}:{c.raddr.port}"
                        if peer_str not in entry["peer_endpoints"]:
                            entry["peer_endpoints"].append(peer_str)
        except (psutil.AccessDenied, OSError):
            pass

        if self._baseline_listening_ports is None:
            self._baseline_listening_ports = set(current_listening_ports) | watched_set | own_listening_ports
        else:
            # Always trust watched Sovereign Bastion ports and Sentinel's own process sockets
            self._baseline_listening_ports.update(watched_set | own_listening_ports)

        new_ports_opened = sorted(current_listening_ports - self._baseline_listening_ports)
        new_port_descriptors = [
            listening_port_owner.get(p, f":{p}") for p in new_ports_opened
        ]

        flood_peers = [
            {
                "remote_ip": ip,
                "connections": count,
                "firewall_cmd": build_windows_firewall_block_cmd(ip),
            }
            for ip, count in inbound_ip_counter.items()
            if count >= self.conn_flood_per_ip
        ]

        with self._lock:
            now = time.monotonic()
            locked_ips = [ip for ip, until in self._locked_until.items() if until > now]
            banned_list = list(self._banned_peers.values())[-16:]
            banned_total = len(self._banned_peers)
            recent_alerts = list(self._alerts)[-12:]

        return {
            "bastions": list(port_states.values()),
            "total_listening_tcp": total_listening,
            "total_established_tcp": total_established,
            "wan_peers_count": wan_peers_count,
            "lan_peers_count": lan_peers_count,
            "loopback_peers_count": loopback_peers_count,
            "remote_peers_sample": remote_peers_sample,
            "new_listening_ports": new_port_descriptors,
            "inbound_non_loopback_hits": inbound_non_loopback_hits,
            "flood_peers": flood_peers,
            "locked_clients": locked_ips,
            "locked_count": len(locked_ips),
            "banned_peers_count": banned_total,
            "banned_peers": banned_list,
            "pinned_egress_hosts_count": len(ALLOWED_EGRESS_HOSTS),
            "alerts": recent_alerts,
        }

    def apply_bastion_snapshot(self, nodes: dict[str, WorldNode], snap: dict[str, Any]) -> dict[str, Any]:
        """Update the 3D Bastion Gate nodes in-place from a pre-computed scan_sockets() snapshot."""
        for b in snap.get("bastions") or []:
            port = b["port"]
            node_id = f"bastion-port-{port}"
            node = nodes.get(node_id)
            if not node:
                continue
            # Do not overwrite temporary attack state if a drill is actively targeting this bastion
            if node.status in {"UNDER ATTACK", "intercepting"}:
                continue
            if b["listening"]:
                proc_tag = f"{b['process']} (PID {b['pid']})" if b["pid"] else "LISTENING"
                peers = b["established_peers"]
                bind_str = ",".join(b["bind_addresses"]) or "127.0.0.1"
                node.label = f":{port} {b['name']} [{b['process']} • {peers} conn]"
                node.status = "LIVE LISTENING" if not b["exposure_warning"] else "EXPOSED 0.0.0.0"
                node.severity = "high" if b["exposure_warning"] else "none"
                node.metadata = {
                    "port": port,
                    "service": b["name"],
                    "listening": True,
                    "real_os_state": "LISTENING",
                    "pid": b["pid"],
                    "process": proc_tag,
                    "bind_ip": bind_str,
                    "connections": peers,
                    "active_tcp_peers": peers,
                    "peer_endpoints": b["peer_endpoints"],
                    "exposure_warning": b["exposure_warning"],
                }
            else:
                node.label = f":{port} {b['name']} [CLOSED / STANDBY]"
                node.status = "PORT CLOSED"
                node.severity = "none"
                node.metadata = {
                    "port": port,
                    "service": b["name"],
                    "listening": False,
                    "real_os_state": "CLOSED (No Process Listening)",
                    "expected_bind": b["expected_bind"],
                }
        return snap

    def sync_bastion_nodes(self, nodes: dict[str, WorldNode]) -> dict[str, Any]:
        """Update the 3D Bastion Gate nodes in-place with REAL live OS socket & PID telemetry."""
        snap = self.scan_sockets()
        return self.apply_bastion_snapshot(nodes, snap)


    def admit_inbound(self, ip: str, *, port: int = 8790) -> dict[str, Any]:
        """Sliding-window inbound rate limiter, permanent blacklist check, and lockout gate."""
        self.descriptor.assert_capability("admit_inbound")
        host = (ip or "?").strip()
        now = time.monotonic()
        with self._lock:
            until = self._locked_until.get(host, 0.0)
            banned, ban_entry = self.is_banned(host)
            if until > now:
                return {
                    "ok": False,
                    "reason": "locked",
                    "permanently_banned": banned,
                    "retry_after": max(1, int(until - now)),
                    "ip": host,
                    "port": port,
                }
            if banned and ban_entry is not None:
                ban_entry["hits_blocked"] = int(ban_entry.get("hits_blocked", 0)) + 1
                self._save_banlist_locked()
                return {
                    "ok": False,
                    "reason": "permanent_blacklist",
                    "ip": host,
                    "port": port,
                    "firewall_cmd": ban_entry.get("firewall_cmd") or build_windows_firewall_block_cmd(host),
                }
            bucket = self._inbound[host]

            _prune(bucket, self.inbound_window_s, now)
            if len(bucket) >= self.inbound_burst:
                alert = {
                    "kind": "inbound_flood",
                    "ip": host,
                    "port": port,
                    "count": len(bucket),
                    "window_s": self.inbound_window_s,
                    "at": time.time(),
                }
                self._alerts.append(alert)
                return {
                    "ok": False,
                    "reason": "rate_limit",
                    "retry_after": int(self.inbound_window_s),
                    "ip": host,
                    "port": port,
                    "alert": alert,
                }
            bucket.append(now)
            return {"ok": True, "ip": host, "port": port}

    def note_auth_fail(self, ip: str, *, port: int = 8790) -> dict[str, Any]:
        """Record a bad token attempt. At the threshold, set a lockout timer and, for non-loopback peers, store a ban record.

        The stored netsh string is not executed.
        """
        self.descriptor.assert_capability("note_auth_fail")
        host = (ip or "?").strip()
        now = time.monotonic()
        with self._lock:
            bucket = self._auth_fail[host]
            _prune(bucket, self.auth_fail_window_s, now)
            bucket.append(now)
            if len(bucket) >= self.auth_fail_limit:
                self._locked_until[host] = now + self.auth_lock_s
                if classify_ip_scope(host) != "loopback":
                    fw_cmd = build_windows_firewall_block_cmd(host)
                    self._banned_peers[host] = {
                        "ip": host,
                        "scope": classify_ip_scope(host),
                        "reason": f"Brute-force auth lockout ({len(bucket)} failures on :{port})",
                        "port": port,
                        "unit_id": "SNT-WRD-001",
                        "banned_at": int(time.time()),
                        "hits_blocked": len(bucket),
                        "firewall_cmd": fw_cmd,
                    }
                    self._save_banlist_locked()
                alert = {
                    "kind": "auth_lockout",
                    "ip": host,
                    "port": port,
                    "failures": len(bucket),
                    "lock_s": self.auth_lock_s,
                    "at": time.time(),
                }
                self._alerts.append(alert)
                return {
                    "ok": False,
                    "locked": True,
                    "permanently_banned": host in self._banned_peers,
                    "retry_after": int(self.auth_lock_s),
                    "ip": host,
                    "port": port,
                    "alert": alert,
                }
            return {
                "ok": False,
                "locked": False,
                "failures": len(bucket),
                "limit": self.auth_fail_limit,
                "ip": host,
                "port": port,
            }

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        """Run a socket scan, a URL policy check, or a ban-record interception."""
        action = str(task_payload.get("action") or "patrol_scan").strip().lower()
        animate = bool(task_payload.get("animate", True))

        if action in {"verify_egress", "check_url"}:
            self.descriptor.assert_capability("verify_egress")

            url = str(task_payload.get("url") or "")
            verdict = await check_url_allowed(url, block_private=True)
            if not verdict.allowed:
                result = await self._intercept_intrusion(
                    unit,
                    label=f"BLOCKED EGRESS: {url[:38]}",
                    reason=verdict.reason or "Blocked URL",
                    port=8790,
                    animate=animate,
                    bus=bus,
                    ledger=ledger,
                    nodes=nodes,
                )
                return dict(result, allowed=False, outcome="url_policy_rejected")
            receipt = ledger.mint(
                unit_id=unit.unit_id,
                caste=self.descriptor.caste_id,
                kind="defense",
                source=url,
                span=f"Egress verified -> {verdict.host} ({verdict.ip})",
                ok=True,
            )
            return {
                "ok": True,
                "allowed": True,
                "host": verdict.host,
                "ip": verdict.ip,
                "receipt": receipt.to_dict(),
            }

        if action == "intercept":
            self.descriptor.assert_capability("intercept_threat")
            label = str(task_payload.get("label") or "INTRUSION PROBE")
            reason = str(task_payload.get("reason") or "Unauthorized connection attempt")
            port = int(task_payload.get("port") or 8765)
            source_ip = str(task_payload.get("source_ip") or "").strip()
            ban_rec: dict[str, Any] | None = None
            if source_ip and classify_ip_scope(source_ip) != "loopback":
                ban_rec = self.ban_peer(
                    source_ip,
                    reason=f"{label}: {reason}",
                    port=port,
                    unit_id=unit.unit_id,
                )
            res = await self._intercept_intrusion(
                unit,
                label=label,
                reason=reason,
                port=port,
                animate=animate,
                bus=bus,
                ledger=ledger,
                nodes=nodes,
            )
            if ban_rec is not None:
                res["ban_record"] = ban_rec
            return res

        # Default: active socket & bastion scan
        snap = await asyncio.to_thread(self.scan_sockets)
        unit.missions_completed += 1
        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="defense",
            source="local_perimeter_sockets",
            span=(
                f"Bastion scan complete: {len(snap['bastions'])} ports watched, "
                f"{snap['total_established_tcp']} active TCP sockets, "
                f"{snap['locked_count']} locked IPs, {snap['banned_peers_count']} permanently banned."
            ),
            ok=True,
            metadata=snap,
        )
        await bus.publish(EventTopic.RECEIPT_MINTED, receipt.to_dict())
        return {"ok": True, "snapshot": snap, "receipt": receipt.to_dict()}

    async def _intercept_intrusion(
        self,
        unit: SentinelUnit,
        *,
        label: str,
        reason: str,
        port: int,
        animate: bool,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        self._threat_seq += 1
        bastion_id = f"bastion-port-{port}"
        if bastion_id in nodes:
            bx, by, bz = nodes[bastion_id].position
            pos = [bx * 1.18, by + 2.5, bz * 1.18]
            nodes[bastion_id].severity = "high"
            nodes[bastion_id].status = "intercepting"
            await bus.publish(EventTopic.NODE_UPDATED, nodes[bastion_id].to_dict())
        else:
            angle = (self._threat_seq * 1.5) % (math.pi * 2.0)
            pos = [math.cos(angle) * 32.0, 2.0, math.sin(angle) * 32.0]

        t_node = WorldNode(
            node_id=f"threat-{self._threat_seq:04d}",
            kind="threat",
            label=label[:48],
            position=pos,
            status="policy_event",
            progress=0.5,
            severity="critical",
            metadata={"reason": reason, "port": port, "unit_id": unit.unit_id},
        )
        nodes[t_node.node_id] = t_node
        await bus.publish(EventTopic.NODE_SPAWNED, t_node.to_dict())

        unit.transition(
            SentinelState.ENGAGED_DEFENSE,
            task=f"Inspecting policy event: {label[:40]}",
            target_node_id=t_node.node_id,
            target_position=t_node.position,
            laser_active=True,
            laser_kind="defense",
        )
        await bus.publish(
            EventTopic.SECURITY_ALERT,
            {
                "unit_id": unit.unit_id,
                "caste": "warden",
                "label": label,
                "reason": reason,
                "port": port,
                "node": t_node.to_dict(),
            },
        )
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())

        if animate:
            await asyncio.sleep(0.32)

        unit.security_events += 1
        unit.missions_completed += 1
        nodes.pop(t_node.node_id, None)
        if bastion_id in nodes:
            nodes[bastion_id].severity = "none"
            nodes[bastion_id].status = "active"
            await bus.publish(EventTopic.NODE_UPDATED, nodes[bastion_id].to_dict())
        await bus.publish(EventTopic.NODE_REMOVED, {"node_id": t_node.node_id})

        unit.transition(
            SentinelState.PATROLLING,
            task="Patrolling perimeter wall",
            laser_active=False,
        )
        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="defense",
            source=f"port:{port}",
            span=f"Application policy event ({label}): {reason}",
            ok=True,
            metadata={"label": label, "reason": reason, "port": port},
        )
        await bus.publish(EventTopic.RECEIPT_MINTED, receipt.to_dict())
        await bus.publish(EventTopic.UNIT_STATE, unit.to_dict())
        return {
            "ok": True,
            "neutralized": False,
            "outcome": "policy_event",
            "unit_id": unit.unit_id,
            "label": label,
            "reason": reason,
            "receipt": receipt.to_dict(),
        }
