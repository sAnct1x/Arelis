"""Deterministic Earth. Labeled simulated. Same seed, same sky.

This is the observatory when no live key is on: Kepler ISS, great-circle
flights, coastal ships, LEO/MEO shells, seismic belts, published camera
pins. Live adapters replace a layer later; they do not paint over holes.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import MEAN_R, WGS84_A, ecef_to_lla, lla_to_ecef
from arelis.earth.store import EntityStore
from arelis.earth.viewshed import attach_viewshed

SEED = 20260828
ISS_NORAD = 25544
ISS_ALT_M = 420_000.0
ISS_INCL = math.radians(51.6)
ISS_PERIOD_S = 92.9 * 60.0
# GPS-ish MEO
GPS_ALT_M = 20_200_000.0
GPS_PERIOD_S = 43_082.0
# Starlink-ish shell
LEO_ALT_M = 550_000.0
LEO_PERIOD_S = 5_739.0

# (iata, lat, lon) — public airport coordinates, enough for a sky full of arcs.
AIRPORTS: tuple[tuple[str, float, float], ...] = (
    ("ATL", 33.64, -84.43),
    ("PEK", 40.08, 116.58),
    ("DXB", 25.25, 55.36),
    ("LAX", 33.94, -118.41),
    ("HND", 35.55, 139.78),
    ("ORD", 41.98, -87.91),
    ("LHR", 51.47, -0.45),
    ("CDG", 49.01, 2.55),
    ("DFW", 32.90, -97.04),
    ("CAN", 23.39, 113.30),
    ("IST", 41.28, 28.75),
    ("DEL", 28.56, 77.10),
    ("SIN", 1.36, 103.99),
    ("FRA", 50.03, 8.57),
    ("AMS", 52.31, 4.76),
    ("JFK", 40.64, -73.78),
    ("MAD", 40.47, -3.56),
    ("BKK", 13.69, 100.75),
    ("SFO", 37.62, -122.38),
    ("GRU", -23.43, -46.47),
    ("SYD", -33.95, 151.18),
    ("JNB", -26.14, 28.23),
    ("MEX", 19.44, -99.07),
    ("NRT", 35.76, 140.39),
    ("ICN", 37.46, 126.44),
    ("MIA", 25.80, -80.29),
    ("SEA", 47.45, -122.31),
    ("YVR", 49.19, -123.18),
    ("EWR", 40.69, -74.17),
    ("DOH", 25.27, 51.61),
)

PORTS: tuple[tuple[str, float, float], ...] = (
    ("Shanghai", 31.23, 121.49),
    ("Singapore", 1.26, 103.85),
    ("Rotterdam", 51.90, 4.48),
    ("Los Angeles", 33.73, -118.26),
    ("Hamburg", 53.54, 9.98),
    ("Antwerp", 51.27, 4.33),
    ("Busan", 35.10, 129.07),
    ("Long Beach", 33.75, -118.19),
    ("New York", 40.68, -74.02),
    ("Santos", -23.98, -46.30),
    ("Durban", -29.87, 31.03),
    ("Piraeus", 37.94, 23.64),
    ("Valencia", 39.44, -0.32),
    ("Tokyo", 35.62, 139.80),
    ("Vancouver", 49.29, -123.11),
    ("Oakland", 37.80, -122.32),
)

RADIO: tuple[tuple[str, float, float], ...] = (
    ("BBC Radio 4", 51.51, -0.14),
    ("NPR", 38.90, -77.04),
    ("NHK FM", 35.66, 139.75),
    ("Radio France", 48.85, 2.35),
    ("ABC Sydney", -33.87, 151.21),
    ("CBC Toronto", 43.65, -79.38),
    ("Deutsche Welle", 50.72, 7.12),
    ("Al Jazeera", 25.29, 51.51),
)

# Published municipal camera *pins* (city open-data locations). Not feeds.
CAMERAS: tuple[tuple[str, float, float, str], ...] = (
    ("tfl:trafalgar", 51.508, -0.128, "TfL Trafalgar Square"),
    ("tfl:london-bridge", 51.508, -0.088, "TfL London Bridge"),
    ("caltrans:101-sf", 37.784, -122.406, "Caltrans US-101 San Francisco"),
    ("caltrans:405-la", 34.052, -118.243, "Caltrans I-405 Los Angeles"),
    ("austin:6th", 30.267, -97.743, "Austin 6th Street"),
    ("austin:congress", 30.265, -97.744, "Austin Congress"),
)

SITES: tuple[tuple[str, float, float, str], ...] = (
    ("site:three-gorges", 30.82, 111.00, "Three Gorges Dam"),
    ("site:hoover", 36.02, -114.74, "Hoover Dam"),
    ("site:itaipu", -25.41, -54.59, "Itaipu"),
)


def _slerp_lla(
    a: tuple[float, float], b: tuple[float, float], u: float
) -> tuple[float, float]:
    """Great-circle interpolation in degrees. u in [0, 1]."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    x1, y1, z1 = (
        math.cos(lat1) * math.cos(lon1),
        math.cos(lat1) * math.sin(lon1),
        math.sin(lat1),
    )
    x2, y2, z2 = (
        math.cos(lat2) * math.cos(lon2),
        math.cos(lat2) * math.sin(lon2),
        math.sin(lat2),
    )
    d = max(-1.0, min(1.0, x1 * x2 + y1 * y2 + z1 * z2))
    omega = math.acos(d)
    if omega < 1e-9:
        return a
    s = math.sin(omega)
    w1, w2 = math.sin((1.0 - u) * omega) / s, math.sin(u * omega) / s
    x, y, z = w1 * x1 + w2 * x2, w1 * y1 + w2 * y2, w1 * z1 + w2 * z2
    hyp = math.hypot(x, y)
    lat = math.degrees(math.atan2(z, hyp))
    lon = math.degrees(math.atan2(y, x))
    return (lat, lon)


