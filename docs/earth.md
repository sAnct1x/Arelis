# Earth zone

The Earth zone is a zone inside Reality — not a room of its own, and
not a product name. Travel to Earth, or just say **enter Earth**, and
you become an observer of whatever's already being broadcast or
published out there.

This page is both the inventory and the legal line for what's
included. The globe itself only runs on a source checkout
(`world_stage_allowed`), inside Reality, with
`pip install -e ".[astro]"` installed.

Inventory currently stands at `arelis/earth/feeds.py`: **108 shipped**,
**25 keyed**, **3 later**, **4 out**. Adapters are meant to replace a layer, not
invent coverage that isn't there — completeness is treated as the
anti-beacon here, meaning we'd rather leave a region visibly sparse
than quietly thin it out to hide a gap.

## What it actually is

A zone layered onto the existing Earth globe, inside Reality.
Internally, storage is in ECEF meters, while the rest of Reality still
runs on ECLIPJ2000 — `arelis/earth/frames.py` handles the handoff
between the two, including local ENU coordinates for street-level
camera frustums. Once the globe fills your view, the inspect camera
becomes Earth-fixed too, so continents stay put and contacts move
across them, rather than the other way around. Leaving Earth,
traveling to another body, or resetting the view all drop you back to
a heliocentric view. Same HUD throughout — no second visual theme.

To enter: travel to Earth (once the warp finishes), say **enter
Earth**, or call `earth action=enter`. To leave: say **leave Earth**,
travel elsewhere, or call `earth action=leave` (which writes a receipt
when it happens). Clicking a contact opens an inspect card — label,
kind in English, freshness, source, citation. Below the HUD sits a
read-only distance line (**from space** / **approaching** / **near
the ground** / **in the city**), then **Live off** / **Live on**,
**Grid**, **Streets**, **Buildings**, and every catalog layer
including People. Live starts off on purpose; the coach line says
to click it. Slash or the find field jumps to a city, country, state,
continent, or contact. Saying **take me to Tokyo** (or Japan,
California, Africa, the UK, home) is a closed verb — typed or
spoken, no model turn. Chat still works throughout all of this;
it's just never required.

