"""Earth zone: nested knowledge on the solar-lab Earth globe.

Not a product title. Travel to Earth, or say enter Earth. Leave Earth
returns to heliocentric. Breadcrumb for the next agent:

- Now: feeds.FEEDS is 63 shipped / 9 keyed / 3 later / 4 out.
  Parallel merge_live. Overlay paints freshness, heading, inspect card.
  Docs: docs/earth.md (now vs next).
- Frames: store is ECEF metres; plate paints ECLIPJ2000 via frames.ecef_to_ecliptic.
- Honesty: simulated layers stay labeled simulated. live=on pulls
  shipped adapters. Failures keep sim. Mid-ocean VHF is deaf; a packet
  a keyed feed sent is painted. We do not buy sat-AIS. Sentinel-1
  ocean frames and GFW unmatched SAR are not hull names. Individual
  cars are a labeled hole. Completeness is the anti-beacon.
- Keyed waiting: AISStream, BarentsWatch, GFW, FIRMS, APRS, Space-Track,
  WAQI, OpenAQ (adapter waits), Shodan banners (never login).
- Later: viirs-boats (Mines FINAL still 401), Earthdata GRD, Copernicus.
- Out: sat-ais, unsecured-cams, face-index, car-vin.
- Next: more no-key 511 / WZDx / cameras; OpenAQ after a paste; VIIRS
  only if FINAL opens. Do not thin a region.
- Owned: RTSP or local webcam you own; face boxes in ENU, local only.
- Inventory: arelis.earth.feeds.FEEDS.
- People: contacts with lat/lon; local webcam boxes; events/assets.
- Tool: arelis.tools.earth_tool.EarthTool  (always schemaed; stage-gated).
- Verbs: enter Earth / leave Earth skip the 9B.
- Dump: outputs/physics/earth/<utc>/manifest.json + state.jsonl
- Visual: arelis/ui/earth_overlay.py from SolarPanel._paint_overlay.
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