def _gcd_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2.0 * MEAN_R * math.asin(min(1.0, math.sqrt(h)))


def _circle_ecef(
    alt_m: float,
    incl: float,
    period_s: float,
    unix: float,
    phase: float,
    raan: float,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    r = WGS84_A + alt_m
    n = 2.0 * math.pi / period_s
    nu = (n * unix + phase) % (2.0 * math.pi)
    # Perifocal then R3(raan) R1(incl)
    px, py = r * math.cos(nu), r * math.sin(nu)
    ci, si = math.cos(incl), math.sin(incl)
    cr, sr = math.cos(raan), math.sin(raan)
    # R1(i): y' = y ci, z' = y si
    y1, z1 = py * ci, py * si
    x = px * cr - y1 * sr
    y = px * sr + y1 * cr
    z = z1
    # Velocity in perifocal: n * r * (-sin, cos)
    vx_p, vy_p = -n * r * math.sin(nu), n * r * math.cos(nu)
    vy1, vz1 = vy_p * ci, vy_p * si
    vx = vx_p * cr - vy1 * sr
    vy = vx_p * sr + vy1 * cr
    vz = vz1
    return (x, y, z), (vx, vy, vz)


def iss_entity(unix: float) -> Entity:
    pos, vel = _circle_ecef(
        ISS_ALT_M, ISS_INCL, ISS_PERIOD_S, unix, 0.35, 1.12
    )
    return Entity(
        id=f"norad:{ISS_NORAD}",
        cls="satellite",
        layer="iss",
        label="ISS",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=vel[0],
        vy=vel[1],
        vz=vel[2],
        when_unix=unix,
        source="simulated Kepler circular",
        freshness="simulated",
        confidence=0.6,
        cite="ISS mean elements: i≈51.6°, h≈420 km, P≈92.9 min. Not SGP4.",
        meta={"norad": ISS_NORAD, "alt_m": ISS_ALT_M},
        coverage=Coverage(
            "orbit",
            "Whole Earth except the polar caps it never reaches.",
            "inclination 51.6°",
        ),
    )


def _flight_routes(rng: random.Random, n: int) -> list[tuple[int, int, float]]:
    routes: list[tuple[int, int, float]] = []
    for i in range(n):
        a, b = rng.randrange(len(AIRPORTS)), rng.randrange(len(AIRPORTS))
        if a == b:
            b = (b + 1 + i) % len(AIRPORTS)
        routes.append((a, b, rng.random()))
    return routes


def _flights(unix: float, rng: random.Random, n: int = 280) -> list[Entity]:
    tas = 250.0  # m/s cruise sketch
    out: list[Entity] = []
    for i, (ia, ib, phase) in enumerate(_flight_routes(rng, n)):
        a, b = AIRPORTS[ia], AIRPORTS[ib]
        dist = max(_gcd_m((a[1], a[2]), (b[1], b[2])), 1.0)
        dur = dist / tas
        u = (unix / dur + phase) % 1.0
        lat, lon = _slerp_lla((a[1], a[2]), (b[1], b[2]), u)
        alt = 10_000.0 + 2_000.0 * math.sin(i + 0.4)
        pos = lla_to_ecef(lat, lon, alt)
        lat2, lon2 = _slerp_lla((a[1], a[2]), (b[1], b[2]), min(1.0, u + 0.002))
        nxt = lla_to_ecef(lat2, lon2, alt)
        vx, vy, vz = (nxt[0] - pos[0]) / 20.0, (nxt[1] - pos[1]) / 20.0, (
            nxt[2] - pos[2]
        ) / 20.0
        mil = i % 37 == 0
        layer = "military" if mil else "flights"
        out.append(
            Entity(
                id=f"sim-flight:{i:04d}",
                cls="aircraft",
                layer=layer,
                label=f"{a[0]}→{b[0]}" + (" mil" if mil else ""),
                x=pos[0],
                y=pos[1],
                z=pos[2],
                vx=vx,
                vy=vy,
                vz=vz,
                when_unix=unix,
                source="simulated great-circle",
                freshness="simulated",
                confidence=0.4,
                cite="Constant TAS 250 m/s on airport pairs. Not ADS-B.",
                meta={"from": a[0], "to": b[0], "alt_m": alt, "military": mil},
            )
        )
    return out


def _vessels(unix: float, rng: random.Random, n: int = 120) -> list[Entity]:
    out: list[Entity] = []
    for i in range(n):
        ia = i % len(PORTS)
        ib = (ia + 1 + (i // len(PORTS))) % len(PORTS)
        a, b = PORTS[ia], PORTS[ib]
        dist = max(_gcd_m((a[1], a[2]), (b[1], b[2])), 1.0)
        speed = 8.0  # m/s ~ 15.5 kn
        dur = dist / speed
        u = (unix / dur + rng.random()) % 1.0
        lat, lon = _slerp_lla((a[1], a[2]), (b[1], b[2]), u)
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"sim-ship:{i:04d}",
                cls="vessel",
                layer="vessels",
                label=f"{a[0]}→{b[0]}",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                when_unix=unix,
                source="simulated coastal",
                freshness="simulated",
                confidence=0.35,
                cite="Great-circle between ports at 15 kn. Not AIS. Ocean is empty on purpose.",
                meta={"from": a[0], "to": b[0]},
                coverage=Coverage(
                    "coastal",
                    "No mid-ocean fill. VHF dies offshore. We do not buy satellite AIS.",
                ),
            )
        )
    return out


def _satellites(unix: float, n_leo: int = 96, n_gps: int = 24) -> list[Entity]:
    out: list[Entity] = []
    for i in range(n_leo):
        plane = i % 8
        slot = i // 8
        raan = plane * (math.pi / 4.0)
        phase = slot * (2.0 * math.pi / max(n_leo // 8, 1))
        pos, vel = _circle_ecef(
            LEO_ALT_M, math.radians(53.0), LEO_PERIOD_S, unix, phase, raan
        )
        out.append(
            Entity(
                id=f"sim-leo:{i:03d}",
                cls="satellite",
                layer="satellites",
                label=f"LEO-{i:03d}",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                vx=vel[0],
                vy=vel[1],
                vz=vel[2],
                when_unix=unix,
                source="simulated LEO shell",
                freshness="simulated",
                confidence=0.45,
                cite="Circular 53° / 550 km shell. Starlink-shaped, not a catalog.",
                meta={"shell": "leo", "alt_m": LEO_ALT_M},
            )
        )
    for i in range(n_gps):
        plane = i % 6
        slot = i // 6
        raan = plane * (math.pi / 3.0)
        phase = slot * (math.pi / 2.0) + 0.2
        pos, vel = _circle_ecef(
            GPS_ALT_M, math.radians(55.0), GPS_PERIOD_S, unix, phase, raan
        )
        out.append(
            Entity(
                id=f"sim-gps:{i:02d}",
                cls="satellite",
                layer="satellites",
                label=f"GPS-{i:02d}",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                vx=vel[0],
                vy=vel[1],
                vz=vel[2],
                when_unix=unix,
                source="simulated GPS constellation",
                freshness="simulated",
                confidence=0.5,
                cite="24 slots, 55°, 20 200 km. Walker-shaped, not the almanac.",
                meta={"shell": "gps", "alt_m": GPS_ALT_M},
            )
        )
    return out


def _quakes(unix: float, rng: random.Random, n: int = 48) -> list[Entity]:
    # Rough belts: circum-Pacific + Alpine-Himalayan
    belts = (
        (0.0, 120.0, 35.0),
        (35.0, 140.0, 20.0),
        (-20.0, -70.0, 25.0),
        (38.0, 22.0, 12.0),
        (36.0, -120.0, 8.0),
        (-33.0, -72.0, 10.0),
        (28.0, 87.0, 15.0),
        (44.0, 148.0, 12.0),
    )
    out: list[Entity] = []
    for i in range(n):
        lat0, lon0, span = belts[i % len(belts)]
        lat = lat0 + (rng.random() - 0.5) * span
        lon = lon0 + (rng.random() - 0.5) * span * 1.4
        mag = 3.2 + rng.random() * 4.0
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"sim-quake:{i:03d}",
                cls="quake",
                layer="quakes",
                label=f"M{mag:.1f}",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                when_unix=unix - rng.random() * 86_400.0,
                source="simulated seismic belts",
                freshness="simulated",
                confidence=0.3,
                cite="Belt sketch, not USGS. Live adapter replaces this layer.",
                meta={"mag": mag, "lat": lat, "lon": lon},
            )
        )
    return out


def _fires(unix: float, rng: random.Random, n: int = 40) -> list[Entity]:
    bands = ((38.0, -122.0), (-15.0, -50.0), (45.0, 16.0), (-25.0, 31.0), (20.0, 78.0))
    out: list[Entity] = []
    for i in range(n):
        lat0, lon0 = bands[i % len(bands)]
        lat = lat0 + (rng.random() - 0.5) * 8.0
        lon = lon0 + (rng.random() - 0.5) * 10.0
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"sim-fire:{i:03d}",
                cls="fire",
                layer="fires",
                label="hotspot",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                when_unix=unix,
                source="simulated hotspots",
                freshness="simulated",
                confidence=0.25,
                cite="Not FIRMS. A later adapter with a map key replaces these.",
                meta={"lat": lat, "lon": lon},
            )
        )
    return out


