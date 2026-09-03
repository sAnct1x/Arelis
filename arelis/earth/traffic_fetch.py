"""Traffic catalog fetchers and entity builders.

Public imports stay on traffic.py. Individual cars are not in
these feeds — operator JSON, not VINs.

Caltrans LCS, TfL Road, Fintraffic, plus national 511 / Open511 /
Live Traffic / WZDx / official ArcGIS catalogs worldwide. Operator
JSON, not VINs. Failures return None so the simulated flow sketch stays.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.secrets import earth_cars_key, earth_secret

CALTRANS_HOST = "cwwp2.dot.ca.gov"
CALTRANS_LCS = tuple(
    f"https://cwwp2.dot.ca.gov/data/d{d}/lcs/lcsStatusD{d:02d}.json"
    for d in range(1, 13)
)
TFL_ROAD = "https://api.tfl.gov.uk/Road/all/Disruption"
TFL_HOST = "api.tfl.gov.uk"
FI_TRAFFIC = "https://tie.digitraffic.fi/api/traffic-message/v1/messages"
FI_HOST = "tie.digitraffic.fi"
DRIVEBC = "https://api.open511.gov.bc.ca/events?format=json&limit=500&status=ACTIVE"
DRIVEBC_HOST = "api.open511.gov.bc.ca"
NSW_HOST = "api.transport.nsw.gov.au"
NSW_HAZARDS = (
    "https://api.transport.nsw.gov.au/v1/live/hazards/incident-open.json",
    "https://api.transport.nsw.gov.au/v1/live/hazards/roadwork-open.json",
)
QLD_EVENTS = "https://api.qldtraffic.qld.gov.au/v2/events"
QLD_HOST = "api.qldtraffic.qld.gov.au"
NZTA_EVENTS = "https://trafficnz.info/service/traffic/rest/4/events"
NZTA_HOST = "trafficnz.info"
_UA = f"Arelis/{__version__} (+{__source_url__})"

# CARS-style 511 JSON. GET /api/v2/get/event. No VIN. Not every country.
_CARS: tuple[tuple[str, str, str], ...] = (
    ("511on.ca", "https://511on.ca/api/v2/get/event?format=json", "Ontario 511"),
    ("511.gov.mb.ca", "https://511.gov.mb.ca/api/v2/get/event?format=json", "Manitoba 511"),
    (
        "511.novascotia.ca",
        "https://511.novascotia.ca/api/v2/get/event?format=json",
        "Nova Scotia 511",
    ),
    ("511.alberta.ca", "https://511.alberta.ca/api/v2/get/event?format=json", "Alberta 511"),
    (
        "hotline.gov.sk.ca",
        "https://hotline.gov.sk.ca/api/v2/get/event?format=json",
        "Saskatchewan 511",
    ),
    ("fl511.com", "https://fl511.com/api/v2/get/event?format=json", "Florida 511"),
    ("511ny.org", "https://511ny.org/api/v2/get/event?format=json", "New York 511"),
    ("www.cotrip.org", "https://www.cotrip.org/api/v2/get/event?format=json", "COtrip 511"),
    ("511ia.org", "https://511ia.org/api/v2/get/event?format=json", "Iowa 511"),
    ("511mn.org", "https://511mn.org/api/v2/get/event?format=json", "Minnesota 511"),
    ("511ga.org", "https://511ga.org/api/v2/get/event?format=json", "Georgia 511"),
)

# WZDx work-zone GeoJSON. Same honesty: published closures, not cars.
# Several CARS /api/v2/get/event hosts want a key; their WZDx path does not.
_WZDX: tuple[tuple[str, str, str], ...] = (
    ("udottraffic.utah.gov", "https://udottraffic.utah.gov/wzdx/udot/v40/data", "Utah WZDx"),
    (
        "storage.googleapis.com",
        "https://storage.googleapis.com/kytc-its-2020-openrecords/public/feeds/WZDx/kytc_wzdx_v4.1.geojson",
        "Kentucky WZDx",
    ),
    (
        "traveler.modot.org",
        "https://traveler.modot.org/timconfig/feed/desktop/mo_wzdx.json",
        "Missouri WZDx",
    ),
    ("511wi.gov", "https://511wi.gov/api/wzdx", "Wisconsin WZDx"),
    ("511.idaho.gov", "https://511.idaho.gov/api/wzdx", "Idaho WZDx"),
    ("511ny.org", "https://511ny.org/api/wzdx", "New York WZDx"),
    ("az511.gov", "https://az511.gov/api/wzdx", "AZ511 WZDx"),
    ("511la.org", "https://511la.org/api/wzdx", "LADOTD WZDx"),
    ("511.alberta.ca", "https://511.alberta.ca/api/wzdx", "Alberta WZDx"),
    ("511.novascotia.ca", "https://511.novascotia.ca/api/wzdx", "Nova Scotia WZDx"),
    ("hotline.gov.sk.ca", "https://hotline.gov.sk.ca/api/wzdx", "Saskatchewan WZDx"),
    ("fl511.com", "https://fl511.com/api/wzdx", "FL511 WZDx"),
    ("511ia.org", "https://511ia.org/api/wzdx", "Iowa WZDx"),
    ("511mn.org", "https://511mn.org/api/wzdx", "Minnesota WZDx"),
    ("511ga.org", "https://511ga.org/api/wzdx", "Georgia WZDx"),
    ("drivenc.gov", "https://drivenc.gov/api/wzdx", "NCDOT WZDx"),
    (
        "in.carsprogram.org",
        "https://in.carsprogram.org/carsapi_v1/api/wzdx",
        "Indiana WZDx",
    ),
    (
        "kscars.kandrive.gov",
        "https://kscars.kandrive.gov/carsapi_v1/api/wzdx",
        "Kansas WZDx",
    ),
    (
        "wzdx.wsdot.wa.gov",
        "https://wzdx.wsdot.wa.gov/api/v4/WorkZoneFeed",
        "WSDOT WZDx",
    ),
    ("511.gnb.ca", "https://511.gnb.ca/api/wzdx", "New Brunswick WZDx"),
    ("511.gov.pe.ca", "https://511.gov.pe.ca/api/wzdx", "PEI WZDx"),
    ("511yukon.ca", "https://511yukon.ca/api/wzdx", "Yukon WZDx"),
    ("511.alaska.gov", "https://511.alaska.gov/api/wzdx", "Alaska 511 WZDx"),
    ("nvroads.com", "https://nvroads.com/api/wzdx", "Nevada WZDx"),
)

# Official ArcGIS FeatureServer GeoJSON. Operator catalogs, not VINs.
# host, url, source, prefix
_ARCGIS: tuple[tuple[str, str, str, str], ...] = (
    (
        "chartimap1.sha.maryland.gov",
        "https://chartimap1.sha.maryland.gov/arcgis/rest/services/CHART/Incidents/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&returnGeometry=true",
        "Maryland CHART",
        "md-chart",
    ),
    (
        "maps.sa.gov.au",
        "https://maps.sa.gov.au/arcgis/rest/services/DPTIExtTransport/TrafficSAOpenData2/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&returnGeometry=true",
        "South Australia traffic",
        "sa-road",
    ),
    (
        "maps.sa.gov.au",
        "https://maps.sa.gov.au/arcgis/rest/services/DPTIExtTransport/TrafficSAOpenData2/MapServer/1/query?where=1%3D1&outFields=*&f=geojson&returnGeometry=true",
        "South Australia closures",
        "sa-clo",
    ),
    (
        "gisservices.mainroads.wa.gov.au",
        "https://gisservices.mainroads.wa.gov.au/arcgis/rest/services/TravelInformation/MapServer/0/query?where=1%3D1&outFields=*&f=geojson&returnGeometry=true",
        "Main Roads WA",
        "wa-road",
    ),
    (
        "gisservices.mainroads.wa.gov.au",
        "https://gisservices.mainroads.wa.gov.au/arcgis/rest/services/TravelInformation/MapServer/1/query?where=1%3D1&outFields=*&f=geojson&returnGeometry=true",
        "Main Roads WA roadworks",
        "wa-works",
    ),
    (
        "gisservices.mainroads.wa.gov.au",
        "https://gisservices.mainroads.wa.gov.au/arcgis/rest/services/TravelInformation/MapServer/2/query?where=1%3D1&outFields=*&f=geojson&returnGeometry=true",
        "Main Roads WA events",
        "wa-evt",
    ),
)

ND_ALERTS = "https://travelfiles.dot.nd.gov/geojson_nc/alerts.json"
ND_HOST = "travelfiles.dot.nd.gov"
TX_HOST = "api.drivetexas.org"
TX_CONDITIONS = "https://api.drivetexas.org/api/conditions.geojson"
TX_WZDX = "https://api.drivetexas.org/api/conditions.wzdx.geojson"
TX_ENV = "ARELIS_DRIVETEXAS_KEY"
QC_EVENTS = (
    "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0"
    "&request=GetFeature&typename=ms:evenements&srsname=EPSG:4326&outputformat=geojson"
)
QC_CHANTIERS = (
    "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0"
    "&request=GetFeature&typename=ms:chantiers_mtmdet&srsname=EPSG:4326&outputformat=geojson"
)
QC_CONDITIONS = (
    "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0"
    "&request=GetFeature&typename=ms:conditions_routieres&srsname=EPSG:4326&outputformat=geojson"
)
QC_HOST = "ws.mapserver.transports.gouv.qc.ca"
DE_AUTOBAHN = "https://verkehr.autobahn.de/o/autobahn"
DE_HOST = "verkehr.autobahn.de"
WA_ALERTS = (
    "https://wsdot.wa.gov/Traffic/api/HighwayAlerts/"
    "HighwayAlertsREST.svc/GetAlertsAsJson"
)
WA_HOST = "wsdot.wa.gov"
WA_ENV = "ARELIS_WSDOT_ACCESS_CODE"
OH_HOST = "publicapi.ohgo.com"
OH_ENV = "ARELIS_OHGO_KEY"
OH_INCIDENTS = "https://publicapi.ohgo.com/api/v1/incidents"
OH_CONSTRUCTION = "https://publicapi.ohgo.com/api/v1/construction"
# Same CARS clones as cameras.py. Query is ?key=
_KEYED_CARS: tuple[tuple[str, str, str, str], ...] = (
    ("drivenc.gov", "NCDOT", "drivenc_key", "ARELIS_DRIVENC_KEY"),
    ("udottraffic.utah.gov", "UDOT", "", ""),
    ("az511.gov", "AZ511", "", ""),
    ("511.idaho.gov", "ITD", "", ""),
    ("511wi.gov", "WisDOT", "", ""),
    ("511la.org", "LADOTD", "", ""),
    ("511.alaska.gov", "Alaska 511", "", ""),
    ("nvroads.com", "Nevada 511", "", ""),
    ("ctroads.org", "CTDOT", "", ""),
    ("511.nebraska.gov", "Nebraska 511", "", ""),
)

_TIMEOUT = 8.0
_CAP = 2500
_CITE = (
    "Caltrans lane-closure / work-zone catalog. Operator JSON, not a VIN "
    "index. Individual cars are not in this feed."
)
_TFL_CITE = (
    "TfL Road Disruption. Operator catalog, not a VIN index. "
    "Individual cars are not in this feed."
)
_FI_CITE = (
    "Fintraffic traffic messages. Finnish roads. CC BY 4.0. "
    "Not a VIN index. Individual cars are not in this feed."
)
_OPEN511_CITE = (
    "DriveBC Open511. Provincial highway events. OGL-BC. "
    "Not a VIN index. Individual cars are not in this feed."
)
_NSW_CITE = (
    "NSW Live Traffic hazards. TfNSW public GeoJSON. "
    "Not a VIN index. Individual cars are not in this feed."
)
_QLD_CITE = (
    "QLDTraffic events. Queensland TMR GeoJSON. "
    "Not a VIN index. Individual cars are not in this feed."
)
_NZ_CITE = (
    "Waka Kotahi / NZTA traffic events. National highways. "
    "Not a VIN index. Individual cars are not in this feed."
)
_CARS_CITE = (
    "Published 511 event catalog. Operator JSON, not a VIN index. "
    "Individual cars are not in this feed."
)
_WZDX_CITE = (
    "WZDx work-zone GeoJSON. Published closures / roadworks, not a VIN index. "
    "Individual cars are not in this feed."
)
_ARCGIS_CITE = (
    "Published road-event GeoJSON. Operator catalog, not a VIN index. "
    "Individual cars are not in this feed."
)
_ND_CITE = (
    "NDDOT highway alerts GeoJSON. North Dakota roads. "
    "Not a VIN index. Individual cars are not in this feed."
)
_QC_CITE = (
    "Quebec 511 / MTMD published road events. Operator GeoJSON. "
    "Not a VIN index. Individual cars are not in this feed."
)
_DE_CITE = (
    "Autobahn GmbH published roadworks and warnings. Operator JSON. "
    "Not a VIN index. Individual cars are not in this feed."
)
_TX_CITE = (
    "DriveTexas / TxDOT published highway conditions. Operator GeoJSON. "
    "Not cameras. Not a VIN index. Individual cars are not in this feed."
)
_WA_CITE = (
    "WSDOT published highway alerts. Operator JSON. "
    "Not a VIN index. Individual cars are not in this feed."
)
_OH_CITE = (
    "OHGO / ODOT published incidents and construction. Operator JSON. "
    "Not a VIN index. Individual cars are not in this feed."
)


def fetch_traffic() -> list[Entity] | None:
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [
            pool.submit(_fetch_caltrans),
            pool.submit(_fetch_tfl),
            pool.submit(_fetch_finland),
            pool.submit(_fetch_drivebc),
            pool.submit(_fetch_nsw),
            pool.submit(_fetch_qld),
            pool.submit(_fetch_nzta),
            pool.submit(_fetch_cars),
            pool.submit(_fetch_wzdx),
            pool.submit(_fetch_arcgis),
            pool.submit(_fetch_nd),
            pool.submit(_fetch_quebec),
            pool.submit(_fetch_autobahn),
            pool.submit(_fetch_drivetexas),
            pool.submit(_fetch_wsdot),
            pool.submit(_fetch_ohgo),
            pool.submit(_fetch_keyed_cars),
        ]
        for fut in as_completed(futs):
            chunks.append(fut.result())
    if all(chunk is None for chunk in chunks):
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def _fetch_caltrans() -> list[Entity] | None:
    out: list[Entity] = []
    seen: set[str] = set()
    any_ok = False
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_get_json, url, CALTRANS_HOST) for url in CALTRANS_LCS]
        for fut in as_completed(futs):
            payload = fut.result()
            if not isinstance(payload, dict):
                continue
            any_ok = True
            for entity in entities_from_lcs(payload):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out


def entities_from_lcs(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_row(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_row(row: dict[str, Any]) -> Entity | None:
    block = row.get("lcs") if isinstance(row.get("lcs"), dict) else row
    loc = block.get("location") if isinstance(block.get("location"), dict) else {}
    lat = _num(loc.get("latitude"))
    lon = _num(loc.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    idx = str(block.get("index") or loc.get("locationName") or "").strip()
    name = str(loc.get("locationName") or idx).strip()
    route = str(loc.get("route") or loc.get("freewayBegin") or "").strip()
    district = str(loc.get("district") or "").strip()
    if not idx and not name:
        return None
    label = name if not route else f"{name} {route}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"lcs:{district or 'x'}:{idx or name.casefold()[:32]}",
        cls="traffic",
        layer="traffic",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Caltrans LCS",
        freshness="delayed",
        confidence=0.7,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "route": route},
        coverage=Coverage(
            "incident",
            "Published closure / work zone. Not a car. Not a plate.",
        ),
    )


def _fetch_tfl() -> list[Entity] | None:
    payload = _get_json(TFL_ROAD, TFL_HOST)
    if not isinstance(payload, list):
        return None
    return entities_from_tfl([row for row in payload if isinstance(row, dict)])


def entities_from_tfl(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        entity = _entity_from_tfl(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _fetch_finland() -> list[Entity] | None:
    payload = _get_json(FI_TRAFFIC, FI_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_finland(payload)
    return pins or None


def entities_from_finland(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_fi(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_fi(feat: dict[str, Any]) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    cid = str(props.get("situationId") or feat.get("id") or "").strip()
    title = str(props.get("title") or props.get("situationType") or cid).strip()
    if not cid and not title:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"fi-road:{cid or title.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=title[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Fintraffic traffic-message",
        freshness="delayed",
        confidence=0.7,
        cite=_FI_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published traffic message. Not a car. Not a plate.",
        ),
    )


def _geom_ll(geom: dict[str, Any]) -> tuple[float | None, float | None]:
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return None, None
    kind = str(geom.get("type") or "")
    if kind == "Point" and len(coords) >= 2:
        return _num(coords[1]), _num(coords[0])
    first = coords[0]
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        if isinstance(first[0], (list, tuple)):
            return _num(first[0][1]), _num(first[0][0])
        return _num(first[1]), _num(first[0])
    return None, None


def _entity_from_tfl(row: dict[str, Any]) -> Entity | None:
    lat, lon = _tfl_ll(row)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(row.get("id") or row.get("guid") or "").strip()
    loc = str(row.get("location") or row.get("commonName") or "").strip()
    cat = str(row.get("category") or row.get("severity") or "").strip()
    if not eid and not loc:
        return None
    label = loc or eid
    if cat and cat.casefold() not in label.casefold():
        label = f"{cat} {label}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"tfl-road:{eid or loc.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="TfL Road Disruption",
        freshness="delayed",
        confidence=0.7,
        cite=_TFL_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published disruption. Not a car. Not a plate.",
        ),
    )


def _fetch_drivebc() -> list[Entity] | None:
    payload = _get_json(DRIVEBC, DRIVEBC_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_open511(
        payload, prefix="bc511", source="DriveBC Open511", cite=_OPEN511_CITE
    )
    return pins or None


def entities_from_open511(
    payload: dict[str, Any],
    *,
    prefix: str,
    source: str,
    cite: str,
) -> list[Entity]:
    rows = payload.get("events")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_open511(row, prefix=prefix, source=source, cite=cite)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_open511(
    row: dict[str, Any], *, prefix: str, source: str, cite: str
) -> Entity | None:
    geom = row.get("geography") if isinstance(row.get("geography"), dict) else {}
    lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(row.get("id") or row.get("url") or "").strip()
    headline = str(row.get("headline") or row.get("event_type") or eid).strip()
    if not eid and not headline:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"{prefix}:{eid or headline.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=headline[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source=source,
        freshness="delayed",
        confidence=0.7,
        cite=cite,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published highway event. Not a car. Not a plate.",
        ),
    )


def _fetch_nsw() -> list[Entity] | None:
    any_ok = False
    out: list[Entity] = []
    seen: set[str] = set()
    for url in NSW_HAZARDS:
        payload = _get_json(url, NSW_HOST)
        if not isinstance(payload, dict):
            continue
        any_ok = True
        for entity in entities_from_geojson_incidents(
            payload, prefix="nsw", source="NSW Live Traffic", cite=_NSW_CITE
        ):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    if not any_ok:
        return None
    return out or None


def _fetch_qld() -> list[Entity] | None:
    payload = _get_json(QLD_EVENTS, QLD_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_incidents(
        payload, prefix="qld", source="QLDTraffic", cite=_QLD_CITE
    )
    return pins or None


def entities_from_geojson_incidents(
    payload: dict[str, Any], *, prefix: str, source: str, cite: str
) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_geojson_incident(
            row, prefix=prefix, source=source, cite=cite
        )
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_geojson_incident(
    feat: dict[str, Any], *, prefix: str, source: str, cite: str
) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        lat = _num(props.get("latitude") or props.get("lat"))
        lon = _num(props.get("longitude") or props.get("lon") or props.get("lng"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    cid = str(
        props.get("id")
        or props.get("Id")
        or props.get("GLOBALID")
        or props.get("identifiant")
        or props.get("identifiantChantier")
        or props.get("NumeroSegment")
        or props.get("hazardId")
        or props.get("event_id")
        or props.get("LOCATION_ID")
        or props.get("OBJECTID")
        or props.get("FID")
        or feat.get("id")
        or ""
    ).strip()
    title = str(
        props.get("headline")
        or props.get("displayName")
        or props.get("EventDescription")
        or props.get("identificationDesTravaux")
        or props.get("descriptionFrancais")
        or props.get("DescriptionEtatChausseeEN")
        or props.get("DescriptionEtatChausseeFR")
        or props.get("Description")
        or props.get("description")
        or props.get("DESCRIPTION")
        or props.get("PLOT_ALT_TEXT")
        or props.get("PLOT_DETAILS")
        or props.get("event_type")
        or props.get("RTE_NM")
        or props.get("type")
        or props.get("entrave")
        or props.get("localisation")
        or props.get("INCIDENTTYPE")
        or props.get("IncidentType")
        or props.get("EventType")
        or props.get("WorkType")
        or props.get("NAME")
        or props.get("title")
        or cid
    ).strip()
    road = str(
        props.get("Road")
        or props.get("NomRoute")
        or props.get("routeAutoroute")
        or props.get("LOCAL_ROAD_NAME")
        or props.get("RoadwayName")
        or ""
    ).strip()
    if road and road.casefold() not in title.casefold():
        title = f"{road} {title}" if title else road
    roads = props.get("roads")
    if isinstance(roads, list) and roads:
        first = roads[0] if isinstance(roads[0], dict) else {}
        street = str(first.get("mainStreet") or first.get("suburb") or "").strip()
        if street and street.casefold() not in title.casefold():
            title = f"{title} {street}" if title else street
    summary = props.get("road_summary")
    if isinstance(summary, dict):
        loc = str(summary.get("locality") or summary.get("road") or "").strip()
        if loc and loc.casefold() not in title.casefold():
            title = f"{title} {loc}" if title else loc
    if not cid and not title:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"{prefix}:{cid or title.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=title[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source=source,
        freshness="delayed",
        confidence=0.7,
        cite=cite,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published road event. Not a car. Not a plate.",
        ),
    )


def _fetch_nzta() -> list[Entity] | None:
    payload = _get_json(NZTA_EVENTS, NZTA_HOST)
    if payload is None:
        return None
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        raw = payload.get("events") or payload.get("event") or payload.get("features") or []
        if isinstance(raw, dict):
            raw = raw.get("event") or raw.get("events") or []
        rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
        if not rows and payload.get("features"):
            return entities_from_geojson_incidents(
                payload, prefix="nzta", source="NZTA traffic", cite=_NZ_CITE
            ) or None
    else:
        return None
    return entities_from_cars(rows, prefix="nzta", source="NZTA traffic") or None


def _fetch_wzdx() -> list[Entity] | None:
    any_ok = False
    out: list[Entity] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(_get_json, url, host) for host, url, _name in _WZDX]
        names = {host: name for host, _url, name in _WZDX}
        hosts = [host for host, _url, _name in _WZDX]
        for host, fut in zip(hosts, futs, strict=True):
            payload = fut.result()
            if not isinstance(payload, dict):
                continue
            any_ok = True
            source = names.get(host, "WZDx")
            prefix = _wzdx_prefix(host)
            for entity in entities_from_wzdx(payload, prefix=prefix, source=source):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out or None


def _wzdx_prefix(host: str) -> str:
    if host.startswith("udot"):
        return "ut-wzdx"
    if host.startswith("storage"):
        return "ky-wzdx"
    if "modot" in host:
        return "mo-wzdx"
    if host.startswith("511wi"):
        return "wi-wzdx"
    if "idaho" in host:
        return "id-wzdx"
    if "511ny" in host:
        return "ny-wzdx"
    if host.startswith("az511"):
        return "az-wzdx"
    if "511la" in host:
        return "la-wzdx"
    if "alberta" in host:
        return "ab-wzdx"
    if "novascotia" in host:
        return "ns-wzdx"
    if "hotline" in host or host.endswith("sk.ca"):
        return "sk-wzdx"
    if host.startswith("fl511"):
        return "fl-wzdx"
    if host.startswith("drivenc"):
        return "nc-wzdx"
    if host.startswith("in.cars"):
        return "in-wzdx"
    if host.startswith("kscars"):
        return "ks-wzdx"
    if "wsdot" in host:
        return "wa-wzdx"
    if host.endswith("gnb.ca"):
        return "nb-wzdx"
    if host.endswith("pe.ca"):
        return "pe-wzdx"
    if "yukon" in host:
        return "yt-wzdx"
    if "alaska" in host:
        return "ak-wzdx"
    if host.startswith("nvroads"):
        return "nv-wzdx"
    return host.split(".")[0][:12]


def entities_from_wzdx(
    payload: dict[str, Any], *, prefix: str, source: str
) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_wzdx(row, prefix=prefix, source=source)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_wzdx(
    feat: dict[str, Any], *, prefix: str, source: str
) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    core = props.get("core_details") if isinstance(props.get("core_details"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        lat = _num(props.get("latitude") or props.get("lat") or core.get("latitude"))
        lon = _num(props.get("longitude") or props.get("lon") or core.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    eid = str(
        props.get("road_event_id")
        or core.get("data_source_id")
        or feat.get("id")
        or props.get("id")
        or ""
    ).strip()
    roads = core.get("road_names") or props.get("road_names") or []
    road = ""
    if isinstance(roads, list) and roads:
        road = str(roads[0] or "").strip()
    elif isinstance(roads, str):
        road = roads.strip()
    kind = str(core.get("event_type") or props.get("event_type") or "work-zone").strip()
    desc = str(core.get("description") or props.get("description") or kind).strip()
    label = desc or kind
    if road and road.casefold() not in label.casefold():
        label = f"{road} {label}" if label else road
    if not eid and not label:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"{prefix}:{eid or label.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source=source,
        freshness="delayed",
        confidence=0.7,
        cite=_WZDX_CITE,
        meta={"lat": lat, "lon": lon, "event_type": kind},
        coverage=Coverage(
            "incident",
            "Published work zone. Not a car. Not a plate.",
        ),
    )


def _fetch_arcgis() -> list[Entity] | None:
    any_ok = False
    out: list[Entity] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [
            pool.submit(_get_json, url, host) for host, url, _name, _prefix in _ARCGIS
        ]
        meta = [(name, prefix) for _host, _url, name, prefix in _ARCGIS]
        for fut, (name, prefix) in zip(futs, meta, strict=True):
            payload = fut.result()
            if not isinstance(payload, dict):
                continue
            any_ok = True
            source = name
            for entity in entities_from_geojson_incidents(
                payload, prefix=prefix, source=source, cite=_ARCGIS_CITE
            ):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out or None


def _fetch_nd() -> list[Entity] | None:
    payload = _get_json(ND_ALERTS, ND_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_incidents(
        payload, prefix="nd511", source="NDDOT alerts", cite=_ND_CITE
    )
    return pins or None


def _fetch_cars() -> list[Entity] | None:
    any_ok = False
    out: list[Entity] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_get_json, url, host) for host, url, _name in _CARS]
        names = {host: name for host, _url, name in _CARS}
        hosts = [host for host, _url, _name in _CARS]
        for host, fut in zip(hosts, futs, strict=True):
            payload = fut.result()
            if payload is None:
                continue
            any_ok = True
            if isinstance(payload, list):
                rows = [row for row in payload if isinstance(row, dict)]
            elif isinstance(payload, dict):
                raw = payload.get("events") or payload.get("Events") or payload.get("data") or []
                rows = (
                    [row for row in raw if isinstance(row, dict)]
                    if isinstance(raw, list)
                    else []
                )
            else:
                continue
            source = names.get(host, "511")
            prefix = host.split(".")[0].replace("www", "cars")[:12]
            if prefix == "cars":
                prefix = host.split(".")[1][:12] if "." in host else "cars"
            for entity in entities_from_cars(rows, prefix=prefix, source=source):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out or None


def entities_from_cars(
    rows: list[dict[str, Any]], *, prefix: str, source: str
) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        entity = _entity_from_cars(row, prefix=prefix, source=source)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_cars(
    row: dict[str, Any], *, prefix: str, source: str
) -> Entity | None:
    loc = row.get("Location") if isinstance(row.get("Location"), dict) else {}
    lat = _num(
        row.get("Latitude"),
        row.get("latitude"),
        row.get("lat"),
        loc.get("Latitude"),
        loc.get("latitude"),
    )
    lon = _num(
        row.get("Longitude"),
        row.get("longitude"),
        row.get("lon"),
        row.get("lng"),
        loc.get("Longitude"),
        loc.get("longitude"),
    )
    if lat is None or lon is None:
        geom = row.get("geography") or row.get("geometry")
        if isinstance(geom, dict):
            lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    eid = str(
        row.get("ID")
        or row.get("Id")
        or row.get("id")
        or row.get("SourceId")
        or row.get("eventId")
        or ""
    ).strip()
    road = str(row.get("RoadwayName") or row.get("road") or row.get("name") or "").strip()
    desc = str(
        row.get("Description")
        or row.get("EventType")
        or row.get("headline")
        or row.get("description")
        or eid
        or road
    ).strip()
    label = desc
    if road and road.casefold() not in label.casefold():
        label = f"{road} {label}" if label else road
    if not eid and not label:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"{prefix}:{eid or label.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source=source,
        freshness="delayed",
        confidence=0.7,
        cite=_CARS_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published 511 event. Not a car. Not a plate.",
        ),
    )


def _fetch_ohgo() -> list[Entity] | None:
    key = earth_secret("ohgo_key", OH_ENV)
    if not key:
        return None
    extra = {"Authorization": f"APIKEY {key}"}
    params = {"page-all": "true"}
    chunks: list[list[Entity] | None] = []
    incidents = _get_json(OH_INCIDENTS, OH_HOST, params=params, extra=extra)
    if isinstance(incidents, dict):
        chunks.append(
            entities_from_ohgo_events(
                _list_rows(incidents, "results"), prefix="oh511", source="OHGO incidents"
            )
            or None
        )
    else:
        chunks.append(None)
    construction = _get_json(OH_CONSTRUCTION, OH_HOST, params=params, extra=extra)
    if isinstance(construction, dict):
        chunks.append(
            entities_from_ohgo_events(
                _list_rows(construction, "results"),
                prefix="oh-wz",
                source="OHGO construction",
            )
            or None
        )
    else:
        chunks.append(None)
    if all(chunk is None for chunk in chunks):
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def entities_from_ohgo_events(
    rows: list[dict[str, Any]], *, prefix: str, source: str
) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        lat = _num(row.get("latitude"), row.get("Latitude"))
        lon = _num(row.get("longitude"), row.get("Longitude"))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            continue
        eid = str(row.get("id") or row.get("Id") or "").strip()
        road = str(row.get("routeName") or row.get("RouteName") or "").strip()
        desc = str(
            row.get("description")
            or row.get("Description")
            or row.get("location")
            or row.get("category")
            or eid
            or road
        ).strip()
        label = desc
        if road and road.casefold() not in label.casefold():
            label = f"{road} {label}" if label else road
        if not eid and not label:
            continue
        kid = f"{prefix}:{eid or label.casefold()[:40]}"
        if kid in seen:
            continue
        seen.add(kid)
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=kid,
                cls="traffic",
                layer="traffic",
                label=label[:80],
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source=source,
                freshness="delayed",
                confidence=0.7,
                cite=_OH_CITE,
                meta={"lat": lat, "lon": lon},
                coverage=Coverage(
                    "incident",
                    "Published OHGO event. Not a car. Not a plate.",
                ),
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _fetch_wsdot() -> list[Entity] | None:
    key = earth_secret("wsdot_access_code", WA_ENV)
    if not key:
        return None
    payload = _get_json(WA_ALERTS, WA_HOST, params={"AccessCode": key})
    rows = _list_rows(payload)
    if not rows:
        return None
    pins = entities_from_wsdot_alerts(rows)
    return pins or None


def _fetch_keyed_cars() -> list[Entity] | None:
    jobs: list[tuple[str, str, str, str]] = []
    for host, name, field, env in _KEYED_CARS:
        key = earth_secret(field, env) if field else earth_cars_key(host)
        if not key:
            continue
        url = f"https://{host}/api/v2/get/event?format=json"
        jobs.append((host, url, name, key))
    if not jobs:
        return None
    any_ok = False
    out: list[Entity] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = [
            pool.submit(_get_json, url, host, params={"key": key})
            for host, url, _name, key in jobs
        ]
        for fut, (host, _url, name, _key) in zip(futs, jobs, strict=True):
            payload = fut.result()
            if payload is None:
                continue
            any_ok = True
            rows = _list_rows(payload, "events", "Events", "data")
            prefix = host.split(".")[0].replace("www", "cars")[:12]
            if prefix == "cars":
                prefix = host.split(".")[1][:12] if "." in host else "cars"
            for entity in entities_from_cars(rows, prefix=prefix, source=name):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out or None


def entities_from_wsdot_alerts(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        start = (
            row.get("StartRoadwayLocation")
            if isinstance(row.get("StartRoadwayLocation"), dict)
            else {}
        )
        lat = _num(start.get("Latitude"), row.get("Latitude"), row.get("latitude"))
        lon = _num(start.get("Longitude"), row.get("Longitude"), row.get("longitude"))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            continue
        eid = str(row.get("AlertID") or row.get("Id") or row.get("id") or "").strip()
        road = str(start.get("RoadName") or row.get("RoadName") or "").strip()
        desc = str(
            row.get("HeadlineDescription")
            or row.get("ExtendedDescription")
            or row.get("EventCategory")
            or eid
            or road
        ).strip()
        label = desc
        if road and road.casefold() not in label.casefold():
            label = f"{road} {label}" if label else road
        if not eid and not label:
            continue
        pos = lla_to_ecef(lat, lon, 0.0)
        kid = f"wa511:{eid or label.casefold()[:40]}"
        if kid in seen:
            continue
        seen.add(kid)
        out.append(
            Entity(
                id=kid,
                cls="traffic",
                layer="traffic",
                label=label[:80],
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="WSDOT alerts",
                freshness="delayed",
                confidence=0.7,
                cite=_WA_CITE,
                meta={"lat": lat, "lon": lon},
                coverage=Coverage(
                    "incident",
                    "Published highway alert. Not a car. Not a plate.",
                ),
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _list_rows(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys or ("alerts", "data", "Alerts"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [row for row in raw if isinstance(row, dict)]
    return []


def _fetch_drivetexas() -> list[Entity] | None:
    key = earth_secret("drivetexas_key", TX_ENV)
    if not key:
        return None
    params = {"key": key}
    chunks: list[list[Entity] | None] = []
    conditions = _get_json(TX_CONDITIONS, TX_HOST, params=params)
    if isinstance(conditions, dict):
        chunks.append(
            entities_from_geojson_incidents(
                conditions, prefix="tx-dt", source="DriveTexas", cite=_TX_CITE
            )
            or None
        )
    else:
        chunks.append(None)
    wzdx = _get_json(TX_WZDX, TX_HOST, params=params)
    if isinstance(wzdx, dict):
        chunks.append(
            entities_from_wzdx(wzdx, prefix="tx-wzdx", source="DriveTexas WZDx") or None
        )
    else:
        chunks.append(None)
    if all(chunk is None for chunk in chunks):
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def _fetch_quebec() -> list[Entity] | None:
    jobs = (
        (QC_EVENTS, "qc511", "Quebec 511 events"),
        (QC_CHANTIERS, "qc-wz", "Quebec 511 construction"),
        (QC_CONDITIONS, "qc-road", "Quebec 511 road conditions"),
    )
    chunks: list[list[Entity] | None] = []
    for url, prefix, source in jobs:
        payload = _get_json(url, QC_HOST)
        if not isinstance(payload, dict):
            chunks.append(None)
            continue
        chunks.append(
            entities_from_geojson_incidents(
                payload, prefix=prefix, source=source, cite=_QC_CITE
            )
            or None
        )
    if all(chunk is None for chunk in chunks):
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def _fetch_autobahn() -> list[Entity] | None:
    listing = _get_json(DE_AUTOBAHN, DE_HOST)
    if not isinstance(listing, dict):
        return None
    roads = listing.get("roads")
    if not isinstance(roads, list) or not roads:
        return None
    jobs: list[tuple[str, str]] = []
    for road in roads:
        name = str(road or "").strip()
        if not name or "/" in name or " " in name or len(name) > 8:
            continue
        jobs.append((f"{DE_AUTOBAHN}/{name}/services/roadworks", "roadworks"))
        jobs.append((f"{DE_AUTOBAHN}/{name}/services/warning", "warning"))
    if not jobs:
        return None
    any_ok = False
    out: list[Entity] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(_get_json, url, DE_HOST) for url, _key in jobs]
        keys = [key for _url, key in jobs]
        for fut, key in zip(futs, keys, strict=True):
            payload = fut.result()
            if not isinstance(payload, dict):
                continue
            any_ok = True
            for entity in entities_from_autobahn(
                payload, key=key, prefix="de-ab", source="Autobahn GmbH"
            ):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out or None


def entities_from_autobahn(
    payload: dict[str, Any], *, key: str, prefix: str, source: str
) -> list[Entity]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_autobahn(row, prefix=prefix, source=source)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_autobahn(
    row: dict[str, Any], *, prefix: str, source: str
) -> Entity | None:
    coord = row.get("coordinate") if isinstance(row.get("coordinate"), dict) else {}
    lat = _num(coord.get("lat"), row.get("lat"))
    lon = _num(coord.get("long"), coord.get("lon"), row.get("long"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    eid = str(row.get("identifier") or row.get("id") or "").strip()
    title = str(row.get("title") or row.get("subtitle") or eid).strip()
    if not eid and not title:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"{prefix}:{eid or title.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=title[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source=source,
        freshness="delayed",
        confidence=0.7,
        cite=_DE_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published autobahn event. Not a car. Not a plate.",
        ),
    )


def _tfl_ll(row: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _num(row.get("latitude") or row.get("lat"))
    lon = _num(row.get("longitude") or row.get("lon") or row.get("lng"))
    if lat is not None and lon is not None:
        return lat, lon
    for key in ("geography", "geometry", "point"):
        geom = row.get(key)
        if not isinstance(geom, dict):
            continue
        coords = geom.get("coordinates")
        if isinstance(coords, list) and coords:
            first = coords[0]
            if geom.get("type") == "Point" and len(coords) >= 2:
                return _num(coords[1]), _num(coords[0])
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                return _num(first[1]), _num(first[0])
    return None, None


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _get_json(
    url: str,
    pin: str,
    params: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> Any:
    from arelis.earth.http import get_json

    headers = {"User-Agent": _UA}
    if extra:
        headers.update(extra)
    return get_json(url, pin, timeout=_TIMEOUT, headers=headers, params=params)
