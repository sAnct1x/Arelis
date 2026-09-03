"""Published camera *positions* worldwide. Not video.

Operator catalogs wherever a public JSON/XML exists, plus OSM webcam
tags on every inhabited continent. Pins only — no still fetch, no stream
URL in meta. Caltrans publishes a look direction; that becomes a
viewshed. Other pose is unknown unless a prior exists. Owned pins come
from secrets the user pasted. Unsecured IP cameras are out. An open
port is not consent. One US city (NYC) is a catalog, not the map.
"""

from __future__ import annotations

from arelis.earth.cameras_fetch import (
    CALTRANS_CCTV,
    CALTRANS_HOST,
    entities_from_algo,
    entities_from_caltrans,
    entities_from_cars_cameras,
    entities_from_deldot,
    entities_from_finland,
    entities_from_geojson_cameras,
    entities_from_hk_xml,
    entities_from_nyc,
    entities_from_ohgo_cameras,
    entities_from_places,
    entities_from_singapore,
    entities_from_tripcheck,
    entities_from_wsdot_cameras,
    fetch_cameras,
    load_owned,
)
from arelis.earth.osm import fetch_osm_webcams

# Fetchers live in cameras_fetch.py. Hosts stay in-tree for egress.
# Stream URL is not stored on the pin. An open port is not consent.


def _pin_host(host: str | None, pin: str) -> bool:
    """Pinned-host check. Tests patch ``cameras._host_pinned``."""
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


def _host_pinned(host: str | None, pin: str) -> bool:
    return _pin_host(host, pin)


__all__ = (
    "CALTRANS_CCTV",
    "CALTRANS_HOST",
    "entities_from_algo",
    "entities_from_caltrans",
    "entities_from_cars_cameras",
    "entities_from_deldot",
    "entities_from_finland",
    "entities_from_geojson_cameras",
    "entities_from_hk_xml",
    "entities_from_nyc",
    "entities_from_ohgo_cameras",
    "entities_from_places",
    "entities_from_singapore",
    "entities_from_tripcheck",
    "entities_from_wsdot_cameras",
    "fetch_cameras",
    "fetch_osm_webcams",
    "load_owned",
)