def _radio() -> list[Entity]:
    out: list[Entity] = []
    for i, (name, lat, lon) in enumerate(RADIO):
        pos = lla_to_ecef(lat, lon, 120.0)
        out.append(
            Entity(
                id=f"sim-radio:{i:02d}",
                cls="rf",
                layer="radio",
                label=name,
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="simulated major FM",
                freshness="simulated",
                confidence=0.7,
                cite="City transmitter pin. Live adapter: Radio Browser directory.",
                meta={"lat": lat, "lon": lon},
            )
        )
    return out


def _camera_entity(cid: str, lat: float, lon: float, label: str) -> Entity:
    pos = lla_to_ecef(lat, lon, 12.0)
    return Entity(
        id=cid,
        cls="camera",
        layer="cameras",
        label=label,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="published municipal pin",
        freshness="reconstructed",
        confidence=0.8,
        cite="Position only. No video ingest. Unsecured IP cams are out.",
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "viewshed",
            "Pose-prior frustum. Occluders not meshed. Unpublished cams are holes.",
            "pose prior",
        ),
        pii="none",
    )


def _cameras() -> list[Entity]:
    return [attach_viewshed(_camera_entity(*row)) for row in CAMERAS]


def _sites() -> list[Entity]:
    out: list[Entity] = []
    for sid, lat, lon, label in SITES:
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=sid,
                cls="site",
                layer="sites",
                label=label,
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="bundled public coordinates",
                freshness="reconstructed",
                confidence=0.9,
                cite="Static pin. Not a live SCADA feed.",
                meta={"lat": lat, "lon": lon},
            )
        )
    for iata, lat, lon in AIRPORTS:
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"airport:{iata}",
                cls="site",
                layer="sites",
                label=iata,
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="bundled airport coordinates",
                freshness="reconstructed",
                confidence=0.9,
                cite="IATA pin for routes. Not OurAirports live.",
                meta={"iata": iata, "lat": lat, "lon": lon},
            )
        )
    return out