The Live layer is distance-gated on purpose, so we're not hammering
every catalog while you're still out in space. Space band only
fetches satellites. Approach pulls in planes within the current look
box (via OpenSky's bounding-box query, 1 credit per call). Near adds
boats to the mix and drops satellite refresh entirely. City band
opens every layer whose chip is switched on — cameras, traffic,
weather, incident sites — still filtered down to the look area and
capped in volume. Layer chips all start off except for **Sats** and
**ISS**. The bar itself only ever shows what the current band can
actually use: space keeps just those two on; approach adds flights;
near adds boats; city opens the rest. Clicking a country or city on
the globe lets you fall toward it. A chip that's off simply isn't
being fetched at all.

Natural Earth country borders are painted directly onto the globe so
continents actually read clearly (public domain data, cached in ECEF
— not a live feed). Fill color only shows under those lines while the
globe is still small in view; once you're close, NASA's albedo
imagery becomes the actual land surface. State lines only appear as
part of the near/city-band detail (approach band keeps them
constrained to the look box). The GL globe itself uses the same
GMST-plus-obliquity frame as the overlay layers, with NASA's texture
referencing u=0.5 at Greenwich.

The Earth disc can grow past the usual 384px software-sphere size
once you've fallen in close. NASA GIBS imagery drapes in
automatically as you get near. **Streets** is opt-in OSM data (zoom
14 at near band, zoom 15 at city band). **Buildings** is opt-in
Overpass footprint data, available only at city band — outlines only,
no individual house labels. **Grid** shows latitude, longitude, and
altitude.

## Glyphs stay consistent

Every marker on the map speaks the same visual language as the rest
of Reality — one shared factory (`arelis/ui/earth_marks.py`) handles
Qt, Cesium billboards, the inspect card, and the solar-system roster
alike. Aircraft and ship hulls carry their heading right in the glyph
itself (a chevron or hull shape, with the nose pointing along the
track). Satellites read as a body with panels; radio sources as a
mast; fires as an ember shape. The ISS keeps its distinctive
ring-plus-arrays look, cameras get a square, drones a box, people a
double ring, radar a diamond, earthquakes an open circle sized by
magnitude, weather a triangle, traffic a flow bar, and incident sites
an open plus sign. Tracks that are being dead-reckoned (rather than
freshly reported) get a dashed ring; stale tracks get a slash through
them. Solar-system bodies — stars, planets, moons, asteroids, probes,
Lagrange points — use that same stroke family and theme color, not
some separately imported icon pack. H names the marks when you are in Earth. We still
avoid a floating legend over the globe.

## Where we actually stand

What shows up on the globe is only what a receiver or operator has
already chosen to publish. This isn't meant to be a US-centric map,
either — NYC, for instance, is represented by one municipal catalog
among many. `merge_live` only runs the adapters that the current band
and enabled chips allow, in parallel, then filters and caps
everything down to the current look box before applying it to the
view.

| What you might want | What you actually get |
|---|---|
| Every plane | OpenSky's look-box `/states/all` query, once you've fallen in close (1 credit per call). Capped at 2,500. The Space band doesn't poll this at all. |
| Every drone | OpenSky's UAV category only — most drones never broadcast a squawk in the first place. |
| Every ship | AISStream, Digitraffic Baltic, and BarentsWatch (keyed). Only packets an actual feed sent get painted — we're not purchasing satellite-AIS data. |
| Ocean gyres / general presence | Sentinel-1 pass footprints, plus GFW's unmatched SAR detections if you've added a key. Not a hull-by-hull name lookup. |
| Named events | NASA EONET, GDACS, and USGS volcano data, shown on the sites layer — not a facial recognition index. |
| Weather | Open-Meteo city pins, NWS CAP alerts, METAR/SIGMET, SWPC aurora data, NDBC buoys, and CO-OPS/IOC tide gauges. |
| Airports | OurAirports' large/medium scheduled-service fields — not a live radar feed. |
| Ocean floats | Argo's last-fix samples (via IFREMER ERDDAP, capped at 80) — not a painted subsurface shell. |
| Every car | A genuine gap. We use 511 / WZDx / Open511 / official ArcGIS catalogs, not individual VINs. |
| Every camera | TfL, Caltrans, NYC, SG LTA, Fintraffic, HK TD, CARS 511 (ON, MB, NS, AB, SK, FL, NY, CO, IA, MN, GA), ODOT TripCheck, SHA/NDDOT, ALGO, DelDOT, NZTA, Quebec 511, and OSM worldwide. These show as pins; official stills or streams play on click, when the publisher's own JSON includes them. The URL itself isn't stored on the pin. |
| Continents / countries / states | Natural Earth 110m border lines on the globe (cached in ECEF). Fill color only shows while the globe is small — not a live feed. |
| Ground imagery | NASA GIBS Blue Marble mosaic when you're close — a published mosaic, not a live satellite pass. |
| Street-level tiles | Optional OSM raster tiles when the Streets chip is on (ODbL-licensed, cached), at zoom 14 near / 15 city, boxed to the look area. |
| 3D cities | Google Photorealistic 3D Tiles, when `earth.google_maps_key` is set — covered cities only. |
| City blocks | Optional Overpass building footprints when Buildings is on, at city band, within roughly a 0.04° fabric box. Outlines only — individual houses stay unlabeled. |
| Every satellite | CelesTrak's GNSS / weather / visual / science / comm catalogs, plus Starlink/OneWeb/Planet samples — not a painted orbital shell of everything up there. |
| Military | adsb.lol's public squawk data only — aircraft that stay silent simply stay absent from the map. |
| Your own video | RTSP, a local webcam, or an HTTP MJPEG/snapshot feed you've pasted in yourself. Clicking the pin plays the live footage, with an eye rendered in the frustum if you've set a heading. Face detection boxes stay in local ENU coordinates only — WGS84 precision is enough for placing the pin itself. |

Traffic catalogs shipped out of the box (all operator JSON feeds, not
individual cars): Caltrans LCS, TfL Road, Fintraffic, DriveBC
Open511, NSW / QLD / NZTA, CARS 511 (ON, MB, NS, AB, SK, FL511,
511ny, COtrip, IA, MN, GA), WZDx (UDOT, KYTC, MoDOT, WisDOT, ITD,
511ny, AZ511, LADOTD, AB, NS, SK, FL511, IA, MN, GA, NCDOT, IN, KS,
WSDOT, NB, PE, YT, AK, NV), ArcGIS (SHA CHART, SA DIT, Main Roads
WA), NDDOT alerts, Quebec 511 events, and Autobahn GmbH
roadworks/warnings.

Earthquake catalogs shipped out of the box: USGS all_day feed, EMSC
FDSN (magnitude 2+, depth included when published), and GeoNet NZ.

## Being honest about freshness

Every entity carries a freshness indicator. By default, what you're
seeing is a simulated version of moving layers plus reconstructed
static pins. Calling `earth action=live` switches on the actual
shipped feeds from `arelis/earth/feeds.py` — and if any of those
fail, it just falls back to the simulation rather than showing
nothing. Live aircraft and ships with a known velocity get
dead-reckoned (extrapolated forward) after 90 seconds without an
update, then marked stale after 15 minutes. Satellites just stay at
their last SGP4-propagated position until the next poll comes in.

Viewsheds shown are pose priors, not verified line-of-sight — the
inspect card is upfront that there's **No terrain** behind them.
Collision detection and the solar tool are both deliberately built
with no mesh and no DEM data — this supports approach and orbit
views only, never a landing. Look-from URLs are never attached to
entities, data dumps, citations, or `logs/reality.*` — they exist
only at the moment you click. Individual cars remain a clearly
labeled gap in coverage. The Qt fallback sphere prefers
`earth_8192.jpg` (NASA's Blue Marble shallow-topo imagery, roughly
5 km per pixel) when that file is present on disk — but it's still
just a static drape, not something you can walk around on.

## Where the legal line actually sits

Authorization is the deciding factor. What's in bounds: public APIs,
unofficial JSON that an operator's own map already relies on, keyed
feeds you've pasted in yourself, and sensors you personally own.
Clicking look-from plays back either the live stream you pasted in,
or an official publisher still/stream sourced from that same JSON
feed. An open port by itself is never treated as consent. Sites like
Insecam, logging into a camera you don't own, any kind of global
face-recognition index, or a VIN/license-plate dragnet are all
explicitly out of bounds and won't be implemented.

## Keyed feeds (already wired, just waiting on your key)

Paste these into the gitignored `data/secrets.yaml`. You don't need
to wait on these before using the no-key adapters that already ship.

| Key | Signup | Host |
|---|---|---|
| `earth.google_maps_key` | Google Cloud Map Tiles API — enables photorealistic 3D cities. A budget alert is recommended | tile.googleapis.com |
| `earth.cesium_ion_token` | https://cesium.com/ion — optional terrain/Bing imagery, not required otherwise | ion.cesium.com / api.cesium.com |
| `earth.aisstream_key` | https://aisstream.io | stream.aisstream.io |
| `earth.barentswatch_client_id` / `_secret` | https://www.barentswatch.no | id / live.ais.barentswatch.no |
| `earth.gfw_token` | https://globalfishingwatch.org | gateway.api.globalfishingwatch.org (CC BY-NC; we stay under their rate cap) |
| `earth.firms_key` | https://firms.modaps.eosdis.nasa.gov/api/ | firms.modaps.eosdis.nasa.gov |
| `earth.aprs_key` | https://aprs.fi (My Account key) | api.aprs.fi |
| `earth.spacetrack_user` / `_password` | https://www.space-track.org/auth/createAccount (.edu accepted) | www.space-track.org |
| `earth.waqi_token` | https://aqicn.org/data-platform/token/ | api.waqi.info (WAQI plus the originating EPA citation; treat it as a local observer, don't republish) |
| `earth.opensky_client_id` / `_secret` | Account → API client → credentials.json | opensky-network.org + auth.opensky-network.org (OAuth2, Standard tier is 4,000 credits/day — we stay under that) |
| `earth.openaq_key` | https://explore.openaq.org/register | api.openaq.org (OpenAQ plus originating provider; local observer, don't republish) |
| `earth.shodan_key` | Hobby tier; IP and banner catalog only — never used to log in, never used for look-from | api.shodan.io |
| `earth.drivetexas_key` | https://api.drivetexas.org/request-key — conditions and WZDx only, no cameras | api.drivetexas.org |
| `earth.nsw_key` | https://opendata.transport.nsw.gov.au/user/register — Live Traffic cameras, sent as header `apikey TOKEN` | api.transport.nsw.gov.au |
| `earth.wsdot_access_code` | https://wsdot.wa.gov/traffic/api/ — cameras plus highway alerts | wsdot.wa.gov |
| `earth.ohgo_key` | https://publicapi.ohgo.com/ — cameras, incidents, construction. Sent as header `APIKEY` | publicapi.ohgo.com |
| `earth.drivenc_key` | https://drivenc.gov/my511/register — cameras (WZDx already ships) | drivenc.gov |
| `earth.cars_keys` | Travel-IQ `/my511/register` on each host — cameras and events. WZDx already ships where listed | udottraffic.utah.gov, az511.gov, 511.idaho.gov, 511wi.gov, 511la.org, 511.alaska.gov, nvroads.com, ctroads.org, 511.nebraska.gov |

OpenSky already works anonymously out of the box — paste in an API
client to unlock the Standard tier (4,000 credits/day); we stay well
under that, or back off on a 429 response. There's also an optional
Alberta 511 developer key available at
https://511.alberta.ca/developers (the public GET endpoint already
ships without it). For cameras you personally own, use
`earth.cameras` or `earth.local_camera` (WGS84 precision is plenty
for placing the pin). Only `rtsp:` links, local devices, or HTTP
streams you actually own are used for live feeds — clicking
look-from plays the live feed itself, never a static still, and none
of it gets stored on the entity.

## Coming later (deliberately not built yet)

| Id | Why it's waiting |
|---|---|
| `viirs-boats` | EOG's FINAL dataset still returns a 401; the NRT version is a paid tier we're not buying |
| `earthdata` | https://urs.earthdata.nasa.gov/users/new — for downloading Sentinel-1 GRD data later. Footprint catalogs already ship via ASF in the meantime |
| `copernicus-dataspace` | Additional Sentinel data, later — a scene by itself still isn't a hull identification |

## Deliberately out of scope

| Id | Why |
|---|---|
| `sat-ais` | We won't pay for Spire, exactEarth, or paid MarineTraffic tiers |
| `unsecured-cams` | An open port still isn't consent |
| `face-index` | Public search over named events and assets is fine; a facial index is not |
| `car-vin` | There's no legitimate, legal way to build a global car-tracking dataset |

## The globe itself

Entering Earth hands the planet rendering over to Cesium (via
WebEngine, source checkout with `.[astro]` only). Arelis still paints
the starfield and the HUD on top. The HUD is masked to just the
chrome elements, so scrolling and dragging pass through to the globe
underneath correctly. Contacts rendered in Cesium are billboards
drawn from that same shared mark factory — not generic teardrop map
pins. The very first thing painted is NASA GIBS imagery, so the
globe is never left black while things load. Streets show up via the
Streets chip (OSM data). Building outlines get pushed into Cesium at
city band when that chip is enabled — outlines only, no house
labels, no extrusion into 3D volumes. Photorealistic 3D cities only
load once you've actually fallen in close, and only if
`earth.google_maps_key` is set — and a failure to load photoreal
data is never allowed to crash the globe entirely. Without a Cesium
ion token, terrain just renders as a plain ellipsoid rather than
actual hills. The inspect card always tells you which rendering
stack is currently active, and attribution credits stay visible on
screen. The Qt-based NASA imagery ball is the fallback whenever
WebEngine is unavailable or Cesium fails to load — and it's also
what every other planet in the solar system still uses. No
action-movie overlay, no landing capability. Tests that only check
image luminosity aren't treated as proof that a city actually
rendered correctly.

