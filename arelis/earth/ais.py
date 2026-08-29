"""AIS. AISStream (keyed) plus Fintraffic Digitraffic plus BarentsWatch (keyed).

Hosts named here are pinned in tests/test_egress.py. Keys never appear in
entity fields, dumps, or logs. Failures return None so the simulated
layer stays. AISStream is a short TLS websocket sample, not a standing
socket. Digitraffic is Finnish coastal / Baltic (CC BY 4.0). BarentsWatch
is Norwegian EEZ including Norwegian satellites in that zone.

VHF dies tens of kilometres from a coast receiver. We still paint a
packet a legal feed already sent — including a mixed sat packet if
AISStream mixed one. We do not buy a commercial sat-AIS product.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import os
import socket
import ssl
import struct
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from arelis import __source_url__, __version__
from arelis.earth.barentswatch import fetch_barentswatch
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import ecef_vel_from_track, lla_to_ecef
from arelis.paths import state_dir

# HTTPS forms so egress tests see the hosts. The wire is wss on the same URL.
AISSTREAM_SITE = "https://aisstream.io"
AISSTREAM_STREAM = "https://stream.aisstream.io/v0/stream"
AISSTREAM_HOST = "stream.aisstream.io"
AISSTREAM_KEY_ENV = "ARELIS_AISSTREAM_KEY"
DIGITRAFFIC_LOCATIONS = "https://meri.digitraffic.fi/api/ais/v1/locations"
DIGITRAFFIC_VESSELS = "https://meri.digitraffic.fi/api/ais/v1/vessels"
DIGITRAFFIC_HOST = "meri.digitraffic.fi"
SECRETS_PATH = state_dir() / "secrets.yaml"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_PINNED_HOSTS = frozenset(
    h
    for h in (
        urlparse(AISSTREAM_SITE).hostname,
        urlparse(AISSTREAM_STREAM).hostname,
        urlparse(DIGITRAFFIC_LOCATIONS).hostname,
    )
    if h
)

# Worldwide terrestrial subscribe box. Coastal receivers dominate.
# Mid-ocean packets are painted if the feed sent them.
WORLD_BOX: list[list[list[float]]] = [[[-90.0, -180.0], [90.0, 180.0]]]
_POSITION_TYPES = frozenset(
    {
        "PositionReport",
        "StandardClassBPositionReport",
        "ExtendedClassBPositionReport",
    }
)
_CAP = 800
_DIGITRAFFIC_CAP = 1500
_MERGED_CAP = 4000
_DRAIN_S = 6.0
_TIMEOUT_S = 8.0
_HTTP_TIMEOUT = 10.0
_WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_MAX_FRAME = 1_000_000

_CITE = (
    "AISStream AIS. Short TLS websocket sample. "
    "VHF dies tens of kilometres from a coast receiver. "
    "A packet the feed sent is painted, including mid-ocean if mixed. "
    "Not a paid satellite product. Not navigation."
)
_DIGITRAFFIC_CITE = (
    "Fintraffic Digitraffic AIS. Finnish coast and Baltic. CC BY 4.0. "
    "VHF dies tens of kilometres from a coast receiver. "
    "Not a paid satellite product. Not navigation."
)
_COVERAGE = (
    "Mostly terrestrial AIS. Mid-ocean VHF is deaf. "
    "We do not buy a commercial sat-AIS product."
)


def aisstream_key(path: Path | None = None) -> str:
    env = (os.environ.get(AISSTREAM_KEY_ENV) or "").strip()
    if env:
        return env
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(raw, dict):
        return ""
    block = raw.get("earth")
    if not isinstance(block, dict):
        return ""
    return str(block.get("aisstream_key") or "").strip()


def fetch_ais() -> list[Entity] | None:
    """None = every source failed (keep sim). Empty list = heard nothing."""
    stream = fetch_aisstream()
    finland = fetch_digitraffic()
    norway = fetch_barentswatch()
    if stream is None and finland is None and norway is None:
        return None
    return merge_vessels(stream or [], finland or [], norway or [])


def fetch_aisstream() -> list[Entity] | None:
    """None = failed or no key. Empty list = heard nothing in the sample."""
    key = aisstream_key()
    if not key:
        return None
    try:
        messages = _drain(key)
    except Exception:
        return None
    if messages is None:
        return None
    return entities_from_messages(messages)


def fetch_digitraffic() -> list[Entity] | None:
    """No key. Finnish coastal / Baltic snapshot. None = failed."""
    locations = _get_json(DIGITRAFFIC_LOCATIONS)
    if not isinstance(locations, dict):
        return None
    vessels = _get_json(DIGITRAFFIC_VESSELS)
    return entities_from_digitraffic(locations, vessels)


def merge_vessels(*groups: list[Entity]) -> list[Entity]:
    """Union by MMSI. Newer report wins. Cap the plate, not the ocean."""
    by_id: dict[str, Entity] = {}
    for group in groups:
        for entity in group:
            prev = by_id.get(entity.id)
            if prev is None:
                if len(by_id) >= _MERGED_CAP:
                    continue
                by_id[entity.id] = entity
            elif entity.when_unix >= prev.when_unix:
                by_id[entity.id] = entity
    return list(by_id.values())


def entities_from_messages(
    messages: list[dict[str, Any]], *, unix: float | None = None
) -> list[Entity]:
    """Parse AISStream envelopes. Last report per MMSI wins."""
    now = float(unix if unix is not None else time.time())
    by_mmsi: dict[str, Entity] = {}
    for payload in messages:
        entity = _entity_from_envelope(payload, now)
        if entity is None:
            continue
        by_mmsi[entity.id] = entity
        if len(by_mmsi) >= _CAP:
            break
    return list(by_mmsi.values())


def open_ocean_hole(lat: float, lon: float) -> bool:
    """True if this is a named terrestrial-AIS deaf zone.

    Geography for coverage notes. Not a drop filter — a packet a legal
    feed already sent is still painted. Commercial sat-AIS would fill
    these as a product; we do not buy that product.
    """
    lon = ((lon + 180.0) % 360.0) - 180.0
    if 18.5 <= lat <= 22.5 and -160.5 <= lon <= -154.5:
        return False
    # Island receivers inside the named gyre boxes. Keep them.
    if 18.5 <= lat <= 20.6 and 165.3 <= lon <= 168.0:
        return False
    if 27.7 <= lat <= 28.8 and -178.0 <= lon <= -176.8:
        return False
    if 16.3 <= lat <= 17.2 and -170.0 <= lon <= -169.1:
        return False
    if 15.0 <= lat <= 40.0 and 160.0 <= lon <= 180.0:
        return True
    if 15.0 <= lat <= 40.0 and -180.0 <= lon <= -130.0:
        return True
    if 10.0 <= lat <= 35.0 and -50.0 <= lon <= -25.0:
        return True
    return False


def _entity_from_envelope(payload: dict[str, Any], now: float) -> Entity | None:
    kind = str(payload.get("MessageType") or "")
    if kind not in _POSITION_TYPES:
        return None
    meta = payload.get("MetaData") if isinstance(payload.get("MetaData"), dict) else {}
    body = payload.get("Message") if isinstance(payload.get("Message"), dict) else {}
    report = body.get(kind) if isinstance(body.get(kind), dict) else {}
    lat = _num(meta.get("latitude"), report.get("Latitude"))
    lon = _num(meta.get("longitude"), report.get("Longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    mmsi = str(meta.get("MMSI") or report.get("UserID") or "").strip()
    if not mmsi or mmsi == "0":
        return None
    name = str(meta.get("ShipName") or "").strip() or mmsi
    sog = _num(report.get("Sog"))
    cog = _num(report.get("Cog"))
    when = _unix_from_meta(meta.get("time_utc"), now)
    pos = lla_to_ecef(lat, lon, 0.0)
    speed = (sog or 0.0) * 0.514444
    vx, vy, vz = (
        ecef_vel_from_track(lat, lon, speed, cog or 0.0)
        if speed > 0.5
        else (0.0, 0.0, 0.0)
    )
    return Entity(
        id=f"mmsi:{mmsi}",
        cls="vessel",
        layer="vessels",
        label=name,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=vx,
        vy=vy,
        vz=vz,
        when_unix=when,
        source="AISStream",
        freshness="live",
        confidence=0.75,
        cite=_CITE,
        meta={
            "mmsi": mmsi,
            "lat": lat,
            "lon": lon,
            "sog_kn": sog,
            "cog_deg": cog,
            "type": kind,
        },
        coverage=Coverage("coastal", _COVERAGE),
    )


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _unix_from_meta(stamp: Any, fallback: float) -> float:
    if not isinstance(stamp, str) or not stamp.strip():
        return fallback
    text = stamp.strip()
    try:
        cut = text.split(" +")[0].split(".")[0]
        dt = datetime.strptime(cut, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return dt.timestamp()
    except (ValueError, OverflowError, OSError):
        return fallback


def entities_from_digitraffic(
    locations: dict[str, Any],
    vessels: Any = None,
    *,
    unix: float | None = None,
) -> list[Entity]:
    """Parse Fintraffic GeoJSON locations. Last report per MMSI wins."""
    now = float(unix if unix is not None else time.time())
    names = _digitraffic_names(vessels)
    by_mmsi: dict[str, Entity] = {}
    features = locations.get("features") if isinstance(locations, dict) else None
    if not isinstance(features, list):
        return []
    for feat in features:
        entity = _entity_from_digitraffic(feat, names, now)
        if entity is None:
            continue
        by_mmsi[entity.id] = entity
        if len(by_mmsi) >= _DIGITRAFFIC_CAP:
            break
    return list(by_mmsi.values())


def _digitraffic_names(vessels: Any) -> dict[str, str]:
    if isinstance(vessels, list):
        rows = vessels
    elif isinstance(vessels, dict):
        inner = vessels.get("vessels") or vessels.get("features") or []
        rows = inner if isinstance(inner, list) else []
    else:
        rows = []
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        props = row.get("properties") if isinstance(row.get("properties"), dict) else row
        mmsi = str(props.get("mmsi") or row.get("mmsi") or "").strip()
        name = str(props.get("name") or row.get("name") or "").strip()
        if mmsi and name:
            out[mmsi] = name
    return out


def _entity_from_digitraffic(
    feat: Any, names: dict[str, str], now: float
) -> Entity | None:
    if not isinstance(feat, dict):
        return None
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
    lon = _num(coords[0] if len(coords) > 0 else None)
    lat = _num(coords[1] if len(coords) > 1 else None)
    if lat is None or lon is None:
        lat = _num(props.get("lat"), feat.get("lat"))
        lon = _num(props.get("lon"), feat.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    mmsi = str(props.get("mmsi") or feat.get("mmsi") or "").strip()
    if not mmsi or mmsi == "0":
        return None
    name = names.get(mmsi) or str(props.get("name") or "").strip() or mmsi
    sog = _num(props.get("sog"))
    cog = _num(props.get("cog"))
    when = _unix_from_digitraffic(props.get("timestampExternal"), now)
    pos = lla_to_ecef(lat, lon, 0.0)
    speed = (sog or 0.0) * 0.514444
    vx, vy, vz = (
        ecef_vel_from_track(lat, lon, speed, cog or 0.0)
        if speed > 0.5
        else (0.0, 0.0, 0.0)
    )
    return Entity(
        id=f"mmsi:{mmsi}",
        cls="vessel",
        layer="vessels",
        label=name,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=vx,
        vy=vy,
        vz=vz,
        when_unix=when,
        source="Fintraffic Digitraffic",
        freshness="live",
        confidence=0.8,
        cite=_DIGITRAFFIC_CITE,
        meta={
            "mmsi": mmsi,
            "lat": lat,
            "lon": lon,
            "sog_kn": sog,
            "cog_deg": cog,
            "type": "digitraffic",
        },
        coverage=Coverage("coastal", _COVERAGE),
    )


def _unix_from_digitraffic(stamp: Any, fallback: float) -> float:
    value = _num(stamp)
    if value is None:
        return fallback
    if value > 1.0e12:
        return value / 1000.0
    if value > 1.0e9:
        return value
    return fallback


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


def _get_json(url: str) -> Any:
    if not _host_pinned(urlparse(url).hostname, DIGITRAFFIC_HOST):
        return None
    if DIGITRAFFIC_HOST not in _PINNED_HOSTS:
        return None
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={
                    "User-Agent": _UA,
                    "Digitraffic-User": _UA,
                    "Accept-Encoding": "gzip",
                },
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, DIGITRAFFIC_HOST):
                return None
            return resp.json()
    except Exception:
        return None


def _drain(key: str) -> list[dict[str, Any]] | None:
    parsed = urlparse(AISSTREAM_STREAM)
    host = (parsed.hostname or "").lower()
    if host != AISSTREAM_HOST or host not in _PINNED_HOSTS:
        return None
    path = parsed.path or "/v0/stream"
    addrs = _public_addrs(host, 443)
    if not addrs:
        return None
    ctx = ssl.create_default_context()
    raw: socket.socket | None = None
    sock: ssl.SSLSocket | None = None
    try:
        raw = socket.create_connection((addrs[0], 443), timeout=_TIMEOUT_S)
        sock = ctx.wrap_socket(raw, server_hostname=AISSTREAM_HOST)
        raw = None
        nonce = base64.b64encode(os.urandom(16)).decode("ascii")
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {AISSTREAM_HOST}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: ArelisEarth/0.2\r\n"
            "\r\n"
        )
        sock.sendall(req.encode("ascii"))
        header, leftover = _read_http_headers(sock)
        if not _handshake_ok(header, nonce):
            return None
        subscribe = {
            "APIKey": key,
            "BoundingBoxes": WORLD_BOX,
            "FilterMessageTypes": sorted(_POSITION_TYPES),
        }
        _ws_send(sock, json.dumps(subscribe, separators=(",", ":")))
        buf = _SockBuf(sock, leftover)
        out: list[dict[str, Any]] = []
        deadline = time.monotonic() + _DRAIN_S
        while time.monotonic() < deadline and len(out) < _CAP:
            remain = deadline - time.monotonic()
            sock.settimeout(max(0.05, min(remain, _TIMEOUT_S)))
            try:
                opcode, payload = _ws_recv(buf)
            except TimeoutError:
                break
            except OSError:
                break
            if opcode == 0x8:
                break
            if opcode == 0x9:
                _ws_send(sock, payload, opcode=0xA)
                continue
            if opcode not in (0x1, 0x2):
                continue
            try:
                data = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                out.append(data)
        return out
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass


def _public_addrs(host: str, port: int) -> list[str]:
    """Fail closed if DNS returns any private/loopback address."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    addrs: list[str] = []
    for info in infos:
        ip_s = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            return []
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return []
        addrs.append(ip_s)
    return addrs


