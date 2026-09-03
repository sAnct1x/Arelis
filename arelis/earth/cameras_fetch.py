"""Camera catalog fetchers and entity builders.

Public imports stay on cameras.py so the ethics docstring and
patchable ``_host_pinned`` / ``fetch_osm_webcams`` live there.

Operator catalogs wherever a public JSON/XML exists, plus OSM webcam
tags on every inhabited continent. Pins only — no still fetch, no stream
URL in meta. Caltrans publishes a look direction; that becomes a
viewshed. Other pose is unknown unless a prior exists. Owned pins come
from secrets the user pasted. Unsecured IP cameras are out. An open
port is not consent. One US city (NYC) is a catalog, not the map.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import httpx
import yaml

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.look import first_url, offer_official, offer_owned
from arelis.earth.secrets import earth_cars_key, earth_secret
from arelis.earth.viewshed import attach_viewshed
from arelis.paths import state_dir

TFL_JAMCAM = "https://api.tfl.gov.uk/Place/Type/JamCam"
TFL_HOST = "api.tfl.gov.uk"
NYC_CAMERAS = "https://webcams.nyctmc.org/api/cameras"
NYC_HOST = "webcams.nyctmc.org"
SG_TRAFFIC = "https://api.data.gov.sg/v1/transport/traffic-images"
SG_HOST = "api.data.gov.sg"
FI_WEATHERCAM = "https://tie.digitraffic.fi/api/weathercam/v1/stations"
FI_HOST = "tie.digitraffic.fi"
HK_CAMERAS = (
    "https://static.data.gov.hk/td/traffic-snapshot-images/"
    "code/Traffic_Camera_Locations_En.xml"
)
HK_HOST = "static.data.gov.hk"
ON_CAMERAS = "https://511on.ca/api/v2/get/cameras?format=json"
ON_HOST = "511on.ca"
# Same CARS camera JSON as Ontario. Hosts already pinned for events,
# plus a few more no-key CARS catalogs.
_CARS_CAMERAS: tuple[tuple[str, str, str, str], ...] = (
    (
        "511.gov.mb.ca",
        "https://511.gov.mb.ca/api/v2/get/cameras?format=json",
        "mb-cam",
        "Manitoba 511 cameras",
    ),
    (
        "511.novascotia.ca",
        "https://511.novascotia.ca/api/v2/get/cameras?format=json",
        "ns-cam",
        "Nova Scotia 511 cameras",
    ),
    (
        "511.alberta.ca",
        "https://511.alberta.ca/api/v2/get/cameras?format=json",
        "ab-cam",
        "Alberta 511 cameras",
    ),
    (
        "hotline.gov.sk.ca",
        "https://hotline.gov.sk.ca/api/v2/get/cameras?format=json",
        "sk-cam",
        "Saskatchewan 511 cameras",
    ),
    (
        "fl511.com",
        "https://fl511.com/api/v2/get/cameras?format=json",
        "fl-cam",
        "Florida 511 cameras",
    ),
    (
        "511ny.org",
        "https://511ny.org/api/v2/get/cameras?format=json",
        "ny-cam",
        "New York 511 cameras",
    ),
    (
        "www.cotrip.org",
        "https://www.cotrip.org/api/v2/get/cameras?format=json",
        "co-cam",
        "COtrip 511 cameras",
    ),
    (
        "511ia.org",
        "https://511ia.org/api/v2/get/cameras?format=json",
        "ia-cam",
        "Iowa 511 cameras",
    ),
    (
        "511mn.org",
        "https://511mn.org/api/v2/get/cameras?format=json",
        "mn-cam",
        "Minnesota 511 cameras",
    ),
    (
        "511ga.org",
        "https://511ga.org/api/v2/get/cameras?format=json",
        "ga-cam",
        "Georgia 511 cameras",
    ),
)
TRIPCHECK = "https://tripcheck.com/Scripts/map/data/cctvinventory.js"
TRIPCHECK_HOST = "tripcheck.com"
MD_CAMERAS = (
    "https://mdgeodata.md.gov/imap/rest/services/Transportation/"
    "MD_TrafficCameras/FeatureServer/0/query"
    "?where=1%3D1&outFields=*&f=geojson&returnGeometry=true"
)
MD_CAM_HOST = "mdgeodata.md.gov"
ND_CAMERAS = "https://travelfiles.dot.nd.gov/geojson_nc/cameras.json"
ND_CAM_HOST = "travelfiles.dot.nd.gov"
AL_CAMERAS = "https://api.algotraffic.com/v4.0/cameras"
AL_HOST = "api.algotraffic.com"
DE_CAMERAS = "https://tmc.deldot.gov/json/videocamera.json"
DE_CAM_HOST = "tmc.deldot.gov"
NZ_CAMERAS = "https://www.journeys.nzta.govt.nz/assets/map-data-cache/cameras.json"
NZ_CAM_HOST = "www.journeys.nzta.govt.nz"
QC_CAMERAS = (
    "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0"
    "&request=GetFeature&typename=ms:infos_cameras&srsname=EPSG:4326&outputformat=geojson"
)
QC_CAM_HOST = "ws.mapserver.transports.gouv.qc.ca"
NSW_CAMERAS = "https://api.transport.nsw.gov.au/v1/live/cameras"
NSW_CAM_HOST = "api.transport.nsw.gov.au"
NSW_ENV = "ARELIS_NSW_KEY"
WA_CAMERAS = (
    "https://wsdot.wa.gov/Traffic/api/HighwayCameras/"
    "HighwayCamerasREST.svc/GetCamerasAsJson"
)
WA_CAM_HOST = "wsdot.wa.gov"
WA_ENV = "ARELIS_WSDOT_ACCESS_CODE"
OH_CAMERAS = "https://publicapi.ohgo.com/api/v1/cameras"
OH_CAM_HOST = "publicapi.ohgo.com"
OH_ENV = "ARELIS_OHGO_KEY"
MO_CAMERAS = (
    "https://mapping.modot.mo.gov/arcgis/rest/services/"
    "TravelerInformation/NWSDATA/MapServer/0/query"
    "?where=1%3D1&outFields=*&f=geojson&returnGeometry=true"
)
MO_CAM_HOST = "mapping.modot.mo.gov"
_MO_CAM_CITE = (
    "MoDOT published camera catalog. Operator GeoJSON. "
    "Position only. No still ingest."
)
# CARS clones that 400 without a developer key. Query is ?key=
# field empty means earth.cars_keys[host].
_KEYED_CARS_CAMERAS: tuple[tuple[str, str, str, str, str], ...] = (
    ("drivenc.gov", "nc-cam", "NCDOT cameras", "drivenc_key", "ARELIS_DRIVENC_KEY"),
    ("udottraffic.utah.gov", "ut-cam", "UDOT cameras", "", ""),
    ("az511.gov", "az-cam", "AZ511 cameras", "", ""),
    ("511.idaho.gov", "id-cam", "ITD cameras", "", ""),
    ("511wi.gov", "wi-cam", "WisDOT cameras", "", ""),
    ("511la.org", "la-cam", "LADOTD cameras", "", ""),
    ("511.alaska.gov", "ak-cam", "Alaska 511 cameras", "", ""),
    ("nvroads.com", "nv-cam", "Nevada 511 cameras", "", ""),
    ("ctroads.org", "ct-cam", "CTDOT cameras", "", ""),
    ("511.nebraska.gov", "ne-cam", "Nebraska 511 cameras", "", ""),
)
CALTRANS_HOST = "cwwp2.dot.ca.gov"
CALTRANS_CCTV = tuple(
    f"https://cwwp2.dot.ca.gov/data/d{d}/cctv/cctvStatusD{d:02d}.json"
    for d in range(1, 13)
)
SECRETS_PATH = state_dir() / "secrets.yaml"
_UA = f"Arelis/{__version__} (+{__source_url__})"

_TIMEOUT = 10.0
_CAP = 5000
_TFL_CITE = (
    "TfL JamCam published position. Operator catalog, not a crawl. "
    "No video ingest. Pose unknown unless a viewshed prior exists. "
    "Unpublished cameras are holes. Unsecured IP streams are out."
)
_CAL_CITE = (
    "Caltrans published CCTV position and look direction. Operator catalog. "
    "No still ingest, no stream URL. Occluders not meshed."
)
_NYC_CITE = (
    "NYC DOT public traffic-camera catalog. Same JSON the operator's map "
    "uses. Position only. No still ingest. One city, not the globe."
)
_SG_CITE = (
    "Singapore LTA traffic-camera positions (data.gov.sg). Operator catalog. "
    "Position only. No still ingest."
)
_FI_CITE = (
    "Fintraffic road weather cameras. Finnish road network. CC BY 4.0. "
    "Position only. No still ingest."
)
_HK_CITE = (
    "Hong Kong Transport Department camera locations. Operator XML. "
    "Position only. No still ingest."
)
_ON_CITE = (
    "Ontario 511 published camera positions. Operator catalog. "
    "Position only. No still ingest."
)
_CARS_CAM_CITE = (
    "Published 511 camera catalog. Operator JSON. Position only. "
    "No still ingest."
)
_TRIP_CITE = (
    "ODOT TripCheck CCTV inventory. Operator catalog. "
    "Position only. No still ingest."
)
_MD_CAM_CITE = (
    "SHA traffic-camera GeoJSON. Operator catalog. "
    "Position only. No still ingest."
)
_ND_CAM_CITE = (
    "NDDOT camera GeoJSON. Operator catalog. "
    "Position only. No still ingest."
)
_AL_CITE = (
    "ALGO / ALDOT published camera catalog. Operator JSON. "
    "Position only. No still ingest."
)
_DE_CAM_CITE = (
    "DelDOT published camera catalog. Operator JSON. "
    "Position only. No still ingest."
)
_NZ_CAM_CITE = (
    "Waka Kotahi / NZTA published camera catalog. Operator GeoJSON. "
    "Position only. No still ingest."
)
_QC_CAM_CITE = (
    "Quebec 511 / MTMD published camera locations. Operator GeoJSON. "
    "Position only. No still ingest."
)
_NSW_CAM_CITE = (
    "NSW Live Traffic published camera catalog. Operator GeoJSON. "
    "Position only. No still ingest."
)
_WA_CAM_CITE = (
    "WSDOT published highway-camera catalog. Operator JSON. "
    "Position only. No still ingest."
)
_KEYED_CARS_CAM_CITE = (
    "Published 511 camera catalog (developer key). Operator JSON. "
    "Position only. No still ingest."
)
_OH_CAM_CITE = (
    "OHGO / ODOT published camera catalog. Operator JSON. "
    "Position only. No still ingest."
)
_OWNED_CITE = (
    "Owned camera pin from secrets. Look-from plays the stream you pasted. "
    "Stream URL is not stored on the pin."
)
_DIR_HEADING: dict[str, float] = {
    "n": 0.0,
    "north": 0.0,
    "nb": 0.0,
    "northbound": 0.0,
    "ne": 45.0,
    "northeast": 45.0,
    "e": 90.0,
    "east": 90.0,
    "eb": 90.0,
    "eastbound": 90.0,
    "se": 135.0,
    "southeast": 135.0,
    "s": 180.0,
    "south": 180.0,
    "sb": 180.0,
    "southbound": 180.0,
    "sw": 225.0,
    "southwest": 225.0,
    "w": 270.0,
    "west": 270.0,
    "wb": 270.0,
    "westbound": 270.0,
    "nw": 315.0,
    "northwest": 315.0,
}


def _osm_webcams():
    from arelis.earth import cameras as cam

    return cam.fetch_osm_webcams()


def fetch_cameras() -> list[Entity] | None:
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [
            pool.submit(_fetch_tfl),
            pool.submit(_fetch_caltrans),
            pool.submit(_fetch_nyc),
            pool.submit(_fetch_singapore),
            pool.submit(_fetch_finland),
            pool.submit(_fetch_hongkong),
            pool.submit(_fetch_ontario),
            pool.submit(_fetch_cars_cameras),
            pool.submit(_fetch_tripcheck),
            pool.submit(_fetch_md_cameras),
            pool.submit(_fetch_nd_cameras),
            pool.submit(_fetch_algo),
            pool.submit(_fetch_deldot),
            pool.submit(_fetch_nz_cameras),
            pool.submit(_fetch_quebec_cameras),
            pool.submit(_fetch_nsw_cameras),
            pool.submit(_fetch_wsdot_cameras),
            pool.submit(_fetch_ohgo_cameras),
            pool.submit(_fetch_keyed_cars_cameras),
            pool.submit(_fetch_modot_cameras),
            pool.submit(_osm_webcams),
        ]
        for fut in as_completed(futs):
            chunks.append(fut.result())
    if all(chunk is None for chunk in chunks):
        return None
    pins: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            pins.append(entity)
            if len(pins) >= _CAP:
                return pins
    if not pins:
        return None
    for extra in _bundled_without_live(seen) + load_owned():
        if extra.id not in seen:
            pins.append(extra)
            seen.add(extra.id)
        if len(pins) >= _CAP:
            break
    return pins[:_CAP]


def load_owned(path: Path | None = None) -> list[Entity]:
    """Pins the user pasted. No RTSP fetch. Empty if none."""
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(raw, dict):
        return []
    block = raw.get("earth")
    if not isinstance(block, dict):
        return []
    rows: list[Any] = []
    local = block.get("local_camera")
    if isinstance(local, dict):
        rows.append(local if local.get("id") else {**local, "id": "local"})
    cams = block.get("cameras")
    if isinstance(cams, list):
        rows.extend(row for row in cams if isinstance(row, dict))
    out: list[Entity] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _owned_from_row(row)
        if entity is not None:
            out.append(attach_viewshed(entity))
    return out


def entities_from_places(rows: list[dict[str, Any]]) -> list[Entity]:
    return _collect(_entity_from_tfl, rows)


def entities_from_nyc(rows: list[dict[str, Any]]) -> list[Entity]:
    return _collect(_entity_from_nyc, rows)


def entities_from_singapore(payload: dict[str, Any]) -> list[Entity]:
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return []
    first = items[0] if isinstance(items[0], dict) else {}
    rows = first.get("cameras")
    if not isinstance(rows, list):
        return []
    return _collect(_entity_from_sg, [r for r in rows if isinstance(r, dict)])


def entities_from_finland(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return _collect(_entity_from_fi, [r for r in rows if isinstance(r, dict)])


def entities_from_hk_xml(text: str) -> list[Entity]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for el in root.findall("image"):
        row = {child.tag: (child.text or "") for child in el}
        entity = _entity_from_hk(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(attach_viewshed(entity))
        if len(out) >= _CAP:
            break
    return out


def entities_from_caltrans(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    return _collect(_entity_from_caltrans, [r for r in rows if isinstance(r, dict)])


def _collect(
    builder: Any, rows: list[dict[str, Any]]
) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        entity = builder(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(attach_viewshed(entity))
        if len(out) >= _CAP:
            break
    return out


def _entity_from_tfl(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))
    if not _ok_ll(lat, lon):
        return None
    pid = str(row.get("id") or "").strip()
    name = str(row.get("commonName") or row.get("name") or "").strip()
    if not pid and not name:
        return None
    eid = f"tfl:{pid or name.casefold()[:48]}"
    pos = lla_to_ecef(lat, lon, 12.0)
    offer_official(eid, *_tfl_media(row))
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=name or pid,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="TfL JamCam",
        freshness="reconstructed",
        confidence=0.8,
        cite=_TFL_CITE,
        meta={"lat": lat, "lon": lon, "place_id": pid},
        coverage=Coverage(
            "pin",
            "Published position. Pose unknown. No video. Occluders not meshed.",
        ),
        pii="none",
    )


def _entity_from_nyc(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("latitude"), row.get("lat"))
    lon = _num(row.get("longitude"), row.get("lon"), row.get("lng"))
    if not _ok_ll(lat, lon):
        return None
    cid = str(row.get("id") or "").strip()
    name = str(row.get("name") or "").strip()
    if not cid and not name:
        return None
    eid = f"nyc:{cid or name.casefold()[:48]}"
    pos = lla_to_ecef(lat, lon, 12.0)
    offer_official(
        eid,
        first_url(row.get("imageUrl"), row.get("image_url"), row.get("url")),
    )
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=(name or cid)[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="NYC DOT cameras",
        freshness="reconstructed",
        confidence=0.8,
        cite=_NYC_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Operator public map JSON. No video. Pose unknown.",
        ),
        pii="none",
    )


def _entity_from_sg(row: dict[str, Any]) -> Entity | None:
    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
    lat = _num(loc.get("latitude"), row.get("latitude"))
    lon = _num(loc.get("longitude"), row.get("longitude"))
    if not _ok_ll(lat, lon):
        return None
    cid = str(row.get("camera_id") or row.get("id") or "").strip()
    if not cid:
        return None
    eid = f"sg:{cid}"
    pos = lla_to_ecef(lat, lon, 12.0)
    offer_official(eid, first_url(row.get("image"), row.get("image_url")))
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=f"Singapore {cid}",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Singapore LTA",
        freshness="reconstructed",
        confidence=0.8,
        cite=_SG_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Operator catalog. No video. Pose unknown.",
        ),
        pii="none",
    )


def _entity_from_fi(feat: dict[str, Any]) -> Entity | None:
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
    lon = _num(coords[0] if len(coords) > 0 else None)
    lat = _num(coords[1] if len(coords) > 1 else None)
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    if not _ok_ll(lat, lon):
        return None
    cid = str(props.get("id") or feat.get("id") or "").strip()
    name = str(props.get("name") or cid).strip()
    if not cid:
        return None
    eid = f"fi:{cid}"
    pos = lla_to_ecef(lat, lon, 12.0)
    offer_official(eid, *_finland_media(feat, props))
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Fintraffic weathercam",
        freshness="reconstructed",
        confidence=0.8,
        cite=_FI_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Operator catalog. No video. Pose unknown.",
        ),
        pii="none",
    )


def _entity_from_hk(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("latitude"))
    lon = _num(row.get("longitude"))
    if not _ok_ll(lat, lon):
        return None
    cid = str(row.get("key") or "").strip()
    name = str(row.get("description") or cid).strip()
    if not cid:
        return None
    eid = f"hk:{cid}"
    pos = lla_to_ecef(lat, lon, 12.0)
    offer_official(eid, first_url(row.get("url"), row.get("imageUrl")))
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Hong Kong TD",
        freshness="reconstructed",
        confidence=0.8,
        cite=_HK_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Operator catalog. No video. Pose unknown.",
        ),
        pii="none",
    )


def _entity_from_caltrans(row: dict[str, Any]) -> Entity | None:
    cctv = row.get("cctv") if isinstance(row.get("cctv"), dict) else row
    loc = cctv.get("location") if isinstance(cctv.get("location"), dict) else {}
    lat = _num(loc.get("latitude"))
    lon = _num(loc.get("longitude"))
    if not _ok_ll(lat, lon):
        return None
    idx = str(cctv.get("index") or loc.get("locationName") or "").strip()
    name = str(loc.get("locationName") or idx).strip()
    route = str(loc.get("route") or "").strip()
    district = str(loc.get("district") or "").strip()
    if not idx and not name:
        return None
    heading = _heading(str(loc.get("direction") or ""))
    label = name if not route else f"{name} {route}"
    eid = f"caltrans:{district or 'x'}:{idx or name.casefold()[:32]}"
    pos = lla_to_ecef(lat, lon, 12.0)
    image = cctv.get("imageData") if isinstance(cctv.get("imageData"), dict) else {}
    offer_official(
        eid,
        first_url(
            image.get("streamingVideoURL"),
            image.get("currentImageURL"),
            cctv.get("streamingVideoURL"),
            cctv.get("currentImageURL"),
        ),
    )
    meta: dict[str, Any] = {"lat": lat, "lon": lon, "route": route}
    if heading is not None:
        meta["heading_deg"] = heading
        meta["fov_deg"] = 55.0
        meta["range_m"] = 300.0
        meta["pose"] = "catalog"
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Caltrans CCTV",
        freshness="reconstructed",
        confidence=0.8,
        cite=_CAL_CITE,
        meta=meta,
        coverage=Coverage(
            "viewshed" if heading is not None else "pin",
            "Operator catalog. No video. Occluders not meshed.",
        ),
        pii="none",
    )


def _owned_from_row(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat"), row.get("latitude"))
    lon = _num(row.get("lon"), row.get("longitude"))
    if not _ok_ll(lat, lon):
        return None
    cid = str(row.get("id") or row.get("name") or "local").strip()
    if not cid:
        return None
    heading = _num(row.get("heading_deg"))
    pos = lla_to_ecef(lat, lon, 12.0)
    device = row.get("device")
    if device is None:
        device = row.get("index") or row.get("device_index")
    offer_owned(
        f"owned:{cid.casefold()[:48]}",
        rtsp=str(row.get("rtsp") or row.get("url") or "").strip(),
        device=device,
    )
    meta: dict[str, Any] = {"lat": lat, "lon": lon}
    if heading is not None:
        meta["heading_deg"] = heading
        meta["fov_deg"] = float(row.get("fov_deg") or 70.0)
        meta["range_m"] = float(row.get("range_m") or 200.0)
        meta["pose"] = "owned"
    return Entity(
        id=f"owned:{cid.casefold()[:48]}",
        cls="camera",
        layer="cameras",
        label=str(row.get("name") or cid),
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="owned pin",
        freshness="reconstructed",
        confidence=0.95,
        cite=_OWNED_CITE,
        meta=meta,
        coverage=Coverage(
            "owned",
            "Operator-owned pin. Look-from plays the stream you pasted.",
        ),
        pii="none",
    )


def _bundled_without_live(seen: set[str]) -> list[Entity]:
    from arelis.earth.simulate import CAMERAS, _camera_entity

    out: list[Entity] = []
    for row in CAMERAS:
        cid = str(row[0])
        if cid.startswith(("tfl:", "caltrans:", "nyc:", "sg:", "fi:", "hk:")):
            continue
        if cid in seen:
            continue
        out.append(attach_viewshed(_camera_entity(*row)))
    return out


def _tfl_media(row: dict[str, Any]) -> tuple[str, ...]:
    props = row.get("additionalProperties")
    video = ""
    image = ""
    if isinstance(props, list):
        for prop in props:
            if not isinstance(prop, dict):
                continue
            key = str(prop.get("key") or "").casefold()
            val = str(prop.get("value") or "").strip()
            if not val:
                continue
            if key in {"videourl", "video_url"}:
                video = val
            elif key in {"imageurl", "image_url"}:
                image = val
    extra = first_url(row.get("url"))
    return (video, image, extra)


def _finland_media(feat: dict[str, Any], props: dict[str, Any]) -> tuple[str, ...]:
    urls: list[str] = []
    for key in ("imageUrl", "imageUrlNearest", "image_url"):
        got = first_url(props.get(key))
        if got:
            urls.append(got)
    presets = props.get("cameraPresets") or props.get("presets") or feat.get("cameraPresets")
    if isinstance(presets, list):
        for preset in presets:
            if not isinstance(preset, dict):
                continue
            got = first_url(
                preset.get("imageUrl"),
                preset.get("imageUrlNearest"),
                preset.get("url"),
            )
            if got:
                urls.append(got)
    return tuple(urls)


def _media_url(*values: Any) -> str:
    """First http(s) URL that is not an HTML player page."""
    text = first_url(*values)
    if not text:
        return ""
    low = text.lower()
    if any(token in low for token in (".html", ".htm", "fenetrevideo")):
        return ""
    return text


def _cars_media(row: dict[str, Any]) -> tuple[str, ...]:
    urls: list[str] = []
    for key in ("VideoUrl", "Url", "ImageUrl", "url", "imageUrl"):
        got = _media_url(row.get(key))
        if got:
            urls.append(got)
    views = row.get("Views") or row.get("views")
    if isinstance(views, list):
        for view in views:
            if not isinstance(view, dict):
                continue
            for key in ("VideoUrl", "Url", "ImageUrl", "url"):
                got = _media_url(view.get(key))
                if got:
                    urls.append(got)
    return tuple(urls)


def _heading(raw: str) -> float | None:
    key = " ".join(raw.strip().lower().split())
    if not key:
        return None
    if key in _DIR_HEADING:
        return _DIR_HEADING[key]
    first = key.split()[0]
    return _DIR_HEADING.get(first)


def _ok_ll(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return False
    return abs(lat) <= 90.0 and abs(lon) <= 180.0


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _host_pinned(host: str | None, pin: str) -> bool:
    from arelis.earth import cameras as cam

    return cam._host_pinned(host, pin)


def entities_from_cars_cameras(
    rows: list[dict[str, Any]], *, prefix: str, source: str, cite: str
) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        loc = row.get("Location") if isinstance(row.get("Location"), dict) else {}
        lat = _num(
            row.get("Latitude"),
            row.get("latitude"),
            row.get("lat"),
            loc.get("Latitude"),
        )
        lon = _num(
            row.get("Longitude"),
            row.get("longitude"),
            row.get("lon"),
            loc.get("Longitude"),
        )
        if not _ok_ll(lat, lon):
            continue
        cid = str(
            row.get("ID") or row.get("Id") or row.get("id") or row.get("SourceId") or ""
        ).strip()
        name = str(
            row.get("Description")
            or row.get("Name")
            or row.get("name")
            or row.get("RoadwayName")
            or cid
        ).strip()
        if not cid and not name:
            continue
        eid = f"{prefix}:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        pos = lla_to_ecef(lat, lon, 12.0)
        offer_official(eid, *_cars_media(row))
        out.append(
            attach_viewshed(
                Entity(
                    id=eid,
                    cls="camera",
                    layer="cameras",
                    label=(name or cid)[:80],
                    x=pos[0],
                    y=pos[1],
                    z=pos[2],
                    source=source,
                    freshness="reconstructed",
                    confidence=0.75,
                    cite=cite,
                    meta={"lat": lat, "lon": lon},
                    coverage=Coverage(
                        "pin",
                        "Operator catalog. No video. Pose unknown.",
                    ),
                    pii="none",
                )
            )
        )
        if len(out) >= _CAP:
            break
    return out


def entities_from_tripcheck(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
        geom = row.get("geometry") if isinstance(row.get("geometry"), dict) else {}
        lat = _num(
            attrs.get("LATITUDE"),
            attrs.get("Latitude"),
            attrs.get("lat"),
            geom.get("y"),
        )
        lon = _num(
            attrs.get("LONGITUDE"),
            attrs.get("Longitude"),
            attrs.get("lon"),
            geom.get("x"),
        )
        if not _ok_ll(lat, lon):
            continue
        cid = str(
            attrs.get("CAMERAID")
            or attrs.get("CAMERA_ID")
            or attrs.get("OBJECTID")
            or row.get("id")
            or ""
        ).strip()
        name = str(attrs.get("NAME") or attrs.get("TITLE") or attrs.get("LOCATION") or cid).strip()
        if not cid and not name:
            continue
        eid = f"odot:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        pos = lla_to_ecef(lat, lon, 12.0)
        offer_official(
            eid,
            first_url(
                attrs.get("VIDEOURL"),
                attrs.get("IMAGEURL"),
                attrs.get("URL"),
                attrs.get("url"),
            ),
        )
        out.append(
            attach_viewshed(
                Entity(
                    id=eid,
                    cls="camera",
                    layer="cameras",
                    label=(name or cid)[:80],
                    x=pos[0],
                    y=pos[1],
                    z=pos[2],
                    source="ODOT TripCheck",
                    freshness="reconstructed",
                    confidence=0.75,
                    cite=_TRIP_CITE,
                    meta={"lat": lat, "lon": lon},
                    coverage=Coverage(
                        "pin",
                        "Operator catalog. No video. Pose unknown.",
                    ),
                    pii="none",
                )
            )
        )
        if len(out) >= _CAP:
            break
    return out


def entities_from_geojson_cameras(
    payload: dict[str, Any], *, prefix: str, source: str, cite: str
) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for feat in rows:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
        geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
        coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
        lon = _num(coords[0] if len(coords) > 0 else None)
        lat = _num(coords[1] if len(coords) > 1 else None)
        if not _ok_ll(lat, lon):
            lat = _num(
                props.get("lat")
                or props.get("latitude")
                or props.get("LATITUDE")
                or props.get("Y")
            )
            lon = _num(
                props.get("lon")
                or props.get("longitude")
                or props.get("LONGITUDE")
                or props.get("X")
            )
        if not _ok_ll(lat, lon):
            continue
        cid = str(
            props.get("id")
            or props.get("CAM_ID")
            or props.get("IDEcamera")
            or props.get("NumeroCamera")
            or props.get("CAMERAID")
            or props.get("OBJECTID")
            or feat.get("id")
            or ""
        ).strip()
        name = str(
            props.get("name")
            or props.get("Name")
            or props.get("NAME")
            or props.get("title")
            or props.get("DESCRIPTION")
            or props.get("DescriptionLocalisationEn")
            or props.get("DescriptionLocalisationFr")
            or props.get("LOCATION")
            or props.get("description")
            or cid
        ).strip()
        if not cid and not name:
            continue
        eid = f"{prefix}:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        pos = lla_to_ecef(lat, lon, 12.0)
        offer_official(
            eid,
            _media_url(
                props.get("VideoUrl"),
                props.get("videoUrl"),
                props.get("ImageUrl"),
                props.get("imageUrl"),
                props.get("href"),
                props.get("view"),
                props.get("snapshotImageUrl"),
                props.get("url"),
                props.get("URL"),
                props.get("URL1"),
                props.get("URL2"),
            ),
        )
        out.append(
            attach_viewshed(
                Entity(
                    id=eid,
                    cls="camera",
                    layer="cameras",
                    label=(name or cid)[:80],
                    x=pos[0],
                    y=pos[1],
                    z=pos[2],
                    source=source,
                    freshness="reconstructed",
                    confidence=0.75,
                    cite=cite,
                    meta={"lat": lat, "lon": lon},
                    coverage=Coverage(
                        "pin",
                        "Operator catalog. No video. Pose unknown.",
                    ),
                    pii="none",
                )
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _fetch_cars_cameras() -> list[Entity] | None:
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=len(_CARS_CAMERAS)) as pool:
        futs = [
            pool.submit(_get_json, url, host) for host, url, _prefix, _source in _CARS_CAMERAS
        ]
        meta = [(prefix, source) for _host, _url, prefix, source in _CARS_CAMERAS]
        for fut, (prefix, source) in zip(futs, meta, strict=True):
            payload = fut.result()
            if isinstance(payload, list):
                rows = [row for row in payload if isinstance(row, dict)]
            elif isinstance(payload, dict):
                raw = payload.get("cameras") or payload.get("data") or []
                rows = (
                    [row for row in raw if isinstance(row, dict)]
                    if isinstance(raw, list)
                    else []
                )
            else:
                chunks.append(None)
                continue
            pins = entities_from_cars_cameras(
                rows, prefix=prefix, source=source, cite=_CARS_CAM_CITE
            )
            chunks.append(pins or None)
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


def _fetch_ontario() -> list[Entity] | None:
    payload = _get_json(ON_CAMERAS, ON_HOST)
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        raw = payload.get("cameras") or payload.get("data") or []
        rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    else:
        return None
    pins = entities_from_cars_cameras(
        rows, prefix="on-cam", source="Ontario 511 cameras", cite=_ON_CITE
    )
    return pins or None


def _fetch_tripcheck() -> list[Entity] | None:
    text = _get_text(TRIPCHECK, TRIPCHECK_HOST)
    if text is None:
        return None
    payload = _js_object(text)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_tripcheck(payload)
    return pins or None


def _js_object(text: str) -> Any:
    raw = (text or "").strip()
    if raw.startswith("var ") or raw.startswith("const ") or raw.startswith("let "):
        eq = raw.find("=")
        if eq >= 0:
            raw = raw[eq + 1 :].strip()
        raw = raw.rstrip(";").strip()
    try:
        import json

        return json.loads(raw)
    except Exception:
        return None


def _fetch_md_cameras() -> list[Entity] | None:
    payload = _get_json(MD_CAMERAS, MD_CAM_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_cameras(
        payload, prefix="md-cam", source="SHA cameras", cite=_MD_CAM_CITE
    )
    return pins or None


def _fetch_nd_cameras() -> list[Entity] | None:
    payload = _get_json(ND_CAMERAS, ND_CAM_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_cameras(
        payload, prefix="nd-cam", source="NDDOT cameras", cite=_ND_CAM_CITE
    )
    return pins or None


def _fetch_modot_cameras() -> list[Entity] | None:
    payload = _get_json(MO_CAMERAS, MO_CAM_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_cameras(
        payload, prefix="mo-cam", source="MoDOT cameras", cite=_MO_CAM_CITE
    )
    return pins or None


def _fetch_algo() -> list[Entity] | None:
    payload = _get_json(AL_CAMERAS, AL_HOST)
    if not isinstance(payload, list):
        return None
    pins = entities_from_algo([row for row in payload if isinstance(row, dict)])
    return pins or None


def entities_from_algo(rows: list[dict[str, Any]]) -> list[Entity]:
    return _collect(_entity_from_algo, rows)


def _entity_from_algo(row: dict[str, Any]) -> Entity | None:
    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
    lat = _num(loc.get("latitude"), row.get("latitude"))
    lon = _num(loc.get("longitude"), row.get("longitude"))
    if not _ok_ll(lat, lon):
        return None
    cid = str(row.get("id") or "").strip()
    route = str(loc.get("displayRouteDesignator") or loc.get("routeDesignator") or "").strip()
    cross = str(loc.get("displayCrossStreet") or loc.get("crossStreet") or "").strip()
    name = " ".join(part for part in (route, cross) if part) or cid
    if not cid and not name:
        return None
    eid = f"al-cam:{cid or name.casefold()[:40]}"
    pos = lla_to_ecef(lat, lon, 12.0)
    play = row.get("playbackUrls") if isinstance(row.get("playbackUrls"), dict) else {}
    offer_official(
        eid,
        _media_url(play.get("hls"), row.get("snapshotImageUrl"), row.get("mapImageUrl")),
    )
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="ALGO cameras",
        freshness="reconstructed",
        confidence=0.75,
        cite=_AL_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Operator catalog. No video. Pose unknown.",
        ),
        pii="none",
    )


def _fetch_deldot() -> list[Entity] | None:
    payload = _get_json(DE_CAMERAS, DE_CAM_HOST)
    if not isinstance(payload, dict):
        return None
    raw = payload.get("videoCameras") or payload.get("cameras") or []
    if not isinstance(raw, list):
        return None
    pins = entities_from_deldot([row for row in raw if isinstance(row, dict)])
    return pins or None


def entities_from_deldot(rows: list[dict[str, Any]]) -> list[Entity]:
    return _collect(_entity_from_deldot, rows)


def _entity_from_deldot(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat"), row.get("latitude"))
    lon = _num(row.get("lon"), row.get("lng"), row.get("longitude"))
    if not _ok_ll(lat, lon):
        return None
    cid = str(row.get("id") or "").strip()
    name = str(row.get("title") or row.get("name") or cid).strip()
    if not cid and not name:
        return None
    eid = f"de-cam:{cid or name.casefold()[:40]}"
    pos = lla_to_ecef(lat, lon, 12.0)
    urls = row.get("urls") if isinstance(row.get("urls"), dict) else {}
    offer_official(
        eid,
        _media_url(
            urls.get("m3u8s"),
            urls.get("m3u8"),
            row.get("imageUrl"),
            row.get("url"),
        ),
    )
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="DelDOT cameras",
        freshness="reconstructed",
        confidence=0.75,
        cite=_DE_CAM_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Operator catalog. No video. Pose unknown.",
        ),
        pii="none",
    )


def _fetch_nz_cameras() -> list[Entity] | None:
    payload = _get_json(NZ_CAMERAS, NZ_CAM_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_cameras(
        payload, prefix="nz-cam", source="NZTA cameras", cite=_NZ_CAM_CITE
    )
    return pins or None


def _fetch_nsw_cameras() -> list[Entity] | None:
    key = earth_secret("nsw_key", NSW_ENV)
    if not key:
        return None
    payload = _get_json(
        NSW_CAMERAS,
        NSW_CAM_HOST,
        extra={"Authorization": f"apikey {key}", "Accept": "application/json"},
    )
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_cameras(
        payload, prefix="nsw-cam", source="NSW Live Traffic cameras", cite=_NSW_CAM_CITE
    )
    return pins or None


def _fetch_ohgo_cameras() -> list[Entity] | None:
    key = earth_secret("ohgo_key", OH_ENV)
    if not key:
        return None
    payload = _get_json(
        OH_CAMERAS,
        OH_CAM_HOST,
        params={"page-all": "true"},
        extra={"Authorization": f"APIKEY {key}"},
    )
    if not isinstance(payload, dict):
        return None
    rows = _list_rows(payload, "results")
    if not rows:
        return None
    pins = entities_from_ohgo_cameras(rows)
    return pins or None


def entities_from_ohgo_cameras(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        lat = _num(row.get("latitude"), row.get("Latitude"))
        lon = _num(row.get("longitude"), row.get("Longitude"))
        if not _ok_ll(lat, lon):
            continue
        cid = str(row.get("id") or row.get("Id") or "").strip()
        name = str(
            row.get("location") or row.get("Location") or row.get("description") or cid
        ).strip()
        if not cid and not name:
            continue
        eid = f"oh-cam:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        views = row.get("cameraViews") or row.get("CameraViews") or []
        media: list[str] = []
        heading = None
        if isinstance(views, list):
            for view in views:
                if not isinstance(view, dict):
                    continue
                media.append(_media_url(view.get("largeUrl"), view.get("LargeUrl")))
                media.append(_media_url(view.get("smallUrl"), view.get("SmallUrl")))
                if heading is None:
                    heading = _heading(str(view.get("direction") or view.get("Direction") or ""))
        offer_official(eid, *media)
        pos = lla_to_ecef(lat, lon, 12.0)
        meta: dict[str, Any] = {"lat": lat, "lon": lon}
        if heading is not None:
            meta["heading_deg"] = heading
        out.append(
            attach_viewshed(
                Entity(
                    id=eid,
                    cls="camera",
                    layer="cameras",
                    label=(name or cid)[:80],
                    x=pos[0],
                    y=pos[1],
                    z=pos[2],
                    source="OHGO cameras",
                    freshness="reconstructed",
                    confidence=0.8,
                    cite=_OH_CAM_CITE,
                    meta=meta,
                    coverage=Coverage(
                        "viewshed" if heading is not None else "pin",
                        "Operator catalog. Published look direction."
                        if heading is not None
                        else "Operator catalog. No video. Pose unknown.",
                    ),
                    pii="none",
                )
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _fetch_wsdot_cameras() -> list[Entity] | None:
    key = earth_secret("wsdot_access_code", WA_ENV)
    if not key:
        return None
    payload = _get_json(WA_CAMERAS, WA_CAM_HOST, params={"AccessCode": key})
    rows = _list_rows(payload)
    if not rows:
        return None
    pins = entities_from_wsdot_cameras(rows)
    return pins or None


def _fetch_keyed_cars_cameras() -> list[Entity] | None:
    jobs: list[tuple[str, str, str, str, str]] = []
    for host, prefix, source, field, env in _KEYED_CARS_CAMERAS:
        key = earth_secret(field, env) if field else earth_cars_key(host)
        if not key:
            continue
        url = f"https://{host}/api/v2/get/cameras?format=json"
        jobs.append((host, url, prefix, source, key))
    if not jobs:
        return None
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = [
            pool.submit(_get_json, url, host, params={"key": key})
            for host, url, _prefix, _source, key in jobs
        ]
        for fut, (_host, _url, prefix, source, _key) in zip(futs, jobs, strict=True):
            payload = fut.result()
            rows = _list_rows(payload, "cameras", "data")
            if not rows:
                chunks.append(None)
                continue
            chunks.append(
                entities_from_cars_cameras(
                    rows, prefix=prefix, source=source, cite=_KEYED_CARS_CAM_CITE
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


def entities_from_wsdot_cameras(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        loc = row.get("CameraLocation") if isinstance(row.get("CameraLocation"), dict) else {}
        lat = _num(loc.get("Latitude"), row.get("Latitude"), row.get("latitude"))
        lon = _num(loc.get("Longitude"), row.get("Longitude"), row.get("longitude"))
        if not _ok_ll(lat, lon):
            continue
        cid = str(row.get("CameraID") or row.get("Id") or row.get("id") or "").strip()
        name = str(
            row.get("Title") or loc.get("Description") or row.get("Description") or cid
        ).strip()
        if not cid and not name:
            continue
        eid = f"wa-cam:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        heading = _heading(str(loc.get("Direction") or row.get("Direction") or ""))
        pos = lla_to_ecef(lat, lon, 12.0)
        offer_official(eid, _media_url(row.get("ImageURL"), row.get("ImageUrl")))
        meta: dict[str, Any] = {"lat": lat, "lon": lon}
        if heading is not None:
            meta["heading_deg"] = heading
        out.append(
            attach_viewshed(
                Entity(
                    id=eid,
                    cls="camera",
                    layer="cameras",
                    label=(name or cid)[:80],
                    x=pos[0],
                    y=pos[1],
                    z=pos[2],
                    source="WSDOT cameras",
                    freshness="reconstructed",
                    confidence=0.8,
                    cite=_WA_CAM_CITE,
                    meta=meta,
                    coverage=Coverage(
                        "viewshed" if heading is not None else "pin",
                        "Operator catalog. No video. Pose unknown."
                        if heading is None
                        else "Operator catalog. Published look direction.",
                    ),
                    pii="none",
                )
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _list_rows(payload: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys or ("cameras", "data", "Cameras"):
            raw = payload.get(key)
            if isinstance(raw, list):
                return [row for row in raw if isinstance(row, dict)]
    return []


def _fetch_quebec_cameras() -> list[Entity] | None:
    payload = _get_json(QC_CAMERAS, QC_CAM_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_geojson_cameras(
        payload, prefix="qc-cam", source="Quebec 511 cameras", cite=_QC_CAM_CITE
    )
    return pins or None


def _fetch_tfl() -> list[Entity] | None:
    places = _get_json(TFL_JAMCAM, TFL_HOST)
    if not isinstance(places, list):
        return None
    pins = entities_from_places([row for row in places if isinstance(row, dict)])
    return pins or None


def _fetch_caltrans() -> list[Entity] | None:
    out: list[Entity] = []
    seen: set[str] = set()
    any_ok = False
    for payload in _fetch_many_json(CALTRANS_CCTV, CALTRANS_HOST):
        if not isinstance(payload, dict):
            continue
        any_ok = True
        for entity in entities_from_caltrans(payload):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    if not any_ok:
        return None
    return out


def _fetch_nyc() -> list[Entity] | None:
    payload = _get_json(NYC_CAMERAS, NYC_HOST)
    if isinstance(payload, list):
        rows = [row for row in payload if isinstance(row, dict)]
    elif isinstance(payload, dict):
        raw = payload.get("data") or payload.get("cameras") or []
        rows = [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []
    else:
        return None
    pins = entities_from_nyc(rows)
    return pins or None


def _fetch_singapore() -> list[Entity] | None:
    payload = _get_json(SG_TRAFFIC, SG_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_singapore(payload)
    return pins or None


def _fetch_finland() -> list[Entity] | None:
    payload = _get_json(
        FI_WEATHERCAM,
        FI_HOST,
        extra={"Digitraffic-User": _UA, "Accept-Encoding": "gzip"},
    )
    if not isinstance(payload, dict):
        return None
    pins = entities_from_finland(payload)
    return pins or None


def _fetch_hongkong() -> list[Entity] | None:
    text = _get_text(HK_CAMERAS, HK_HOST)
    if text is None:
        return None
    pins = entities_from_hk_xml(text)
    return pins or None


def _fetch_many_json(urls: tuple[str, ...], pin: str) -> list[Any]:
    found: list[Any] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_get_json, url, pin) for url in urls]
        for fut in as_completed(futs):
            payload = fut.result()
            if payload is not None:
                found.append(payload)
    return found


def _get_json(
    url: str,
    pin: str,
    extra: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    if not _host_pinned(urlparse(url).hostname, pin):
        return None
    headers = {"User-Agent": _UA}
    if extra:
        headers.update(extra)
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return None
            return resp.json()
    except Exception:
        return None


def _get_text(url: str, pin: str) -> str | None:
    if not _host_pinned(urlparse(url).hostname, pin):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return None
            return resp.text
    except Exception:
        return None