def _weather(unix: float) -> list[Entity]:
    cities = (
        ("London", 51.5, -0.12),
        ("Tokyo", 35.7, 139.7),
        ("New York", 40.7, -74.0),
        ("Nairobi", -1.3, 36.8),
        ("São Paulo", -23.5, -46.6),
        ("Reykjavík", 64.1, -21.9),
    )
    out: list[Entity] = []
    for i, (name, lat, lon) in enumerate(cities):
        # Crude: warmer at equator, seasonal sine on unix.
        season = math.sin(2.0 * math.pi * (unix % 31_557_600.0) / 31_557_600.0)
        temp = 15.0 - abs(lat) * 0.35 + 8.0 * season * (1.0 if lat >= 0 else -1.0)
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"sim-wx:{i:02d}",
                cls="weather",
                layer="weather",
                label=f"{name} {temp:.0f}°C",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                when_unix=unix,
                source="simulated climate sketch",
                freshness="simulated",
                confidence=0.2,
                cite="Latitude + annual sine. Call weather for Open-Meteo.",
                meta={"place": name, "temp_c": temp, "lat": lat, "lon": lon},
            )
        )
    return out


def _traffic(unix: float, rng: random.Random, n: int = 40) -> list[Entity]:
    cities = (
        (34.05, -118.24),
        (40.71, -74.01),
        (51.51, -0.13),
        (35.68, 139.69),
    )
    out: list[Entity] = []
    for i in range(n):
        lat0, lon0 = cities[i % len(cities)]
        lat = lat0 + (rng.random() - 0.5) * 0.08
        lon = lon0 + (rng.random() - 0.5) * 0.08
        pos = lla_to_ecef(lat, lon, 8.0)
        out.append(
            Entity(
                id=f"sim-traffic:{i:03d}",
                cls="traffic",
                layer="traffic",
                label="flow",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                when_unix=unix,
                source="simulated street dots",
                freshness="simulated",
                confidence=0.15,
                cite="Keyless traffic is a labeled simulation. TomTom would replace it.",
                meta={"lat": lat, "lon": lon},
            )
        )
    return out