def _read_http_headers(sock: ssl.SSLSocket) -> tuple[bytes, bytes]:
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise OSError("socket closed during handshake")
        buf.extend(chunk)
        if len(buf) > 65_536:
            raise OSError("handshake too large")
    head, rest = bytes(buf).split(b"\r\n\r\n", 1)
    return head, rest


def _handshake_ok(header: bytes, nonce: str) -> bool:
    try:
        status = header.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    except IndexError:
        return False
    if "101" not in status:
        return False
    expect = base64.b64encode(hashlib.sha1(nonce.encode("ascii") + _WS_MAGIC).digest())
    accept = b""
    for line in header.split(b"\r\n")[1:]:
        if line.lower().startswith(b"sec-websocket-accept:"):
            accept = line.split(b":", 1)[1].strip()
            break
    return accept == expect


def _ws_send(sock: ssl.SSLSocket, payload: str | bytes, *, opcode: int = 0x1) -> None:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    mask = os.urandom(4)
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))
    n = len(data)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", n))
    header.extend(mask)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(header + masked)


class _SockBuf:
    def __init__(self, sock: ssl.SSLSocket, leftover: bytes) -> None:
        self.sock = sock
        self.buf = bytearray(leftover)

    def read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self.buf)))
            if not chunk:
                raise OSError("socket closed")
            self.buf.extend(chunk)
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def _ws_recv(buf: _SockBuf) -> tuple[int, bytes]:
    b0, b1 = buf.read(2)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", buf.read(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", buf.read(8))[0]
    if n > _MAX_FRAME:
        raise OSError("frame too large")
    mask = buf.read(4) if masked else b""
    payload = buf.read(n)
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload
