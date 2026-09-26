"""Per-fetcher fail-soft. Timeout / 500 / unpinned host must not raise.

Modeled on shodan.py's HTTP shape (except Exception → None, host pin)
without touching shodan ethics or cameras_fetch internals.
"""

from __future__ import annotations

import importlib

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


def test_get_json_unpinned_does_not_open() -> None:
    from arelis.earth.http import get_json

    assert get_json("https://evil.example/x", "api.weather.gov") is None


def test_get_json_timeout_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.earth.http as http_mod

    monkeypatch.setattr(http_mod.httpx, "Client", _TimeoutClient)
    assert http_mod.get_json("https://api.weather.gov/alerts/active", "api.weather.gov") is None


def test_get_json_http_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.earth.http as http_mod

    class BoomResp:
        def raise_for_status(self) -> None:
            raise httpx.HTTPError("500")

        @property
        def url(self) -> str:
            return "https://api.weather.gov/alerts/active"

        def json(self) -> dict:
            return {"nope": True}

    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, *args: object, **kwargs: object) -> BoomResp:
            return BoomResp()

    monkeypatch.setattr(http_mod.httpx, "Client", Client)
    assert http_mod.get_json("https://api.weather.gov/alerts/active", "api.weather.gov") is None


def test_get_json_retries_once_then_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    import arelis.earth.http as http_mod

    hits = {"n": 0}

    class Resp:
        url = "https://api.weather.gov/alerts/active"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"ok": True}

    class Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            hits["n"] += 1
            if hits["n"] == 1:
                raise httpx.TimeoutException("slow")

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def get(self, *args: object, **kwargs: object) -> Resp:
            return Resp()

    monkeypatch.setattr(http_mod.httpx, "Client", Client)
    monkeypatch.setattr(http_mod.time, "sleep", lambda _s: None)
    got = http_mod.get_json(
        "https://api.weather.gov/alerts/active",
        "api.weather.gov",
        retries=1,
        backoff_s=0.0,
    )
    assert got == {"ok": True}
    assert hits["n"] == 2


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


@pytest.mark.parametrize("mod_name, func_name", _VIA_HELPER)
def test_helper_fetchers_fail_soft(
    monkeypatch: pytest.MonkeyPatch, mod_name: str, func_name: str
) -> None:
    monkeypatch.setattr("arelis.earth.http.get_json", lambda *_a, **_k: None)
    monkeypatch.setattr("arelis.earth.http.get_text", lambda *_a, **_k: None)
    mod = importlib.import_module(mod_name)
    got = getattr(mod, func_name)()
    assert got in (None, [])


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
    ("arelis.earth.shodan", "fetch_shodan"),
    ("arelis.earth.live", "fetch_usgs"),
)


@pytest.mark.parametrize("mod_name, func_name", _OWN_HTTPX)
def test_own_httpx_fetchers_fail_soft(
    monkeypatch: pytest.MonkeyPatch, mod_name: str, func_name: str
) -> None:
    mod = importlib.import_module(mod_name)
    if hasattr(mod, "httpx"):
        monkeypatch.setattr(mod.httpx, "Client", _TimeoutClient)
    got = getattr(mod, func_name)()
    assert got in (None, [])


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


def test_usgs_recorded_empty_features_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from arelis.earth import live

    body = json.loads((_FIXTURE_DIR / "usgs_all_day_empty.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(live.httpx, "Client", _client_with_body(body))
    assert live.fetch_usgs() == []


def test_opensky_recorded_states_shape() -> None:
    import json

    from arelis.earth.opensky import entities_from_opensky

    one = json.loads((_FIXTURE_DIR / "opensky_states_one.json").read_text(encoding="utf-8"))
    empty = json.loads((_FIXTURE_DIR / "opensky_states_empty.json").read_text(encoding="utf-8"))
    rows = entities_from_opensky(one)
    assert len(rows) == 1
    assert rows[0].id == "icao:abc123"
    assert rows[0].layer == "flights"
    assert entities_from_opensky(empty) == []


def test_usgs_live_optional() -> None:
    import os

    if os.environ.get("ARELIS_LIVE_EARTH", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        pytest.skip("optional live; set ARELIS_LIVE_EARTH=1")
    from arelis.earth.live import fetch_usgs

    got = fetch_usgs()
    assert got is None or isinstance(got, list)
    if got:
        assert all(e.layer == "quakes" for e in got)
