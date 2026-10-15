"""Per-fetcher fail-soft. Timeout / 500 / unpinned host must not raise.

Modeled on the other self-contained fetchers' HTTP shape (except Exception to None, host pin).
"""

from __future__ import annotations

import httpx
import pytest


class _TimeoutClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise httpx.TimeoutException("slow")

    def __enter__(self) -> _TimeoutClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_host_pinned_exact_and_suffix() -> None:
    from arelis.earth.http import host_pinned

    assert host_pinned("api.weather.gov", "api.weather.gov") is True
    assert host_pinned("www.api.weather.gov", "api.weather.gov") is True
    assert host_pinned("evil.example", "api.weather.gov") is False
    assert host_pinned(None, "api.weather.gov") is False


def test_get_json_timeout_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.earth.http as http_mod

    monkeypatch.setattr(http_mod.httpx, "Client", _TimeoutClient)
    assert (
        http_mod.get_json(
            "https://api.weather.gov/alerts/active", "api.weather.gov"
        )
        is None
    )


# Public fetch_* that now go through earth.http.get_json.
_VIA_HELPER = (
    ("arelis.earth.eonet", "fetch_eonet"),
    ("arelis.earth.nws", "fetch_nws"),
    ("arelis.earth.emsc", "fetch_emsc"),
    ("arelis.earth.gdacs", "fetch_gdacs"),
    ("arelis.earth.volcanoes", "fetch_volcanoes"),
    ("arelis.earth.swpc", "fetch_swpc"),
    ("arelis.earth.ndbc", "fetch_ndbc"),
    ("arelis.earth.adsb", "fetch_adsb_mil"),
    ("arelis.earth.geonet", "fetch_geonet"),
    ("arelis.earth.satnogs", "fetch_satnogs"),
    ("arelis.earth.traffic", "fetch_traffic"),
)


def test_camera_fetch_timeout_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public cameras API. Internals stay in cameras_fetch (C)."""
    from arelis.earth import cameras_fetch
    from arelis.earth.cameras import fetch_cameras

    monkeypatch.setattr(cameras_fetch, "_get_json", lambda *_a, **_k: None)
    monkeypatch.setattr(cameras_fetch, "_get_text", lambda *_a, **_k: None)
    monkeypatch.setattr(cameras_fetch, "_osm_webcams", lambda: None)
    monkeypatch.setattr(cameras_fetch, "_fetch_many_json", lambda *_a, **_k: [])
    assert fetch_cameras() is None


# Fetchers that still own their httpx Client. Timeout must not raise.
_OWN_HTTPX = (
    ("arelis.earth.radio", "fetch_radio"),
    ("arelis.earth.firms", "fetch_firms"),
    ("arelis.earth.launches", "fetch_launches"),
    ("arelis.earth.airports", "fetch_airports"),
    ("arelis.earth.wx", "fetch_weather"),
    ("arelis.earth.osm", "fetch_osm_webcams"),
    ("arelis.earth.opensky", "fetch_opensky"),
    ("arelis.earth.metar", "fetch_metar"),
    ("arelis.earth.tides", "fetch_tides"),
    ("arelis.earth.rwis", "fetch_rwis"),
    ("arelis.earth.argo", "fetch_argo"),
    ("arelis.earth.waqi", "fetch_waqi"),
    ("arelis.earth.openaq", "fetch_openaq"),
    ("arelis.earth.ais", "fetch_ais"),
    ("arelis.earth.aprs", "fetch_aprs"),
    ("arelis.earth.radar", "fetch_radar"),
    ("arelis.earth.gfw", "fetch_gfw"),
    ("arelis.earth.barentswatch", "fetch_barentswatch"),
    ("arelis.earth.fdsn", "fetch_fdsn"),
    ("arelis.earth.tle", "fetch_celestrak"),
    ("arelis.earth.spacetrack", "fetch_spacetrack"),
    ("arelis.earth.live", "fetch_usgs"),
)


_FIXTURE_DIR = __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "earth"


def _client_with_body(body: dict):
    real = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    def Client(*args: object, **kwargs: object):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    return Client


def test_usgs_recorded_geojson_becomes_quakes(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from arelis.earth import live

    body = json.loads((_FIXTURE_DIR / "usgs_all_day_two.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(live.httpx, "Client", _client_with_body(body))
    got = live.fetch_usgs()
    assert got is not None
    assert len(got) == 2
    assert all(e.layer == "quakes" for e in got)
    assert "Fake City" in got[0].label
    assert got[0].id.startswith("usgs:")


