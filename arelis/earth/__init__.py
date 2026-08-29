"""Earth zone: nested knowledge on the solar-lab Earth globe.

Not a product title. Travel to Earth, or say enter Earth. Leave Earth
returns to heliocentric. Breadcrumb for the next agent:

- Frames: store is ECEF metres; plate paints ECLIPJ2000 via frames.ecef_to_ecliptic.
- Honesty: simulated layers stay labeled simulated. live=on may pull
  USGS, OpenSky (every squawk + UAV category), adsb.lol military,
  AISStream (free key), Fintraffic Digitraffic AIS (no key), BarentsWatch
  (keyed), CelesTrak TLE + Starlink/OneWeb samples, Radio Browser, TfL /
  Caltrans / NYC / Singapore / Finland / Hong Kong camera catalogs,
  OSM webcams worldwide, OSM tiles (optional chip), Open-Meteo, FIRMS
  (free key), Launch Library, APRS (free key), Shodan banners (optional
  free key, not a login). Failures keep sim. Mid-ocean VHF is deaf; a
  packet a keyed feed sent is painted. We do not buy sat-AIS.
  Sentinel-1 ocean frames and GFW unmatched SAR are not hull names.
  NASA EONET named events. Individual cars are not a public feed.
- Out: logging into a camera you do not own; intercepting encrypted radio;
  a global face index; a VIN/plate dragnet. Observer of broadcasts.
  Keyed public APIs (including a Shodan banner catalog) are in.
  Insecam video of someone else's cam is still out.
- Owned: RTSP or local webcam you own; face boxes in ENU, local only.
  Not a named webcam model.
- Inventory: arelis.earth.feeds.FEEDS (shipped / keyed / later / out).
- People: contacts with lat/lon; local webcam boxes later; events/assets.
- Tool: arelis.tools.earth_tool.EarthTool  (always schemaed; stage-gated).
- Verbs: enter Earth / leave Earth skip the 9B.
- Dump: outputs/physics/earth/<utc>/manifest.json + state.jsonl
- Visual: arelis/ui/earth_overlay.py from SolarPanel._paint_overlay.
- Canvases: earth-hub, earth-layers, earth-runtime, earth-build.

Stretch 1 ships a full simulated observatory so the globe is never empty.
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