def populate(store: EntityStore, unix: float, *, seed: int = SEED) -> None:
    """Rebuild moving layers. Static pins are rewritten too so leave/enter is clean."""
    rng = random.Random(seed)
    store.clear()
    store.upsert(iss_entity(unix))
    for e in _flights(unix, rng):
        store.upsert(e)
    rng2 = random.Random(seed + 1)
    for e in _vessels(unix, rng2):
        store.upsert(e)
    for e in _satellites(unix):
        store.upsert(e)
    rng3 = random.Random(seed + 2)
    for e in _quakes(unix, rng3):
        store.upsert(e)
    rng4 = random.Random(seed + 3)
    for e in _fires(unix, rng4):
        store.upsert(e)
    for e in _radio():
        store.upsert(e)
    for e in _cameras():
        store.upsert(e)
    for e in _sites():
        store.upsert(e)
    for e in _weather(unix):
        store.upsert(e)
    rng5 = random.Random(seed + 4)
    for e in _traffic(unix, rng5):
        store.upsert(e)


_FEED_TAGS = frozenset(
    {"live", "delayed", "interpolated", "dead-reckoned", "stale"}
)


def _feed_owns(store: EntityStore, *layers: str) -> bool:
    """A live adapter replaced this layer; do not paint sim back over it."""
    for layer in layers:
        for e in store.in_layer(layer):
            if e.freshness in _FEED_TAGS:
                return True
    return False


