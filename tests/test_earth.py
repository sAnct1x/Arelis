"""Earth zone: enter, ISS, simulated world, dump, tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.earth.frames import ecef_to_lla, lla_to_ecef
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.tools.earth_tool import EarthTool


@pytest.fixture(autouse=True)
def _isolate_earth(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.look import forget

    set_earth(None)
    forget()
    # Enter must not read the developer's contacts.yaml / secrets cameras.
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_local",
        lambda self: None,
    )
    yield
    forget()
    set_earth(None)


_LIVE_FETCHERS = (
    "fetch_usgs",
    "fetch_opensky",
    "fetch_adsb_mil",
    "fetch_ais",
    "fetch_celestrak",
    "fetch_radio",
    "fetch_cameras",
    "fetch_weather",
    "fetch_firms",
    "fetch_launches",
    "fetch_aprs",
    "fetch_traffic",
    "fetch_radar",
    "fetch_gfw",
    "fetch_eonet",
    "fetch_nws",
    "fetch_airports",
    "fetch_spacetrack",
    "fetch_tip",
    "fetch_emsc",
    "fetch_swpc",
    "fetch_satnogs",
    "fetch_metar",
    "fetch_waqi",
    "fetch_geonet",
    "fetch_ndbc",
    "fetch_volcanoes",
    "fetch_gdacs",
    "fetch_tides",
    "fetch_argo",
    "fetch_openaq",
    "fetch_rwis",
    "fetch_fdsn",
)


def _mute_live(monkeypatch: pytest.MonkeyPatch, **keep: object) -> None:
    """Stub every live adapter. A new fetch in merge_live must land here."""

    def _none() -> None:
        return None

    for name in _LIVE_FETCHERS:
        monkeypatch.setattr(f"arelis.earth.live.{name}", keep.get(name, _none))


def test_lla_roundtrip_is_near_the_pin() -> None:
    x, y, z = lla_to_ecef(51.5, -0.12, 0.0)
    lat, lon, alt = ecef_to_lla(x, y, z)
    assert lat == pytest.approx(51.5, abs=0.4)
    assert lon == pytest.approx(-0.12, abs=0.4)
    assert abs(alt) < 30_000.0


@pytest.mark.asyncio
async def test_earth_tool_enter_status_leave(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    monkeypatch.setattr("arelis.earth.dump.dumps_root", lambda: tmp_path / "earth")
    set_earth(EarthRuntime())
    tool = EarthTool()
    entered = await tool.run(action="enter")
    assert entered.ok, entered.output
    assert entered.data["active"] is True
    status = await tool.run(action="status")
    assert status.ok
    assert "Earth" in status.output
    left = await tool.run(action="leave")
    assert left.ok
    assert left.data["active"] is False


def test_earth_cam_roundtrip_keeps_the_eye() -> None:
    from arelis.earth.frames import apply_earth_cam, capture_earth_cam
    from arelis.physics.camera import FlyCamera

    cam = FlyCamera()
    earth = (1.4e11, 2.0e10, -1.0e9)
    cam.x, cam.y, cam.z = earth[0] + 8.0e7, earth[1], earth[2]
    cam.look_at(*earth)
    jd = 2_451_545.0
    pose = capture_earth_cam(cam, earth, jd)
    cam.x += 1.0e9
    apply_earth_cam(cam, earth, jd, pose)
    assert cam.x == pytest.approx(earth[0] + 8.0e7, rel=1e-6, abs=20.0)
    assert cam.y == pytest.approx(earth[1], rel=1e-6, abs=20.0)
    assert cam.z == pytest.approx(earth[2], rel=1e-6, abs=20.0)


def _ais_envelope(lat: float, lon: float, mmsi: str, name: str = "TEST") -> dict:
    return {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": name,
            "latitude": lat,
            "longitude": lon,
            "time_utc": "2026-08-28 12:00:00.000000000 +0000 UTC",
        },
        "Message": {
            "PositionReport": {
                "UserID": int(mmsi) if mmsi.isdigit() else 0,
                "Latitude": lat,
                "Longitude": lon,
                "Sog": 12.3,
                "Cog": 180.0,
            }
        },
    }


# Public ISS TLE (CelesTrak epoch 2008 day 264). Not a personal coordinate.
_ISS_TLE = """ISS (ZARYA)
1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927
2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537
"""


def test_lod_gates_planes_boats_and_cameras() -> None:
    from arelis.earth.lod import adapter_allowed, chip_layers, paint_layers

    assert adapter_allowed("opensky", "space") is False
    assert adapter_allowed("opensky", "approach") is True
    assert adapter_allowed("ais", "approach") is False
    assert adapter_allowed("ais", "near") is True
    assert adapter_allowed("cameras", "near") is False
    assert adapter_allowed("cameras", "city") is True
    assert adapter_allowed("celestrak", "city") is True
    assert adapter_allowed(
        "opensky", "city", {"flights": False, "drones": False}
    ) is False
    assert adapter_allowed("opensky", "city", {"flights": True}) is True
    assert "flights" in paint_layers("approach")
    assert "satellites" in paint_layers("approach")
    assert "cameras" not in paint_layers("approach")
    assert "vessels" in paint_layers("near")
    assert "satellites" in paint_layers("near")
    assert "cameras" not in paint_layers("near")
    assert "cameras" in paint_layers("city")
    assert "quakes" in paint_layers("space")
    assert "fires" in paint_layers("space")
    assert "cameras" not in paint_layers("space")
    assert chip_layers("space") == ("satellites", "iss", "quakes", "fires")
    assert "flights" in (chip_layers("approach") or ())
    assert "satellites" in (chip_layers("approach") or ())
    assert chip_layers("city") is None
    from arelis.earth.lod import adapters_due

    due = adapters_due(
        "city", {}, 1000.0, {"cameras": False, "flights": True, "drones": False}
    )
    assert "cameras" not in due
    assert "opensky" in due
    assert "ais" not in due


def _opaque_pixels(img) -> int:
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 0:
                n += 1
    return n

