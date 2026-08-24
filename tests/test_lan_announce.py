"""UDP house beacon — find the PC after DHCP without a new QR."""

from __future__ import annotations

import socket
import time

from arelis.identity import instance_id
from arelis.lan_announce import (
    BEACON_PREFIX,
    LanAnnouncer,
    broadcast_targets,
    decode_beacon,
    directed_broadcast,
    encode_beacon,
)


def test_encode_round_trip() -> None:
    raw = encode_beacon("inst0123456789ab", 8765)
    assert raw.decode("ascii").startswith(BEACON_PREFIX + "|")
    assert decode_beacon(raw) == ("inst0123456789ab", 8765)


def test_decode_rejects_junk() -> None:
    assert decode_beacon(b"") is None
    assert decode_beacon(b"nope") is None
    assert decode_beacon(b"ARELIS1|inst|not-a-port") is None
    assert decode_beacon(b"ARELIS1||8765") is None


def test_directed_broadcast_is_slash_24() -> None:
    assert directed_broadcast("192.168.86.248") == "192.168.86.255"
    assert directed_broadcast("10.0.0.2") == "10.0.0.255"
    assert directed_broadcast("bad") == "255.255.255.255"


def test_broadcast_targets_include_limited_broadcast() -> None:
    targets = broadcast_targets(["192.168.86.248", "192.168.86.10"], beacon_port=18765)
    assert ("255.255.255.255", 18765) in targets
    assert ("192.168.86.255", 18765) in targets
    assert len(targets) == 2


def test_announcer_payload_reaches_a_listener() -> None:
    recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    recv.bind(("127.0.0.1", 0))
    recv.settimeout(2.0)
    port = int(recv.getsockname()[1])
    inst = instance_id()
    announcer = LanAnnouncer(
        instance=inst,
        http_port=8766,
        interval_s=0.15,
        destinations=(("127.0.0.1", port),),
    )
    announcer.start()
    try:
        data, _addr = recv.recvfrom(256)
    finally:
        announcer.stop()
        recv.close()
    assert decode_beacon(data) == (inst, 8766)
    # A couple of extra milliseconds so the thread can actually die.
    time.sleep(0.05)