## What's coming next

More no-key 511 / WZDx / ArcGIS / camera inventories, expanding
worldwide. More official still-image CDNs added to the look
allowlist, wherever a catalog already publishes them. VIIRS data
only if Mines opens up the FINAL dataset without requiring a login.
We won't be purchasing satellite-AIS data. We won't thin out a
region just to hide an individual house. Individual cars remain, and
will stay, a clearly labeled gap in coverage.

## Files

| Path | Job |
|---|---|
| `arelis/earth/` | Entity handling, storage, runtime, frames, simulation, live data, feeds, adapters |
| `arelis/earth/lod.py` | Distance bands, look box logic, adapter/layer gating |
| `arelis/earth/land.py` | Natural Earth country fill plus state-line and admin-1 centroid cache for landfall |
| `arelis/earth/buildings.py` | City-band Overpass building footprints. Cached, not a live feed |
| `arelis/physics/telemetry.py` | Reality logging plus jsonl output, always on while things are being tuned |
| `arelis/earth/owned.py` | Owned-camera face boxes, in local ENU coordinates |
| `arelis/earth/look.py` | Click-time look-from / listen caching; URLs are never attached to entities |
| `arelis/earth/tiles.py` | GIBS plus OSM raster tile cache |
| `arelis/earth/globe_stack.py` | Which imagery layers this particular copy is allowed to show |
| `arelis/ui/earth_globe/` | The Cesium page itself (rendering engine only, no HUD overlay) |
| `arelis/ui/earth_globe_host.py` | Qt WebEngine host, QWebChannel bridge, and the mark atlas |
| `arelis/ui/earth_marks.py` | The shared mark-drawing code — used by Qt, Cesium, the inspect card, and the roster |
| `arelis/earth/tides.py` | CO-OPS plus IOC sea-level gauge data |
| `arelis/earth/argo.py` | Argo float last-fix sampling |
| `arelis/tools/earth_tool.py` | The model-facing tool surface (don't shrink this schema) |
| `arelis/ui/earth_overlay.py` | Overlay paint, hit-testing, ride camera, and tile handling |
| `outputs/physics/earth/` | Dump receipts |

## How to actually run it

You'll need a source checkout (`world_stage_allowed`), inside
Reality, with the solar system already loaded, and
`pip install -e ".[astro]"` installed. Then travel to Earth, say
**enter Earth**, or **take me to Tokyo**. The Live layer is turned
on via its chip, the `earth action=live` call, or just by asking
in chat — it's not locked to one specific phrase.
