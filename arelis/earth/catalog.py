"""Layer catalog. Source, hole, default on. Not a HUD skin."""

from __future__ import annotations

from dataclasses import dataclass

from arelis.earth.entity import LAYER_IDS


@dataclass(frozen=True)
class LayerSpec:
    id: str
    title: str
    what: str
    source: str
    hole: str
    default_on: bool = True


LAYERS: tuple[LayerSpec, ...] = (
    LayerSpec(
        "flights",
        "Flights",
        "Civil air traffic on great-circle routes (sim) or ADS-B (live).",
        "simulated worldgen; live: OpenSky Network, every squawk in the poll",
        "Oceans and polar with no receiver. Silent airframes stay absent.",
    ),
    LayerSpec(
        "drones",
        "Drones",
        "ADS-B category UAV. Most drones never squawk.",
        "live: OpenSky category=UAV; simulated: none (do not invent a swarm)",
        "Remote ID without a public dump is a hole. An open Wi-Fi drone is not consent.",
    ),
    LayerSpec(
        "military",
        "Military ADS-B",
        "Military tracks that are publicly squawking.",
        "simulated subset; live: adsb.lol /v2/mil",
        "Anything not squawking is invisible. That is the point.",
    ),
    LayerSpec(
        "vessels",
        "Vessels",
        "Coastal AIS. Mid-ocean is empty: VHF dies tens of kilometres from a receiver.",
        "simulated coastal; live: AISStream + Digitraffic + BarentsWatch if keyed",
        "Packets a keyed feed sent are painted. We do not buy sat-AIS.",
    ),
    LayerSpec(
        "radar",
        "Radar",
        "Sentinel-1 IW frames, mid-ocean sample. A pass, not a hull name.",
        "live: NASA ASF pass footprints + GFW unmatched SAR if keyed",
        "A frame is not a hull. Browse is too coarse to resolve ships. Not AIS.",
    ),
    LayerSpec(
        "satellites",
        "Satellites",
        "LEO/MEO from public TLEs (sim shells, or CelesTrak + SGP4).",
        "simulated shells; live: CelesTrak samples + Space-Track GP if keyed",
        "Classified objects are not in the file. Starlink is a sample, not the shell.",
    ),
    LayerSpec(
        "iss",
        "ISS",
        "NORAD 25544. CelesTrak stations TLE + SGP4 when live.",
        "simulated Kepler; live: CelesTrak or Space-Track TLE + SGP4",
        "TLE epoch hours stale. Metre-accurate it is not.",
        True,
    ),
    LayerSpec(
        "quakes",
        "Earthquakes",
        "Recent seismicity as points.",
        "simulated belts; live: USGS all_day + EMSC FDSN + GeoNet NZ",
        "Only what a seismograph reported.",
    ),
    LayerSpec(
        "fires",
        "Fires",
        "Hotspots, trailing day.",
        "simulated; live: NASA FIRMS (key)",
        "Cloud and revisit hide fires.",
    ),
    LayerSpec(
        "weather",
        "Weather",
        "Sampled stations + a jet-stream sketch.",
        "simulated climates; live: Open-Meteo + NWS + METAR/SIGMET + "
        "SWPC + NDBC + CO-OPS/IOC + WAQI if keyed",
        "Not a forecast model. NWS is US CAP. Most of Earth is a hole.",
    ),
    LayerSpec(
        "radio",
        "Radio",
        "Geolocated broadcast transmitters.",
        "simulated FM + Radio Browser; live APRS if keyed + SatNOGS stations",
        "Most RF has no point on a globe.",
    ),
    LayerSpec(
        "cameras",
        "Cameras",
        "Published municipal camera *positions*. Not a video dragnet.",
        "live: TfL, Caltrans, NYC, SG LTA, Fintraffic, HK TD, "
        "CARS 511 cameras, ODOT TripCheck, SHA/NDDOT, OSM worldwide",
        "Rural is blind. Unpublished cams are holes. Viewsheds need a pose prior.",
    ),
    LayerSpec(
        "traffic",
        "Traffic",
        "Street-scale *flow* sketch. Individual cars are not a public feed.",
        "simulated dots; live: 511 / WZDx / Open511 / ArcGIS. No VIN, no plate",
        "No legal global car tracker. Adapters replace; they do not invent cars.",
        False,
    ),
    LayerSpec(
        "sites",
        "Sites",
        "Static infrastructure: a few cables, dams, airports.",
        "bundled pins; live: Launch Library + EONET + OurAirports + "
        "volcanoes + GDACS + Argo sample + TIP",
        "Incomplete by nature. Reconstructed pins, not live SCADA. Named events are not faces.",
    ),
    LayerSpec(
        "people",
        "People",
        "Contacts with coordinates on the card. Everyone else stays off the map.",
        "data/contacts.yaml lat/lon. Never geocoded.",
        "Unknown people are a hole. Not a face index.",
    ),
)

LAYER_BY_ID: dict[str, LayerSpec] = {spec.id: spec for spec in LAYERS}

assert tuple(spec.id for spec in LAYERS) == LAYER_IDS
