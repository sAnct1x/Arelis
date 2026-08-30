# Earth zone

A zone inside Reality, not a room and not a product title. Travel to
Earth, or say **enter Earth**. You are an observer of what is
broadcasting or published.

This page is the inventory and the legal line. The globe lives on a
source checkout only (`world_stage_allowed`), in Reality, with
`pip install -e ".[astro]"`. Travel to Earth or say **enter Earth**.
Leave: **leave Earth**, travel to another body, or `earth action=leave`.

Inventory is `arelis/earth/feeds.py`: **108 shipped**, **25 keyed**,
**3 later**, **4 out**. Adapters replace a layer; they do not invent
coverage. Completeness is the anti-beacon — do not thin a region.

## What it is

A **zone** on the existing Earth globe, inside Reality. Store is ECEF
metres. The plate is still ECLIPJ2000; `arelis/earth/frames.py` is the
handoff (including local ENU for street frustums). Once the globe fills
the view, the inspect eye is Earth-fixed too — continents stay put,
contacts move over them. Leave Earth, travel to another body, or reset
view returns to heliocentric. Same sodium HUD. No thriller skin.

Enter: travel to Earth (warp finish), say **enter Earth**, or
`earth action=enter`. Leave: **leave Earth**, travel to another body,
or `earth action=leave` (writes a receipt). Click a contact for a sodium
inspect card (label, id, layer, freshness, source, cite). Under the HUD,
a read-only **Space / Approach / Near / City** chip, then **Live**,
**Grid**, **Streets**, **Buildings**, and every layer except People —
click to toggle. Chat still works; it is not required.

Live is distance-gated so we do not slam every catalog from orbit.
**Space** fetches satellites only. **Approach** pulls planes in the
look box (OpenSky bbox, 1 credit). **Near** adds boats and drops
satellite refresh. **City** opens every layer whose chip is on —
cameras, traffic, weather, sites — still filtered to the look area
and capped. Layer chips start dark except **Sats** and **ISS**. The bar only
shows what this band can use: space keeps those two; approach adds
flights; near adds boats; city opens the rest. Click a country or
city on the disc to fall toward it. A dark chip is not fetched. Natural Earth country lines paint on the
disc so continents actually read (public domain, cached ECEF, not a
feed). Fills sit under the strokes only while the disc is still small;
the NASA albedo is the land once you are close. State lines are a
near/city fabric (approach keeps them in the look box). The GL globe
uses the same GMST+obliquity frame as the overlays, with NASA u=0.5
on Greenwich.
The Earth disc can grow past the usual 384 px software sphere once you
have fallen in. NASA GIBS drapes automatically when close. **Streets**
is opt-in OSM (z14 near / z15 city). **Buildings** is opt-in Overpass
footprints at city band only — outlines, no house labels. **Grid**
shows lat/lon/alt.

Glyphs stay in the plate language — one factory (`arelis/ui/earth_marks.py`)
for Qt, Cesium billboards, the inspect card, and the solar roster.
Airframes and hulls carry heading in the mark (chevron / hull, nose =
track). Satellites read as a body plus panels, radio as a mast, fire
as an ember. ISS keeps its ring plus arrays, cameras the square,
drones the box, people the double ring, radar the diamond, quakes the
open circle by magnitude, weather the triangle, traffic a flow bar,
sites an open plus. Dead-reckoned tracks get a dashed ring; stale
tracks a slash. Solar kinds (star / planet / moon / asteroid / probe /
Lagrange) use the same stroke family and theme ink — no imported icon
pack. Do not dump Keys chrome.

## Where we are

What is on the plate is what a receiver or an operator already published.
The globe is not a US map. NYC is one municipal catalog. `merge_live`
runs only the adapters this band and these chips allow, in parallel,
then filters and caps to the look box before it applies.

| Want | What you actually get |
|------|------------------------|
| Every plane | OpenSky: look-box `/states/all` once you have fallen in (1 credit). Cap 2500. Space does not poll it |
| Every drone | OpenSky UAV category only. Most drones never squawk |
| Every ship | AISStream + Digitraffic Baltic + BarentsWatch (keyed). Packets a feed sent are painted. We do not buy sat-AIS |
| Gyre / ocean presence | Sentinel-1 pass footprints + GFW unmatched SAR if keyed. Not a hull name |
| Named events | NASA EONET + GDACS + USGS volcanoes on sites. Not a face index |
| Weather | Open-Meteo city pins + NWS CAP + METAR/SIGMET + SWPC aurora + NDBC + CO-OPS/IOC gauges |
| Airports | OurAirports large/medium scheduled fields. Not a live radar |
| Ocean floats | Argo last-fix *sample* (IFREMER ERDDAP, cap 80). Not a painted shell |
| Every car | **Hole.** 511 / WZDx / Open511 / official ArcGIS catalogs, not VINs |
| Every camera | TfL, Caltrans, NYC, SG LTA, Fintraffic, HK TD, CARS 511 (ON, MB, NS, AB, SK, FL, NY, CO, IA, MN, GA), ODOT TripCheck, SHA/NDDOT, ALGO, DelDOT, NZTA, Quebec 511, OSM worldwide. Pins. Official stills/streams play on click when the publisher JSON includes them; URL is not stored on the pin |
| Continents / countries / states | Natural Earth 110m lines on the disc (ECEF cache). Fill only while the disc is small. Not a feed |
| Ground mosaic | NASA GIBS Blue Marble when close. Published mosaic, not a live pass |
| Street tiles | Optional OSM raster when **Streets** is on. ODbL. Cache. z14 near / z15 city, look-pin boxed |
| 3D cities | Google Photorealistic 3D Tiles when `earth.google_maps_key` is set. Covered cities only |
| City blocks | Optional Overpass building footprints when **Buildings** is on. City band, ~0.04° fabric box. Outlines only. Individual houses stay unlabeled |
| Every satellite | CelesTrak GNSS / weather / visual / science / comm + Starlink/OneWeb/Planet *samples*, not a painted shell |
| Military | adsb.lol public squawks. Silent airframes stay absent |
| Owned video | RTSP, local webcam, or HTTP MJPEG/snapshot you pasted. Click the pin — live footage, eye in the frustum if heading is set. Face boxes in ENU, local only. WGS84 is enough for a pin |

