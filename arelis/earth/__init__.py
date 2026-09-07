"""Earth zone: nested knowledge on Reality's Earth globe.

A zone inside Reality, not a room. Travel to is a solar-lab warp
to any body. Enter appears after you arrive at Earth — the zone
door. Closer bands *can* show more; chips stay yours.
Leave Earth returns to heliocentric. Breadcrumb for the next agent:

- Concept closed (2026-09-05): the 2026-08 zone plan is this package.
  Archive that chat. Do not name the zone. Room id stays physics.
  Source of truth: docs/earth.md + feeds.FEEDS.
- Now: feeds.FEEDS is 109 shipped / 25 keyed / 3 later / 4 out.
  Distance-gated live (`lod.py`): space=sats, approach keeps sats and
  opens planes, near adds boats, city opens ground catalogs. Streets
  wait on altitude. Observer budget
  (`physics.observe`): the camera is not a body. Physics stays true;
  the plate commits at half a pixel of accumulated screen motion —
  every solar body, orbit and IAU spin. Overnight and a closer zoom
  are the same math. Travel standoff does not show Earth spin.
  Natural Earth fill + borders for landfall. Adaptive Earth disc.
  GIBS mosaic when close. Earth zone is Cesium after solar GL is
  destroyed — a child process when the solar lab used GPU, because
  park() cannot kill the Qt share group. Native NASA disc is fallback
  only (no WebEngine, Cesium boot fail). Pytest without GPU solar
  stays in-process. Never both live. Named road overlay only when close
  (Overpass, on GIBS / photoreal — not the OSM carto drawing),
  Find types and flies (gazetteer, then Nominatim force=True).
  Cesium pins are WGS84 from the ECEF store. Distance meter waits
  on the Cesium look-ray; map scale only closer in.
  Building footprints at city. Overlay paints freshness,
  heading, inspect card, Earth trail on track/ride.
  Reality telemetry: logs/reality.log + reality.jsonl (always on).
  Docs: docs/earth.md (now vs next).
- Frames: store is ECEF metres; plate paints ECLIPJ2000 via frames.ecef_to_ecliptic.
  Near Earth the inspect eye is also ECEF (`EarthCam`). Leave / reset drops it.
-   Honesty: Enter takes one published snapshot (wall clock when the
  lab can lock), then live TTL for air/sea while tracks coast.
  Sats re-run SGP4 between TLE polls. Air/sea pose time is `_pose_unix`
  so Cesium does not double-coast. Cesium FOV matches the solar
  eye. CelesTrak groups overlap.
  Leave clears; re-enter refetches. Failures keep sim.
  Simulated layers stay labeled simulated. Mid-ocean VHF is deaf; a packet
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
- Verbs: enter Earth / leave Earth / take me to <place> skip the 9B.
- Dump: outputs/physics/earth/<utc>/manifest.json + state.jsonl
- Visual: Cesium (`earth_globe_host.py` / `earth_globe_proc.py`) is
  the Earth-zone planet. The plate is opaque (no child winId on the
  HUD, no leftover solar frame). Qt overlay (`earth_overlay.py`) is
  HUD + fallback disc. City look is 8 km AGL (city band). Do not
  delete the WebEngine host.
- Canvas close-out: reality-vs-concept (concept chat archived).
  Plate polish: arelis/earth/copy.py, goto.py, key_paste.py,
  arelis/ui/earth_find.py, earth_chrome.py. Status is a sentence.
  Find is on the plate. Say take me to Tokyo or a street address.
  Band is type. Enter turns Live on.

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
