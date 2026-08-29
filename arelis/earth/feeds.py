"""Legal OSINT network for the Earth zone. Inventory, not a crawl.

Every public / keyed / owned source we intend lives here so the globe
cannot grow a silent adapter. Shipped rows fetch. Keyed rows wait on a
paste. Later rows are next. Out rows are refused — no host in source.

The observer sees what is broadcasting or published. Individual cars,
silent airframes, unpublished cameras, and mid-ocean ships (VHF dies
offshore; we do not buy satellite AIS) are holes, not scrape targets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

FeedStatus = Literal["shipped", "keyed", "later", "out"]


@dataclass(frozen=True)
class FeedSpec:
    id: str
    layer: str
    status: FeedStatus
    what: str
    hole: str
    host: str = ""
    key: str = ""


FEEDS: tuple[FeedSpec, ...] = (
    FeedSpec(
        "usgs",
        "quakes",
        "shipped",
        "USGS all_day GeoJSON",
        "Below network detection. Delayed.",
        host="earthquake.usgs.gov",
    ),
    FeedSpec(
        "opensky",
        "flights",
        "shipped",
        "OpenSky Network /api/states/all (every squawk in the poll, UAV split)",
        "Oceans and remote FIR. Silent airframes stay absent. Not every car.",
        host="opensky-network.org",
    ),
    FeedSpec(
        "adsb-mil",
        "military",
        "shipped",
        "adsb.lol /v2/mil public military ADS-B",
        "Silent airframes are a deaf zone.",
        host="adsb.lol",
    ),
    FeedSpec(
        "aisstream",
        "vessels",
        "keyed",
        "AISStream AIS (free key). Paint packets the feed sent, including mid-ocean if mixed.",
        "Worldwide coastal sample. Mid-ocean VHF is deaf. We do not buy a sat-AIS product.",
        host="stream.aisstream.io",
        key="earth.aisstream_key",
    ),
    FeedSpec(
        "celestrak",
        "satellites",
        "shipped",
        "CelesTrak GP TLE + SGP4 (stations, gps-ops, weather, visual, Starlink sample)",
        "Classified objects absent. Starlink is a sample, not the painted shell.",
        host="celestrak.org",
    ),
    FeedSpec(
        "radio-browser",
        "radio",
        "shipped",
        "Radio Browser directory geo pins",
        "No audio. Not a transmitter viewshed.",
        host="radio-browser.info",
    ),
    FeedSpec(
        "tfl-jamcam",
        "cameras",
        "shipped",
        "TfL JamCam published positions",
        "Pose unknown unless a prior exists. No stills, no video. Rural is blind.",
        host="api.tfl.gov.uk",
    ),
    FeedSpec(
        "caltrans-cctv",
        "cameras",
        "shipped",
        "Caltrans D1-D12 published CCTV positions + look direction",
        "Rural CA and other states are holes. No still ingest.",
        host="cwwp2.dot.ca.gov",
    ),
    FeedSpec(
        "open-meteo",
        "weather",
        "shipped",
        "Open-Meteo current at city pins",
        "Model grid, not a station mesh.",
        host="api.open-meteo.com",
    ),
    FeedSpec(
        "launches",
        "sites",
        "shipped",
        "Launch Library 2 upcoming pads",
        "Pads without geo are a hole. Not a T-0 clock.",
        host="ll.thespacedevs.com",
    ),
    FeedSpec(
        "firms",
        "fires",
        "keyed",
        "NASA FIRMS hotspots (free MAP_KEY)",
        "Cloud and revisit. Needs a free MAP_KEY. We do not buy a higher tier.",
        host="firms.modaps.eosdis.nasa.gov",
        key="earth.firms_key",
    ),
    FeedSpec(
        "digitraffic",
        "vessels",
        "shipped",
        "Fintraffic Digitraffic AIS (Finnish coast / Baltic, no key)",
        "Not global. Mid-ocean VHF is deaf. We do not buy satellite AIS.",
        host="meri.digitraffic.fi",
    ),
    FeedSpec(
        "eonet",
        "sites",
        "shipped",
        "NASA EONET open natural events (named storms, fires, volcanoes)",
        "Not every incident. Not a face index.",
        host="eonet.gsfc.nasa.gov",
    ),
    FeedSpec(
        "tfl-road",
        "traffic",
        "shipped",
        "TfL Road Disruption (not VINs)",
        "London roads. Individual cars are not a public feed.",
        host="api.tfl.gov.uk",
    ),
    FeedSpec(
        "osm-webcams",
        "cameras",
        "shipped",
        "OSM camera:type=webcam pins worldwide (ODbL, positions only)",
        "Mapper catalog, not a crawl. No stills. Overpass sample boxes on inhabited continents.",
        host="overpass-api.de",
    ),
    FeedSpec(
        "sentinel1-asf",
        "radar",
        "shipped",
        "NASA ASF Sentinel-1 IW GRD catalog, mid-ocean sample (pass footprints)",
        "A frame is not a hull. Sample of recent scenes, not every pass.",
        host="api.daac.asf.alaska.edu",
    ),
    FeedSpec(
        "viirs-boats",
        "radar",
        "later",
        "EOG VIIRS night-light boat detections (CC BY 4.0 when the file is open)",
        "Mines NRT tree currently wants a login. Not a name tag.",
    ),
    FeedSpec(
        "sat-ais",
        "vessels",
        "out",
        "Commercial satellite AIS (Spire, exactEarth, paid MarineTraffic)",
        "Not illegal. We will not pay. Mid-ocean stays empty.",
    ),
    FeedSpec(
        "barentswatch",
        "vessels",
        "keyed",
        "Kystverket / BarentsWatch AIS (free AIS client, Norwegian EEZ + their sats)",
        "Not a global paid sat-AIS product. Fishing <15 m and leisure/sail <45 m withheld.",
        host="live.ais.barentswatch.no",
        key="earth.barentswatch_client_id",
    ),
    FeedSpec(
        "gfw-sar",
        "radar",
        "keyed",
        "Global Fishing Watch unmatched SAR detections (CC BY-NC, local observer)",
        "Industrial-scale metal, ~5 day lag. Not a hull name. Not a resale.",
        host="gateway.api.globalfishingwatch.org",
        key="earth.gfw_token",
    ),
    FeedSpec(
        "nyc-dot",
        "cameras",
        "shipped",
        "NYC DOT public map camera positions (one city catalog)",
        "Position only. No stills. Not the globe.",
        host="webcams.nyctmc.org",
    ),
    FeedSpec(
        "sg-lta",
        "cameras",
        "shipped",
        "Singapore LTA traffic-camera positions (data.gov.sg)",
        "Position only. No stills.",
        host="api.data.gov.sg",
    ),
    FeedSpec(
        "fi-weathercam",
        "cameras",
        "shipped",
        "Fintraffic road weather cameras (CC BY 4.0)",
        "Finland roads. Position only. No stills.",
        host="tie.digitraffic.fi",
    ),
    FeedSpec(
        "hk-td",
        "cameras",
        "shipped",
        "Hong Kong Transport Department camera locations",
        "Position only. No stills.",
        host="static.data.gov.hk",
    ),
    FeedSpec(
        "osm-tiles",
        "sites",
        "shipped",
        "OpenStreetMap raster tiles on the disc when Tiles is on (ODbL)",
        "Optional. Never required to see holes. Cache + 2 connections.",
        host="tile.openstreetmap.org",
    ),
    FeedSpec(
        "fi-traffic",
        "traffic",
        "shipped",
        "Fintraffic traffic messages (not VINs)",
        "Finnish roads. Individual cars are not a public feed.",
        host="tie.digitraffic.fi",
    ),
    FeedSpec(
        "aprs",
        "radio",
        "keyed",
        "aprs.fi loc for named stations (https://aprs.fi)",
        "Only callsigns you name (default W1AW). No wildcard, no map scrape.",
        host="api.aprs.fi",
        key="earth.aprs_key",
    ),
    FeedSpec(
        "caltrans-lcs",
        "traffic",
        "shipped",
        "Caltrans lane-closure / work-zone catalog (not VINs)",
        "Individual cars are not a public feed. Other states later.",
        host="cwwp2.dot.ca.gov",
    ),
    FeedSpec(
        "shodan-banners",
        "cameras",
        "keyed",
        "Shodan banner catalog if a free key already exists",
        "Banners, not a login. We will not buy a membership. Default password is still a login.",
        host="api.shodan.io",
        key="earth.shodan_key",
    ),
    FeedSpec(
        "owned-rtsp",
        "cameras",
        "shipped",
        "Operator-owned RTSP / local webcam stills and ENU face boxes",
        "Only cameras we own. Stream URL never stored. No global face index.",
    ),
    FeedSpec(
        "contacts",
        "people",
        "shipped",
        "Address-book people with lat/lon on the card",
        "Unknown people stay off the map. Never geocoded.",
    ),
    FeedSpec(
        "unsecured-cams",
        "cameras",
        "out",
        "Insecam / default-password / anyone's open RTSP",
        "An open port is not consent.",
    ),
    FeedSpec(
        "face-index",
        "sites",
        "out",
        "Global face search on municipal CCTV",
        "Named public search is events and assets, not faces.",
    ),
    FeedSpec(
        "car-vin",
        "traffic",
        "out",
        "Every car / plate / phone ping",
        "There is no legal global car tracker. Observer of broadcasts, not a dragnet.",
    ),
)

FEED_BY_ID: dict[str, FeedSpec] = {spec.id: spec for spec in FEEDS}


def shipped_hosts() -> tuple[str, ...]:
    return tuple(spec.host for spec in FEEDS if spec.status == "shipped" and spec.host)