Shipped traffic catalogs (operator JSON, not cars): Caltrans LCS, TfL
Road, Fintraffic, DriveBC Open511, NSW / QLD / NZTA, CARS 511 (ON, MB,
NS, AB, SK, FL511, 511ny, COtrip, IA, MN, GA), WZDx (UDOT, KYTC, MoDOT,
WisDOT, ITD, 511ny, AZ511, LADOTD, AB, NS, SK, FL511, IA, MN, GA,
NCDOT, IN, KS, WSDOT, NB, PE, YT, AK, NV), ArcGIS (SHA CHART, SA DIT,
Main Roads WA), NDDOT alerts, Quebec 511 events, Autobahn GmbH
roadworks / warnings.

Shipped quake catalogs: USGS all_day, EMSC FDSN (min M2, depth when
published), GeoNet NZ.

## Honesty

Every entity has `freshness`. The default observatory is **simulated**
moving layers plus **reconstructed** static pins. `earth action=live`
pulls the shipped feeds in `arelis/earth/feeds.py`. Failures keep sim.
Live air and ships with a velocity coast as **dead-reckoned** after 90s,
then **stale** after 15 min. Satellites stay at the last SGP4 until the
next poll.

Viewsheds are pose priors. The inspect card says **No terrain.**
Collision and the solar tool stay **no mesh, no DEM** — approach/orbit
only, not a landing. Look-from URLs never land on entities, dumps,
cites, or `logs/reality.*`. Individual cars stay a labeled hole.
The Qt fallback sphere prefers `earth_8192.jpg` (NASA Blue Marble
shallow topo, ~5 km/px) when that file is on disk. Still a drape,
not a walk.

## Legal line

Authorization is the line. Public APIs, unofficial JSON the operator's
own map already uses, keyed feeds you pasted, and sensors you own are
in. Click look-from plays the live stream you pasted, or an official
publisher still/stream from that same JSON. An open port is not
consent. Insecam, logging into a camera you do not own, a global face
index, and a VIN/plate dragnet stay out.

## Keyed (wired, waiting on paste)

Paste into gitignored `data/secrets.yaml`. Do not wait on these to ship
no-key adapters.

| Key | Signup | Host |
|-----|--------|------|
| `earth.google_maps_key` | Google Cloud Map Tiles API — Photorealistic 3D cities. Budget alert recommended | tile.googleapis.com |
| `earth.cesium_ion_token` | https://cesium.com/ion — optional hills / Bing. Not required | ion.cesium.com / api.cesium.com |
| `earth.aisstream_key` | https://aisstream.io | stream.aisstream.io |
| `earth.barentswatch_client_id` / `_secret` | https://www.barentswatch.no | id / live.ais.barentswatch.no |
| `earth.gfw_token` | https://globalfishingwatch.org | gateway.api.globalfishingwatch.org (CC BY-NC; we stop near their rate cap) |
| `earth.firms_key` | https://firms.modaps.eosdis.nasa.gov/api/ | firms.modaps.eosdis.nasa.gov |
| `earth.aprs_key` | https://aprs.fi (My account key) | api.aprs.fi |
| `earth.spacetrack_user` / `_password` | https://www.space-track.org/auth/createAccount (.edu accepted) | www.space-track.org |
| `earth.waqi_token` | https://aqicn.org/data-platform/token/ | api.waqi.info (WAQI + originating EPA cite; local observer; do not republish) |
| `earth.opensky_client_id` / `_secret` | Account → API client → credentials.json | opensky-network.org + auth.opensky-network.org (OAuth2; Standard 4,000 credits/day; we stop near that) |
| `earth.openaq_key` | https://explore.openaq.org/register | api.openaq.org (OpenAQ + originating provider; local observer; do not republish) |
| `earth.shodan_key` | hobby; IP + banner catalog; never login, never look-from | api.shodan.io |
| `earth.drivetexas_key` | https://api.drivetexas.org/request-key — conditions + WZDx only. **No cameras** | api.drivetexas.org |
| `earth.nsw_key` | https://opendata.transport.nsw.gov.au/user/register — Live Traffic cameras, header `apikey TOKEN` | api.transport.nsw.gov.au |
| `earth.wsdot_access_code` | https://wsdot.wa.gov/traffic/api/ — cameras + highway alerts | wsdot.wa.gov |
| `earth.ohgo_key` | https://publicapi.ohgo.com/ — cameras + incidents + construction. Header `APIKEY` | publicapi.ohgo.com |
| `earth.drivenc_key` | https://drivenc.gov/my511/register — cameras (WZDx already ships) | drivenc.gov |
| `earth.cars_keys` | Travel-IQ `/my511/register` on each host — cameras + events. WZDx already ships where listed | udottraffic.utah.gov, az511.gov, 511.idaho.gov, 511wi.gov, 511la.org, 511.alaska.gov, nvroads.com, ctroads.org, 511.nebraska.gov |

