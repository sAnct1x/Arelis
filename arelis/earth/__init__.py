"""Earth zone: nested knowledge on Reality's Earth globe.

A zone inside Reality, not a room. Travel to Earth, or say enter Earth.
Leave Earth returns to heliocentric. Breadcrumb for the next agent:

- Now: feeds.FEEDS is 108 shipped / 25 keyed / 3 later / 4 out.
  Distance-gated live (`lod.py`): space=sats, approach=local planes,
  near=boats+planes, city=toggled layers. Natural Earth fill + borders
  for landfall. Adaptive Earth disc. GIBS mosaic when close. Cesium
  globe on enter (WebEngine). Optional OSM streets + building
  footprints (Cesium outlines at city; Qt fallback paints them too).
  Overlay paints freshness, heading, inspect card.
  Reality telemetry: logs/reality.log + reality.jsonl (always on).
  Docs: docs/earth.md (now vs next).
- Frames: store is ECEF metres; plate paints ECLIPJ2000 via frames.ecef_to_ecliptic.
  Near Earth the inspect eye is also ECEF (`EarthCam`). Leave / reset drops it.
- Honesty: simulated layers stay labeled simulated. live=on pulls
  shipped adapters. Failures keep sim. Mid-ocean VHF is deaf; a packet
  a keyed feed sent is painted. We do not buy sat-AIS. Sentinel-1
  ocean frames and GFW unmatched SAR are not hull names. Individual
  cars are a labeled hole. Completeness is the anti-beacon.
  Viewsheds say No terrain. Collision is no mesh, no DEM.
  Look-from URLs never on pins, dumps, cites, or reality logs.
  Qt fallback prefers earth_8192.jpg when present (still a sphere).
- Keyed waiting: AISStream, BarentsWatch, GFW, FIRMS, APRS, Space-Track,
  WAQI, OpenAQ, OpenSky OAuth2 (4,000 credits/day),
  Shodan banners (IP + body; never login, never look-from),
  DriveTexas conditions (no cameras), NSW Live Traffic cameras,
  WSDOT AccessCode, OHGO, DriveNC cameras, Travel-IQ CARS fleet
  (UT/AZ/ID/WI/LA/AK/NV/CT/NE).
- Later: viirs-boats (Mines FINAL still 401), Earthdata GRD, Copernicus.
- Out: sat-ais, unsecured-cams, face-index, car-vin.
- Next: more no-key official catalogs worldwide; VIIRS only if
  FINAL opens. Do not thin a region. Keys paste into secrets.yaml.
  Do not add catalogs until LOD/landfall is the way the plate works.
- Owned: RTSP / local webcam / pasted HTTP you own. Click look-from is
  live footage, not a still. Official publisher stills refresh on click.
  Stream URL never stored on the pin. Face boxes in ENU, local only.
- Inventory: arelis.earth.feeds.FEEDS.
- People: contacts with lat/lon; local webcam boxes; events/assets.
- Tool: arelis.tools.earth_tool.EarthTool  (always schemaed; stage-gated).
- Verbs: enter Earth / leave Earth skip the 9B.
- Dump: outputs/physics/earth/<utc>/manifest.json + state.jsonl
- Visual: Qt overlay (`earth_overlay.py`) plus Cesium plate
  (`earth_globe_host.py`) on enter. Do not delete the WebEngine host.
- Canvases: earth-hub, earth-layers, earth-runtime, earth-build.

Live adapters replace a layer; they do not invent coverage.
"""

from __future__ import annotations

from arelis.earth.runtime import (
    EarthRuntime,
    get_earth,
    require_earth,
    set_earth,
    stage_ok,
)

__all__ = [
    "EarthRuntime",
    "get_earth",
    "require_earth",
    "set_earth",
    "stage_ok",
]
