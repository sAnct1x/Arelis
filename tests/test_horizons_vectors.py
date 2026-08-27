"""Horizons VECTORS parse and catalog table=vectors. Observer stays default."""

from __future__ import annotations

import httpx
import pytest

from arelis.physics.horizons import parse_vector_table
from arelis.tools.catalog import CatalogTool

_VECTOR_BLOB = """
*******************************************************************************
$$SOE
2451545.000000000 = A.D. 2000-Jan-01 12:00:00.0000 TDB
 X = 1.495978707000000E+08 Y =-2.000000000000000E+03 Z = 4.000000000000000E+03
 VX=-1.000000000000000E-03 VY= 2.978000000000000E+01 VZ=-4.000000000000000E-03
$$EOE
*******************************************************************************
"""


def test_parse_vector_table_km_s_to_si() -> None:
    state = parse_vector_table(_VECTOR_BLOB, units="KM-S")
    assert state.units == "SI"
    assert state.x == pytest.approx(1.495978707e11)
    assert state.vy == pytest.approx(29780.0)
    assert state.epoch_jd == pytest.approx(2451545.0)


def test_parse_refuses_a_blob_without_soe() -> None:
    with pytest.raises(ValueError, match="SOE"):
        parse_vector_table("no table here", units="KM-S")


@pytest.mark.asyncio
async def test_horizons_vectors_asks_ssb_eclipj2000() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"result": _VECTOR_BLOB})

    tool = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    result = await tool.run(
        action="horizons", target="399", date="2000-01-01", table="vectors"
    )
    assert result.ok, result.output
    assert seen
    url = seen[0].upper()
    assert "EMAIL" not in url
    assert "VECTORS" in url
    assert "ECLIPJ2000" in url
    assert result.data["center"] == "SSB"
    assert result.data["x"] == pytest.approx(1.495978707e11)
    assert result.data["jd"] == pytest.approx(2451545.0)


@pytest.mark.asyncio
async def test_horizons_default_table_is_still_observer() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"result": "range 1.52 au"})

    tool = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    result = await tool.run(action="horizons", target="Mars", date="2026-08-19")
    assert result.ok, result.output
    assert "OBSERVER" in seen[0].upper()
    assert result.data.get("table") == "observer"


@pytest.mark.asyncio
async def test_horizons_quotes_command() -> None:
    from urllib.parse import unquote

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(unquote(str(request.url)))
        return httpx.Response(200, json={"result": _VECTOR_BLOB})

    tool = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    result = await tool.run(
        action="horizons", target="399", date="2000-01-01", table="vectors"
    )
    assert result.ok, result.output
    assert "COMMAND='399'" in seen[0]


@pytest.mark.asyncio
async def test_horizons_retries_503_then_succeeds(monkeypatch) -> None:
    import arelis.tools.catalog as catalog

    monkeypatch.setattr(catalog, "HORIZONS_RETRY_S", (0.0,))
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"result": _VECTOR_BLOB})

    tool = CatalogTool(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
    )
    result = await tool.run(
        action="horizons", target="10", date="2000-01-01", table="vectors"
    )
    assert result.ok, result.output
    assert hits["n"] == 2
