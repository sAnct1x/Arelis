"""LAN beacon bytes and broadcast addresses. No sockets, no LanAnnouncer."""

from __future__ import annotations

import pytest

from arelis.lan_announce import (
    BEACON_PORT,
    broadcast_targets,
    decode_beacon,
    directed_broadcast,
    encode_beacon,
)


def test_beacon_round_trip_strips_instance_whitespace() -> None:
    encoded = encode_beacon("  desk  ", 8080)
    assert encoded == b"ARELIS1|desk|8080"
    assert decode_beacon(encoded) == ("desk", 8080)
    assert decode_beacon(b"ARELIS1|  desk  |65535") == ("desk", 65535)
    assert decode_beacon(b"  ARELIS1|desk|9\n") == ("desk", 9)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"NOPE|desk|80",
        b"ARELIS1|desk",
        b"ARELIS1",
        b"ARELIS1|",
        b"ARELIS1||80",
        b"ARELIS1|   |80",
        b"ARELIS1|desk|nope",
        b"ARELIS1|desk|0",
        b"ARELIS1|desk|65536",
    ],
)
def test_decode_beacon_rejects_garbage(payload: bytes) -> None:
    assert decode_beacon(payload) is None


def test_directed_broadcast_rewrites_the_last_octet() -> None:
    assert directed_broadcast("192.168.1.20") == "192.168.1.255"
    assert directed_broadcast("") == "255.255.255.255"
    assert directed_broadcast("not-an-ip") == "255.255.255.255"
    assert directed_broadcast("192.168.1") == "255.255.255.255"
    assert directed_broadcast("192.168.1.20.5") == "255.255.255.255"


def test_broadcast_targets_lead_with_the_global_address_and_drop_duplicates() -> None:
    targets = broadcast_targets(
        [
            "192.168.1.20",
            "192.168.1.21",
            "10.0.0.8",
            "255.255.255.255",
        ]
    )
    assert targets[0] == ("255.255.255.255", BEACON_PORT)
    assert targets == (
        ("255.255.255.255", BEACON_PORT),
        ("192.168.1.255", BEACON_PORT),
        ("10.0.0.255", BEACON_PORT),
    )
    assert broadcast_targets([]) == (("255.255.255.255", BEACON_PORT),)
