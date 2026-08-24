"""LAN beacon so the phone can find this PC after DHCP moves.

The QR bakes in a LAN IP. That address is a snapshot, not a name. The ingest
server already answers `/inbound/health` with this instance id; this module
adds a UDP broadcast of the same fact so the phone does not have to guess
which lease the PC just took, and does not have to scan a new QR.

The token never goes on the wire here. A matching instance only tells the
phone where to knock. Auth is still the ingest token on HTTP.
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Iterable

log = logging.getLogger(__name__)

BEACON_PORT = 18765
BEACON_PREFIX = "ARELIS1"
BEACON_INTERVAL_S = 2.0


def encode_beacon(instance: str, port: int) -> bytes:
    inst = (instance or "").strip()
    return f"{BEACON_PREFIX}|{inst}|{int(port)}".encode("ascii", "replace")


def decode_beacon(data: bytes) -> tuple[str, int] | None:
    try:
        text = data.decode("ascii", "replace").strip()
    except Exception:
        return None
    parts = text.split("|")
    if len(parts) < 3 or parts[0] != BEACON_PREFIX:
        return None
    inst = parts[1].strip()
    try:
        port = int(parts[2].strip())
    except ValueError:
        return None
    if not inst or not (1 <= port <= 65535):
        return None
    return inst, port


def directed_broadcast(ip: str) -> str:
    """`192.168.86.248` → `192.168.86.255`. Home LANs here are /24."""
    parts = (ip or "").split(".")
    if len(parts) != 4:
        return "255.255.255.255"
    return ".".join([*parts[:3], "255"])


def broadcast_targets(
    ips: Iterable[str],
    *,
    beacon_port: int = BEACON_PORT,
) -> tuple[tuple[str, int], ...]:
    seen: list[tuple[str, int]] = [("255.255.255.255", int(beacon_port))]
    for ip in ips:
        dest = (directed_broadcast(ip), int(beacon_port))
        if dest not in seen:
            seen.append(dest)
    return tuple(seen)


class LanAnnouncer:
    """Daemon thread: UDP broadcast of instance + HTTP ingest port."""

    def __init__(
        self,
        *,
        instance: str,
        http_port: int,
        beacon_port: int = BEACON_PORT,
        interval_s: float = BEACON_INTERVAL_S,
        destinations: Iterable[tuple[str, int]] | None = None,
        ips: Iterable[str] | None = None,
    ) -> None:
        self.instance = instance
        self.http_port = int(http_port)
        self.beacon_port = int(beacon_port)
        self.interval_s = float(interval_s)
        if destinations is not None:
            self._destinations = tuple(destinations)
        elif ips is not None:
            self._destinations = broadcast_targets(ips, beacon_port=self.beacon_port)
        else:
            self._destinations = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="arelis-lan-announce",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=2)

    def _targets(self) -> tuple[tuple[str, int], ...]:
        if self._destinations is not None:
            return self._destinations
        from arelis.sms_ingest import list_lan_ipv4

        return broadcast_targets(list_lan_ipv4(), beacon_port=self.beacon_port)

    def _run(self) -> None:
        payload = encode_beacon(self.instance, self.http_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.4)
            while not self._stop.is_set():
                for host, port in self._targets():
                    try:
                        sock.sendto(payload, (host, port))
                    except OSError:
                        continue
                if self._stop.wait(self.interval_s):
                    break
        finally:
            sock.close()
