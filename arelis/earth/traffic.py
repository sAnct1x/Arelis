"""Lane closures and published road disruptions. Not individual cars.

Caltrans LCS, TfL Road, Fintraffic, plus national 511 / Open511 /
Live Traffic / WZDx / official ArcGIS catalogs worldwide. Operator
JSON, not VINs. Failures return None so the simulated flow sketch stays.
"""

from __future__ import annotations

from arelis.earth.traffic_fetch import (
    CALTRANS_HOST,
    CALTRANS_LCS,
    entities_from_autobahn,
    entities_from_cars,
    entities_from_finland,
    entities_from_geojson_incidents,
    entities_from_lcs,
    entities_from_ohgo_events,
    entities_from_open511,
    entities_from_tfl,
    entities_from_wsdot_alerts,
    entities_from_wzdx,
    fetch_traffic,
)

# Fetchers live in traffic_fetch.py. Hosts stay in-tree for egress.
# Not a VIN index. Individual cars are not in this feed.

__all__ = (
    "CALTRANS_HOST",
    "CALTRANS_LCS",
    "entities_from_autobahn",
    "entities_from_cars",
    "entities_from_finland",
    "entities_from_geojson_incidents",
    "entities_from_lcs",
    "entities_from_ohgo_events",
    "entities_from_open511",
    "entities_from_tfl",
    "entities_from_wsdot_alerts",
    "entities_from_wzdx",
    "fetch_traffic",
)
