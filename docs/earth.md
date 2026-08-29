# Earth zone

Not a product title. Physics room, solar lab, travel to Earth.
You are an observer of what is broadcasting or published.

This page is the inventory and the legal line. The globe lives on a
source checkout only (`world_stage_allowed`), in the physics room, with
`pip install -e ".[astro]"`. Travel to Earth or say **enter Earth**.
Leave: **leave Earth**, travel to another body, or `earth action=leave`.

Inventory is `arelis/earth/feeds.py`: **63 shipped**, **9 keyed**,
**3 later**, **4 out**. Adapters replace a layer; they do not invent
coverage. Completeness is the anti-beacon — do not thin a region.

## What it is

A **zone** on the existing Earth globe. Store is ECEF metres. The plate is
still ECLIPJ2000; `arelis/earth/frames.py` is the handoff (including local
ENU for street frustums). Same sodium HUD. No thriller skin.

Enter: travel to Earth (warp finish), say **enter Earth**, or
`earth action=enter`. Leave: **leave Earth**, travel to another body,
or `earth action=leave` (writes a receipt). Click a contact for a sodium
inspect card (label, id, layer, freshness, source, cite). Under the HUD,
**Live**, **Tiles**, and every layer are chips — click to toggle. Chat
still works; it is not required.

Glyphs stay in the plate language: ISS ring, camera square, drone box,
people double ring, radar diamond, quake circle by magnitude, fire
dot, traffic cross, weather triangle, sites plus. Dead-reckoned tracks
get a dashed ring; stale tracks a slash. Heading ticks follow last
ECEF velocity. Do not dump Keys chrome.

## Where we are

What is on the plate is what a receiver or an operator already published.
The globe is not a US map. NYC is one municipal catalog. `merge_live`
runs adapters in parallel, then applies in a stable order.

| Want | What you actually get |
|------|------------------------|
| Every plane | OpenSky: every ADS-B squawk in the poll (cap 2500) |
| Every drone | OpenSky UAV category only. Most drones never squawk |
| Every ship | AISStream + Digitraffic Baltic + BarentsWatch (keyed). Packets a feed sent are painted. We do not buy sat-AIS |
| Gyre / ocean presence | Sentinel-1 pass footprints + GFW unmatched SAR if keyed. Not a hull name |
| Named events | NASA EONET + GDACS + USGS volcanoes on sites. Not a face index |
| Weather | Open-Meteo city pins + NWS CAP + METAR/SIGMET + SWPC aurora + NDBC + CO-OPS/IOC gauges |
| Airports | OurAirports large/medium scheduled fields. Not a live radar |
| Ocean floats | Argo last-fix *sample* (IFREMER ERDDAP, cap 80). Not a painted shell |
| Every car | **Hole.** 511 / WZDx / Open511 / official ArcGIS catalogs, not VINs |
| Every camera | TfL, Caltrans, NYC, SG LTA, Fintraffic, HK TD, Ontario 511, ODOT TripCheck, SHA/NDDOT, OSM worldwide. Positions only |
| Street tiles | Optional OSM raster when **Tiles** is on. ODbL. Cache + 2 connections |
| Every satellite | CelesTrak GNSS / weather / visual / science / comm + Starlink/OneWeb/Planet *samples*, not a painted shell |
| Military | adsb.lol public squawks. Silent airframes stay absent |
| Owned video | RTSP or local webcam you own. Face boxes in ENU, local only. WGS84 is enough for a pin |

Shipped traffic catalogs (operator JSON, not cars): Caltrans LCS, TfL
Road, Fintraffic, DriveBC Open511, NSW / QLD / NZTA, CARS 511 (ON, MB,
NS, AB, SK, FL511, 511ny, COtrip), WZDx (UDOT, KYTC, MoDOT, WisDOT,
ITD, 511ny, AZ511, LADOTD, AB, NS, SK, FL511), ArcGIS (SHA CHART, SA
DIT, Main Roads WA), NDDOT alerts.

Shipped quake catalogs: USGS all_day, EMSC FDSN (min M2, depth when
published), GeoNet NZ.

## Honesty

Every entity has `freshness`. The default observatory is **simulated**
moving layers plus **reconstructed** static pins. `earth action=live`
pulls the shipped feeds in `arelis/earth/feeds.py`. Failures keep sim.
Live air and ships with a velocity coast as **dead-reckoned** after 90s,
then **stale** after 15 min. Satellites stay at the last SGP4 until the
next poll.

## Legal line

Authorization is the line. Public APIs, unofficial JSON the operator's
own map already uses, keyed feeds you pasted, and sensors you own are
in. An open port is not consent. Insecam, logging into a camera you do
not own, a global face index, and a VIN/plate dragnet stay out.

## Keyed (wired, waiting on paste)

Paste into gitignored `data/secrets.yaml`. Do not wait on these to ship
no-key adapters.

| Key | Signup | Host |
|-----|--------|------|
| `earth.aisstream_key` | https://aisstream.io | stream.aisstream.io |
| `earth.barentswatch_client_id` / `_secret` | https://www.barentswatch.no | id / live.ais.barentswatch.no |
| `earth.gfw_token` | https://globalfishingwatch.org | gateway.api.globalfishingwatch.org |
| `earth.firms_key` | https://firms.modaps.eosdis.nasa.gov/api/ | firms.modaps.eosdis.nasa.gov |
| `earth.aprs_key` | https://aprs.fi (My account key) | api.aprs.fi |
| `earth.spacetrack_user` / `_password` | https://www.space-track.org/auth/createAccount (.edu accepted) | www.space-track.org |
| `earth.waqi_token` | https://aqicn.org/data-platform/token/ | api.waqi.info |
| `earth.openaq_key` | https://explore.openaq.org/register | api.openaq.org (adapter waits) |
| `earth.shodan_key` | hobby; banners only, never IP/body, never login | api.shodan.io |

OpenSky already ships anonymously; `earth.opensky_user` / `_password`
raises the rate limit (https://opensky-network.org). Optional Alberta
511 developer key at https://511.alberta.ca/developers (public GET
already ships). Owned cameras: `earth.cameras` and `earth.local_camera`
(WGS84 is enough for a pin). `rtsp:` only for streams you own. Never
stored on entities.

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

## What's next

More no-key 511 / WZDx / ArcGIS / camera inventories worldwide. More
honest academic JSON (INGV / GFZ text parsers if GeoJSON stays closed).
OpenAQ adapter after a paste. VIIRS only if Mines opens FINAL without
a login. Do not buy sat-AIS. Do not thin a region to hide a house.
Individual cars stay a labeled hole.

## Files

| Path | Job |
|------|-----|
| `arelis/earth/` | entity, store, runtime, frames, simulate, live, feeds, adapters |
| `arelis/earth/owned.py` | owned stills + local ENU face boxes |
| `arelis/earth/tiles.py` | OSM raster cache |
| `arelis/earth/tides.py` | CO-OPS + IOC sea-level gauges |
| `arelis/earth/argo.py` | Argo last-fix sample |
| `arelis/tools/earth_tool.py` | model surface (do not shrink the schema) |
| `arelis/ui/earth_overlay.py` | sodium paint + hit + ride eye + tiles |
| `outputs/physics/earth/` | dump receipts |

## How to run

Source checkout only (`world_stage_allowed`), physics room, solar
loaded, `pip install -e ".[astro]"`. Travel to Earth or say enter Earth.
Live is the chip / `earth action=live` / chat — not a closed verb.
