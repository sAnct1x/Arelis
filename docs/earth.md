# Earth zone

Not a product title. Physics room, solar lab, travel to Earth.
You are an observer of what is broadcasting or published.

Living notes for the next session. Canvases live beside chat in the
IDE folder `C:/Users/you/.cursor/projects/Arelis/canvases/`
(earth-hub, earth-layers, earth-runtime, earth-build). They are not
in this repo.

## What it is

A **zone** on the existing Earth globe. Store is ECEF metres. The plate is
still ECLIPJ2000; `arelis/earth/frames.py` is the handoff (including local
ENU for street frustums). Same sodium HUD. No thriller skin.

Enter: travel to Earth (warp finish), say **enter Earth**, or
`earth action=enter`. Leave: **leave Earth**, travel to another body,
or `earth action=leave` (writes a receipt). Click a contact for a sodium
inspect card. Under the HUD, **Live**, **Tiles**, and every layer are
chips — click to toggle. Chat still works; it is not required.

## Observer ceiling

What is on the plate is what a receiver or an operator already published.
The globe is not a US map. NYC is one municipal catalog.

| Want | What you actually get |
|------|------------------------|
| Every plane | OpenSky: every ADS-B squawk in the poll (cap 2500) |
| Every drone | OpenSky UAV category only. Most drones never squawk |
| Every ship | AISStream + Digitraffic Baltic + BarentsWatch (keyed). Packets a feed sent are painted. We do not buy sat-AIS |
| Gyre / ocean presence | Sentinel-1 pass footprints + GFW unmatched SAR if keyed. Not a hull name |
| Named events | NASA EONET open events on sites. Not a face index |
| Every car | **Hole.** Caltrans LCS + TfL + Fintraffic messages, not VINs |
| Every camera | TfL, Caltrans, NYC, Singapore LTA, Fintraffic, Hong Kong TD, OSM worldwide. Positions only |
| Street tiles | Optional OSM raster when **Tiles** is on. ODbL. Cache + 2 connections |
| Every satellite | CelesTrak groups + Starlink/OneWeb *samples*, not a painted shell |
| Military | adsb.lol public squawks. Silent airframes stay absent |
| Owned video | RTSP or local webcam you own. Face boxes in ENU, local only |

## Honesty

Every entity has `freshness`. The default observatory is **simulated**
moving layers plus **reconstructed** static pins. `earth action=live`
pulls the shipped feeds in `arelis/earth/feeds.py`. Failures keep sim.

## Legal line

Authorization is the line. Public APIs, unofficial JSON the operator's
own map already uses, keyed feeds you pasted, and sensors you own are
in. An open port is not consent. Insecam, logging into a camera you do
not own, a global face index, and a VIN/plate dragnet stay out.

AIS key: `earth.aisstream_key` or `ARELIS_AISSTREAM_KEY`.
BarentsWatch: `earth.barentswatch_client_id` / `_secret` (free AIS client).
GFW: `earth.gfw_token` (CC BY-NC, local observer).
FIRMS: `earth.firms_key`.
Owned cameras: `earth.cameras` and optional `earth.local_camera` (device
index + WGS84). `rtsp:` only for streams you own. Never stored on entities.

## Files

| Path | Job |
|------|-----|
| `arelis/earth/` | entity, store, runtime, frames, simulate, live, feeds, adapters |
| `arelis/earth/owned.py` | owned stills + local ENU face boxes |
| `arelis/earth/tiles.py` | OSM raster cache |
| `arelis/tools/earth_tool.py` | model surface |
| `arelis/ui/earth_overlay.py` | sodium paint + hit + ride eye + tiles |
| `outputs/physics/earth/` | dump receipts |

## Next

More national 511 JSON. VIIRS boat lights if Mines actually opens.
Adapters replace a layer; they do not invent coverage. Individual cars
stay a labeled hole. We do not buy satellite AIS.