_DR_AFTER_S = 90.0
_STALE_AFTER_S = 15.0 * 60.0
_DR_LAYERS = frozenset({"flights", "drones", "military", "vessels"})


def refresh_moving(
    store: EntityStore, unix: float, *, seed: int = SEED, dt: float = 0.0
) -> None:
    """Update ISS, flights, vessels, satellites in place. Pins stay.

    Live-owned layers are skipped so OpenSky / AISStream are not clobbered
    by the simulated world on the next tick. Those tracks coast with
    reported velocity and are tagged dead-reckoned, then stale.
    """
    rng = random.Random(seed)
    if not _feed_owns(store, "iss"):
        store.upsert(iss_entity(unix))
    air_live = _feed_owns(store, "flights", "drones")
    mil_live = _feed_owns(store, "military")
    if not air_live:
        for e in _flights(unix, rng):
            if e.layer == "military" and mil_live:
                continue
            store.upsert(e)
    if not _feed_owns(store, "vessels"):
        rng2 = random.Random(seed + 1)
        for e in _vessels(unix, rng2):
            store.upsert(e)
    if not _feed_owns(store, "satellites"):
        for e in _satellites(unix):
            store.upsert(e)
    advance_live(store, unix, dt)


def advance_live(store: EntityStore, unix: float, dt: float) -> None:
    """Coast feed-owned air/sea tracks. Sats stay at last SGP4 until the next poll."""
    move = 0.0 if dt <= 0.0 or dt > 120.0 else dt
    for e in store.all():
        if e.layer not in _DR_LAYERS:
            continue
        if e.freshness not in _FEED_TAGS:
            continue
        age = (unix - e.when_unix) if e.when_unix > 0.0 else 0.0
        if age >= _STALE_AFTER_S:
            e.freshness = "stale"
            continue
        if age >= _DR_AFTER_S and e.freshness in {"live", "delayed", "interpolated"}:
            e.freshness = "dead-reckoned"
        if move <= 0.0 or e.speed() < 0.5:
            continue
        e.x += e.vx * move
        e.y += e.vy * move
        e.z += e.vz * move
        lat, lon, _alt = ecef_to_lla(e.x, e.y, e.z)
        e.meta = {**e.meta, "lat": lat, "lon": lon}


def entities(
    unix: float, *, seed: int = SEED, layers: Iterable[str] | None = None
) -> list[Entity]:
    store = EntityStore()
    populate(store, unix, seed=seed)
    if layers is None:
        return list(store.all())
    wanted = set(layers)
    return [e for e in store.all() if e.layer in wanted]