OpenSky already ships anonymously; paste the API client to use
Standard (4,000 credits/day). We stop near that, or on 429.
Optional Alberta
511 developer key at https://511.alberta.ca/developers (public GET
already ships). Owned cameras: `earth.cameras` and `earth.local_camera`
(WGS84 is enough for a pin). `rtsp:` / device / HTTP only for streams
you own. Click look-from is the live feed, not a still. Never stored
on entities.

## Later (do not implement until the file is actually open)

| Id | Why it waits |
|----|----------------|
| `viirs-boats` | EOG FINAL still 401. NRT is paid. We will not buy it |
| `earthdata` | https://urs.earthdata.nasa.gov/users/new — Sentinel-1 GRD download later. Catalog footprints already ship via ASF |
| `copernicus-dataspace` | Extra Sentinel later. A scene is not a hull |

## Out (do not implement)

| Id | Why |
|----|-----|
| `sat-ais` | We will not pay for Spire / exactEarth / paid MarineTraffic |
| `unsecured-cams` | An open port is not consent |
| `face-index` | Named public search is events and assets, not faces |
| `car-vin` | There is no legal global car tracker |

## Globe

Enter Earth and Cesium takes the planet (WebEngine, source checkout +
`.[astro]` only). Arelis still paints the starfield and the sodium HUD.
The HUD glass is masked to chrome so scroll and drag belong to the
globe. Contacts on Cesium are billboards from the same mark factory,
not teardrop pins. First paint is NASA GIBS so the plate is never
black. Streets are the Streets chip (OSM). **Buildings** outlines push
to Cesium at city band when that chip is on — no house labels, no
extrusion. Photorealistic 3D cities load only after you have fallen
in, and only if `earth.google_maps_key` is set. A photoreal miss
must not kill the globe. Hills without a Cesium ion token are an
ellipsoid. The inspect card says which stack is live. Credits stay
on screen. The Qt NASA ball is the fallback when WebEngine is missing
or Cesium fails, and it is still what other planets use. No thriller
skin. No landing. Tests that only check luma are not proof of a city.

## What's next

More no-key 511 / WZDx / ArcGIS / camera inventories worldwide. More
official still CDNs on the look allowlist when a catalog already
publishes them. VIIRS only if Mines opens FINAL without a login. Do
not buy sat-AIS. Do not thin a region to hide a house. Individual
cars stay a labeled hole.

## Files

| Path | Job |
|------|-----|
| `arelis/earth/` | entity, store, runtime, frames, simulate, live, feeds, adapters |
| `arelis/earth/lod.py` | Distance bands, look box, adapter/layer gates |
| `arelis/earth/land.py` | Natural Earth country fill + state cache for landfall |
| `arelis/earth/buildings.py` | City-band Overpass footprints. Cached. Not a feed |
| `arelis/physics/telemetry.py` | Reality log + jsonl. Always on while we tune |
| `arelis/earth/owned.py` | owned face boxes in local ENU |
| `arelis/earth/look.py` | click-time look-from / listen cache; URLs never on entities |
| `arelis/earth/tiles.py` | GIBS + OSM raster cache |
| `arelis/earth/globe_stack.py` | Which pictures this copy may show |
| `arelis/ui/earth_globe/` | Cesium page (engine only, no army HUD) |
| `arelis/ui/earth_globe_host.py` | Qt WebEngine + QWebChannel + mark atlas |
| `arelis/ui/earth_marks.py` | Drawn sodium marks. Qt, Cesium, inspect, roster |
| `arelis/earth/tides.py` | CO-OPS + IOC sea-level gauges |
| `arelis/earth/argo.py` | Argo last-fix sample |
| `arelis/tools/earth_tool.py` | model surface (do not shrink the schema) |
| `arelis/ui/earth_overlay.py` | sodium paint + hit + ride eye + tiles |
| `outputs/physics/earth/` | dump receipts |

## How to run

Source checkout only (`world_stage_allowed`), Reality, solar loaded,
`pip install -e ".[astro]"`. Travel to Earth or say enter Earth.
Live is the chip / `earth action=live` / chat — not a closed verb.
