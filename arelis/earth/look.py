"""Click-time look-from and listen. Stream URLs never land on an entity.

The globe is honest: a pin without a picture is not a failure. When the
operator pasted a stream, or a publisher JSON includes an official still
or stream we are allowed to open, a click plays it. The URL lives in this
process cache only — not in meta, dumps, cites, or logs.

Owned: RTSP, local device, or HTTP MJPEG/snapshot the operator pasted.
Official: same JSON the operator's map already uses, host allowlisted.
Radio: Radio Browser directory URL, played, not stored on the pin.
Unsecured IP cameras and open ports stay out.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

# Named so tests/test_egress.py pins the still CDNs. Fetched only on click,
# only when the official catalog JSON already pointed here.
TFL_JAMCAM_STILLS = "https://jamcams.tfl.gov.uk/"
SG_TRAFFIC_STILLS = "https://images.data.gov.sg/"
FI_WEATHERCAM_STILLS = "https://weathercam.digitraffic.fi/"
AL_ALGO_STILLS = "https://api.algotraffic.com/"
AL_ALGO_HLS = "https://cdn3.wowza.com/"
DE_DELDOT_VIDEO = "https://video.deldot.gov/"
NZ_TRAFFIC_STILLS = "https://www.trafficnz.info/"
NSW_TRAFFIC_STILLS = "https://www.livetraffic.com/"
WA_WSDOT_API = "https://wsdot.wa.gov/"
WA_WSDOT_STILLS = "https://images.wsdot.wa.gov/"
OH_OHGO = "https://publicapi.ohgo.com/"
OH_OHGO_STILLS = "https://itscameras.dot.state.oh.us/"
NC_DRIVENC = "https://drivenc.gov/"
CT_ROADS = "https://ctroads.org/"
NE_511 = "https://511.nebraska.gov/"
MO_MODOT_GIS = "https://mapping.modot.mo.gov/"
MO_MODOT_TRAVELER = "https://traveler.modot.org/"
MO_MODOT_SFS01 = "https://sfs01-traveler.modot.mo.gov/"
MO_MODOT_SFS02 = "https://sfs02-traveler.modot.mo.gov/"
MO_MODOT_SFS03 = "https://sfs03-traveler.modot.mo.gov/"
MO_MODOT_SFS04 = "https://sfs04-traveler.modot.mo.gov/"
MO_MODOT_SFS07 = "https://sfs07-traveler.modot.mo.gov/"
MO_OZARKS = "https://s2.ozarkstrafficoneview.com/"

LookKind = Literal["owned", "official", "radio"]
LookMedia = Literal["video", "mjpeg", "still", "audio"]

_LOCK = threading.Lock()
_CACHE: dict[str, LookHandle] = {}

# Operator catalogs we already fetch for pins, plus the still CDNs those
# catalogs publish. Not a crawl. Not anyone's open port.
_STILL_PIN_URLS = (
    TFL_JAMCAM_STILLS,
    SG_TRAFFIC_STILLS,
    FI_WEATHERCAM_STILLS,
    AL_ALGO_STILLS,
    AL_ALGO_HLS,
    DE_DELDOT_VIDEO,
    NZ_TRAFFIC_STILLS,
    NSW_TRAFFIC_STILLS,
    WA_WSDOT_API,
    WA_WSDOT_STILLS,
    OH_OHGO,
    OH_OHGO_STILLS,
    NC_DRIVENC,
    CT_ROADS,
    NE_511,
    MO_MODOT_GIS,
    MO_MODOT_TRAVELER,
    MO_MODOT_SFS01,
    MO_MODOT_SFS02,
    MO_MODOT_SFS03,
    MO_MODOT_SFS04,
    MO_MODOT_SFS07,
    MO_OZARKS,
)
_OFFICIAL_HOSTS = frozenset(
    {
        *(host for url in _STILL_PIN_URLS if (host := urlparse(url).hostname)),
        "cwwp2.dot.ca.gov",
        "webcams.nyctmc.org",
        "api.data.gov.sg",
        "images.data.gov.sg",
        "tie.digitraffic.fi",
        "weathercam.digitraffic.fi",
        "static.data.gov.hk",
        "511on.ca",
        "511.gov.mb.ca",
        "511.novascotia.ca",
        "511.alberta.ca",
        "hotline.gov.sk.ca",
        "fl511.com",
        "511ny.org",
        "www.cotrip.org",
        "511ia.org",
        "511mn.org",
        "511ga.org",
        "tripcheck.com",
        "mdgeodata.md.gov",
        "travelfiles.dot.nd.gov",
        "api.algotraffic.com",
        "cdn3.wowza.com",
        "tmc.deldot.gov",
        "video.deldot.gov",
        "www.journeys.nzta.govt.nz",
        "trafficnz.info",
        "ws.mapserver.transports.gouv.qc.ca",
        "api.transport.nsw.gov.au",
        "www.livetraffic.com",
        "wsdot.wa.gov",
        "images.wsdot.wa.gov",
        "publicapi.ohgo.com",
        "itscameras.dot.state.oh.us",
        "drivenc.gov",
        "udottraffic.utah.gov",
        "az511.gov",
        "511.idaho.gov",
        "511wi.gov",
        "511la.org",
        "511.alaska.gov",
        "nvroads.com",
        "ctroads.org",
        "511.nebraska.gov",
        "mapping.modot.mo.gov",
        "traveler.modot.org",
        "sfs01-traveler.modot.mo.gov",
        "sfs02-traveler.modot.mo.gov",
        "sfs03-traveler.modot.mo.gov",
        "sfs04-traveler.modot.mo.gov",
        "sfs07-traveler.modot.mo.gov",
        "s2.ozarkstrafficoneview.com",
    }
)


@dataclass(frozen=True)
class LookHandle:
    """In-memory playable source. ``source`` is for the session, not the plate."""

    entity_id: str
    kind: LookKind
    media: LookMedia
    _source: str
    note: str = ""

    def source(self) -> str:
        return self._source

    def __repr__(self) -> str:
        return f"LookHandle({self.entity_id!r}, {self.kind}, {self.media})"


def remember(
    entity_id: str,
    *,
    kind: LookKind,
    source: str,
    media: LookMedia,
    note: str = "",
) -> LookHandle | None:
    """Keep a playable source off the entity. No-op when the source is refused."""
    eid = (entity_id or "").strip()
    raw = (source or "").strip()
    if not eid or not raw:
        return None
    if eid.startswith("shodan:"):
        return None
    if kind == "official" and not official_url_ok(raw):
        return None
    if kind == "radio" and not _http_url(raw):
        return None
    if kind == "owned" and not _owned_source_ok(raw):
        return None
    handle = LookHandle(
        entity_id=eid, kind=kind, media=media, _source=raw, note=note
    )
    with _LOCK:
        _CACHE[eid] = handle
    return handle


def offer_official(entity_id: str, *urls: str) -> LookHandle | None:
    """First allowlisted official URL wins. Video before a still."""
    ranked: list[tuple[int, str, LookMedia]] = []
    for url in urls:
        text = str(url or "").strip()
        if not text or not official_url_ok(text):
            continue
        media = media_of(text)
        rank = {"video": 0, "mjpeg": 1, "still": 2, "audio": 9}.get(media, 8)
        ranked.append((rank, text, media))
    if not ranked:
        return None
    ranked.sort(key=lambda row: row[0])
    _rank, url, media = ranked[0]
    return remember(
        entity_id,
        kind="official",
        source=url,
        media=media,
        note="publisher",
    )


def offer_owned(
    entity_id: str, *, rtsp: str = "", device: Any = None
) -> LookHandle | None:
    raw = (rtsp or "").strip()
    if raw:
        media = media_of(raw) if _http_url(raw) else "video"
        return remember(
            entity_id, kind="owned", source=raw, media=media, note="owned"
        )
    if device is None or device == "":
        return None
    try:
        index = int(device)
    except (TypeError, ValueError):
        return remember(
            entity_id,
            kind="owned",
            source=str(device),
            media="video",
            note="owned",
        )
    return remember(
        entity_id,
        kind="owned",
        source=f"device:{index}",
        media="video",
        note="owned",
    )


def offer_radio(entity_id: str, *urls: str) -> LookHandle | None:
    for url in urls:
        text = str(url or "").strip()
        if _http_url(text):
            return remember(
                entity_id,
                kind="radio",
                source=text,
                media="audio",
                note="directory",
            )
    return None


def resolve(entity_id: str) -> LookHandle | None:
    with _LOCK:
        return _CACHE.get((entity_id or "").strip())


def has_look(entity_id: str) -> bool:
    return resolve(entity_id) is not None


def forget(entity_id: str | None = None) -> None:
    with _LOCK:
        if entity_id is None:
            _CACHE.clear()
            return
        _CACHE.pop((entity_id or "").strip(), None)


def describe(entity_id: str, *, layer: str = "") -> str:
    """Caption line. Never includes a URL."""
    handle = resolve(entity_id)
    if handle is None:
        if layer == "cameras":
            return "Pin only. No picture — the globe is honest."
        if layer == "radio":
            return "Directory pin. No audio."
        return ""
    if handle.kind == "owned":
        return "Look-from: live (owned). Stream URL is not on this pin."
    if handle.media == "audio":
        return "Listen: published stream. URL is not on this pin."
    if handle.media == "still":
        return "Look-from: publisher still (refreshes). URL is not on this pin."
    return "Look-from: publisher live. URL is not on this pin."


def open_source(handle: LookHandle) -> Any:
    """Value OpenCV / Qt can open. Device indexes stay ints."""
    raw = handle.source()
    if handle.kind == "owned" and raw.startswith("device:"):
        try:
            return int(raw.split(":", 1)[1])
        except ValueError:
            return raw
    return raw


def official_url_ok(url: str) -> bool:
    """Official still/stream only. TfL jamcams may sit on an AWS path."""
    if not _http_url(url):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if _host_in(host, _OFFICIAL_HOSTS):
        return True
    path = parsed.path or ""
    if host.endswith("amazonaws.com") and "jamcams.tfl.gov.uk" in path:
        return True
    return False


def media_of(url: str) -> LookMedia:
    low = (url or "").lower()
    if any(token in low for token in ("m3u8", "hls", ".mp4", ".webm", "video")):
        return "video"
    if any(token in low for token in ("mjpeg", "mjpg", "multipart")):
        return "mjpeg"
    if any(token in low for token in (".mp3", ".aac", "audio", "stream")):
        # Official camera stills can contain "stream" in a JPEG path; keep still
        # unless it is clearly audio. Radio uses offer_radio.
        if any(token in low for token in (".mp3", ".aac", "audio/")):
            return "audio"
    return "still"


def first_url(*values: Any) -> str:
    """First non-empty string that looks like a URL. Does not validate host."""
    for value in values:
        if value is None or value == "":
            continue
        text = str(value).strip()
        if text.lower().startswith(("http://", "https://", "rtsp://")):
            return text
    return ""


def _owned_source_ok(raw: str) -> bool:
    if raw.startswith("device:"):
        return True
    low = raw.lower()
    if low.startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return True
    return False


def _http_url(url: str) -> bool:
    return (url or "").lower().startswith(("http://", "https://"))


def _host_in(host: str, pins: frozenset[str]) -> bool:
    name = host.lower()
    for pin in pins:
        if name == pin or name.endswith("." + pin):
            return True
    return False
