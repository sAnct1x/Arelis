"""Where this application is allowed to reach, written down and pinned.

The promise Arelis makes is that nothing about a user leaves their machine unless
they pointed it somewhere themselves. That is true today by construction: there is
no analytics, no crash reporter, no phone-home, no update ping. But being
accidentally correct and being reliably correct are different properties, and only
one of them survives a busy afternoon and a convenient library.

So the set of hosts this codebase can name is pinned below, each with the reason a
user's own action is what reaches it. Adding a destination is then a deliberate
act that edits this list and has to justify itself in review, rather than a line
nobody noticed.

Two honest limits, stated rather than papered over. This reads hosts written into
the source; a host assembled from configuration at runtime is invisible here, and
that is correct, because a configured host is by definition one the user chose —
their own mail server, their own phone, their own Ollama. And it proves what the
code *can* name, not what it did on any given day. It is a boundary on the design,
not a packet capture.

The README privacy section points at this file. That is the point of it: a privacy claim
worth making is one a reader can check.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import urlparse

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "arelis"

LOOPBACK = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "::1"})

# Every non-loopback host this package may name, and who asked for it.
ALLOWED: dict[str, str] = {
    # Search and reading, when the user asks a question that needs the web.
    "html.duckduckgo.com": "web_search, on a turn the user started",
    "lite.duckduckgo.com": "web_search fallback, same vendor, on a turn the user started",
    "en.wikipedia.org": "web_search encyclopedia fallback when HTML search is empty",
    # Weather, when the user asks about weather.
    "api.open-meteo.com": "weather tool; no key, no account, no identifier sent",
    # Same provider, same terms. Reached only when the profile names a city and
    # gives no coordinates, and it is sent that city name and nothing else.
    "geocoding-api.open-meteo.com": "place name -> lat/lon for a city the user typed",
    # Off by default in config and documented as off deliberately.
    "ipapi.co": "optional coarse location, opt-in via location.network.enabled",
    # Calendar and mail, reachable only once the user has pasted their own
    # OAuth client into data/secrets.yaml.
    "accounts.google.com": "Google OAuth consent, user-initiated",
    "oauth2.googleapis.com": "Google OAuth token exchange",
    "www.googleapis.com": "Google Calendar API, user-configured",
    "myaccount.google.com": "named in an error string telling a user where to revoke",
    "graph.microsoft.com": "Outlook calendar API, user-configured",
    "login.microsoftonline.com": "Microsoft OAuth, user-initiated",
    # The user's own phone, running software they installed.
    "api.sms-gate.app": "SMSGate cloud mode, if the user chose it",
    "sms-gate.app": "named in setup copy so the user can find the app",
    # Model and voice weights, downloaded once when a feature is first used and
    # gated behind allow_download in config.
    "github.com": "release assets for Kokoro, Silero, Sherpa, and the Ollama engine if missing",
    "huggingface.co": "Smart Turn v3 ONNX, once, when conversation end-of-turn first runs",
    "storage.googleapis.com": "MediaPipe hand_landmarker.task, once, when physics-room tracking starts; KYTC WZDx public bucket when earth action=live",
    # Whether a newer Arelis has been published. One unauthenticated GET a day, from an
    # installed copy only, carrying nothing but a User-Agent naming the version -- which is
    # unavoidable in an update check, since asking "is there something newer than this"
    # requires saying what this is. No answer is sent anywhere, and a source checkout never
    # asks. See arelis/update.py for what it does with the reply.
    "api.github.com": "the once-a-day update check made by an installed copy",
    # Places her own browser can be pointed, at the user's request. These are
    # navigation targets, not fetches: nothing is sent that the user did not
    # type or click.
    "www.google.com": "browser alias and search",
    "maps.google.com": "phone-friendly directions link",
    "mail.google.com": "browser alias",
    "calendar.google.com": "browser alias",
    "www.youtube.com": "browser alias and search",
    "www.amazon.com": "browser search",
    "www.reddit.com": "browser alias",
    "x.com": "browser alias",
    "www.opentable.com": "restaurant search, user asked to book",
    "resy.com": "restaurant search, user asked to book",
    # Not requests: an XML namespace identifier in a Task Scheduler document.
    "schemas.microsoft.com": "XML namespace in the scheduled-task definition",
    # Fixtures in the offline evaluation harness. Never fetched by the app.
    "example.com": "eval fixture host",
    "www.wsj.com": "eval fixture host, never requested",
    # Science catalogs, on a turn the user started. arXiv and Horizons need
    # no key. NASA APOD and ADS fire only after the user pastes a free key.
    "export.arxiv.org": "catalog arXiv search, on a turn the user started",
    "ssd.jpl.nasa.gov": "catalog JPL Horizons ephemerides, on a turn the user started",
    "earthquake.usgs.gov": "Earth-zone live quakes, only when earth action=live",
    "opensky-network.org": "Earth-zone live ADS-B, only when earth action=live",
    "aisstream.io": "Earth-zone AIS signup; keyed feed the user pasted",
    "stream.aisstream.io": "Earth-zone live AIS websocket, only when earth action=live and a free AISStream key is set",
    "meri.digitraffic.fi": "Earth-zone Fintraffic Digitraffic AIS, only when earth action=live; no key",
    "api.daac.asf.alaska.edu": "Earth-zone Sentinel-1 catalog, only when earth action=live",
    "eonet.gsfc.nasa.gov": "Earth-zone NASA EONET named events, only when earth action=live",
    "overpass-api.de": "Earth-zone OSM webcam tags, only when earth action=live",
    "overpass.kumi.systems": "Earth-zone OSM webcam Overpass fallback, only when earth action=live",
    "celestrak.org": "Earth-zone live TLE, only when earth action=live",
    "all.api.radio-browser.info": "Earth-zone Radio Browser directory, only when earth action=live",
    "de1.api.radio-browser.info": "Earth-zone Radio Browser mirror fallback, only when earth action=live",
    "api.tfl.gov.uk": "Earth-zone TfL JamCam published camera positions, only when earth action=live",
    "cwwp2.dot.ca.gov": "Earth-zone Caltrans CCTV and lane closures, only when earth action=live",
    "api.adsb.lol": "Earth-zone public military ADS-B, only when earth action=live",
    "ll.thespacedevs.com": "Earth-zone Launch Library 2 pads, only when earth action=live",
    "firms.modaps.eosdis.nasa.gov": "Earth-zone NASA FIRMS hotspots, only when earth action=live and a MAP_KEY is set",
    "api.aprs.fi": "Earth-zone APRS loc, only when earth action=live and an aprs.fi key is set",
    "aprs.fi": "credit link required by aprs.fi API terms; named in Earth cites, not fetched",
    "api.shodan.io": "Earth-zone Shodan banner catalog, only when earth action=live and a key is set; never a login",
    "webcams.nyctmc.org": "Earth-zone NYC DOT camera positions, only when earth action=live; no stills",
    "api.data.gov.sg": "Earth-zone Singapore LTA camera positions, only when earth action=live; no stills",
    "tie.digitraffic.fi": "Earth-zone Fintraffic road cameras and traffic messages, only when earth action=live",
    "static.data.gov.hk": "Earth-zone Hong Kong TD camera locations, only when earth action=live; no stills",
    "tile.openstreetmap.org": "Earth-zone optional OSM raster tiles, only when Tiles is on",
    "id.barentswatch.no": "Earth-zone BarentsWatch OAuth token, only when earth action=live and a free AIS client is set",
    "live.ais.barentswatch.no": "Earth-zone BarentsWatch AIS, only when earth action=live and a free AIS client is set",
    "gateway.api.globalfishingwatch.org": "Earth-zone GFW unmatched SAR, only when earth action=live and a token is set",
    "api.open511.gov.bc.ca": "Earth-zone DriveBC Open511 road events, only when earth action=live",
    "api.transport.nsw.gov.au": "Earth-zone NSW Live Traffic hazards, only when earth action=live",
    "api.qldtraffic.qld.gov.au": "Earth-zone QLDTraffic events, only when earth action=live",
    "trafficnz.info": "Earth-zone NZTA traffic events, only when earth action=live",
    "511on.ca": "Earth-zone Ontario 511 events, only when earth action=live",
    "511.gov.mb.ca": "Earth-zone Manitoba 511 events, only when earth action=live",
    "511.novascotia.ca": "Earth-zone Nova Scotia 511 events, only when earth action=live",
    "511.alberta.ca": "Earth-zone Alberta 511 events, only when earth action=live",
    "hotline.gov.sk.ca": "Earth-zone Saskatchewan 511 events, only when earth action=live",
    "fl511.com": "Earth-zone FL511 road events, only when earth action=live",
    "511ny.org": "Earth-zone 511ny road events, only when earth action=live",
    "www.cotrip.org": "Earth-zone COtrip 511 road events, only when earth action=live",
    "api.weather.gov": "Earth-zone NWS active alerts, only when earth action=live",
    "www.space-track.org": "Earth-zone Space-Track GP/TIP, only when earth action=live and a free account is set",
    "services.swpc.noaa.gov": "Earth-zone NOAA SWPC aurora forecast, only when earth action=live",
    "www.seismicportal.eu": "Earth-zone EMSC FDSN events, only when earth action=live",
    "network.satnogs.org": "Earth-zone SatNOGS station pins, only when earth action=live",
    "aviationweather.gov": "Earth-zone METAR and SIGMET reports, only when earth action=live",
    "www.ndbc.noaa.gov": "Earth-zone NOAA NDBC buoy catalog, only when earth action=live",
    "volcanoes.usgs.gov": "Earth-zone USGS volcano monitoring pins, only when earth action=live",
    "www.gdacs.org": "Earth-zone GDACS disaster events, only when earth action=live",
    "api.geonet.org.nz": "Earth-zone GeoNet NZ quakes, only when earth action=live",
    "udottraffic.utah.gov": "Earth-zone UDOT WZDx work zones, only when earth action=live",
    "traveler.modot.org": "Earth-zone MoDOT WZDx work zones, only when earth action=live",
    "511wi.gov": "Earth-zone WisDOT WZDx work zones, only when earth action=live",
    "511.idaho.gov": "Earth-zone ITD WZDx work zones, only when earth action=live",
    "chartimap1.sha.maryland.gov": "Earth-zone SHA CHART incidents, only when earth action=live",
    "maps.sa.gov.au": "Earth-zone SA DIT traffic events, only when earth action=live",
    "gisservices.mainroads.wa.gov.au": "Earth-zone Main Roads WA events, only when earth action=live",
    "travelfiles.dot.nd.gov": "Earth-zone NDDOT highway alerts and cameras, only when earth action=live",
    "az511.gov": "Earth-zone AZ511 WZDx work zones, only when earth action=live",
    "511la.org": "Earth-zone LADOTD WZDx work zones, only when earth action=live",
    "tripcheck.com": "Earth-zone ODOT TripCheck camera inventory, only when earth action=live",
    "mdgeodata.md.gov": "Earth-zone SHA traffic-camera GeoJSON, only when earth action=live",
    "api.tidesandcurrents.noaa.gov": "Earth-zone NOAA CO-OPS tide stations, only when earth action=live",
    "www.ioc-sealevelmonitoring.org": "Earth-zone IOC sea-level gauges, only when earth action=live",
    "erddap.ifremer.fr": "Earth-zone Argo last-fix sample, only when earth action=live",
    "api.waqi.info": "Earth-zone WAQI station AQI, only when earth action=live and a free token is set",
    "eoimages.gsfc.nasa.gov": "NASA Visible Earth Blue Marble, solar maps fetch the user started",
    "svs.gsfc.nasa.gov": "NASA SVS planet mosaics, solar maps fetch the user started",
    "raw.githubusercontent.com": "NASA 3D Resources albedo JPEGs, solar maps fetch the user started",
    "api.nasa.gov": "catalog NASA APOD, only with a key the user pasted",
    "api.adsabs.harvard.edu": "catalog NASA ADS search, only with a token the user pasted",
    # Atom XML namespace in the arXiv parser. Never fetched.
    "www.w3.org": "Atom namespace string in catalog; not a request",
}


URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\\]+")

# A destination has to be a real name to be a real destination. The first
# version of this test reported "%s", "phone_ip" and "<this-pc-lan-ip>" as
# hosts, which are setup instructions telling a user where to type their own
# phone's address — the opposite of an undisclosed egress. It also read
# "2130706433" out of a docstring explaining how that decimal form of 127.0.0.1
# is blocked. Requiring a dotted name with an alphabetic suffix removes all of
# them without an exception list to maintain.
HOSTNAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


def _hosts_named_in_source() -> dict[str, set[str]]:
    """Host -> the modules that name it, read out of the syntax tree.

    String literals rather than a regex over the file, so that a URL written in
    a comment does not count. A comment cannot open a connection.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for url in URL_IN_TEXT.findall(node.value):
                host = urlparse(url).hostname
                if not host or host in LOOPBACK or not HOSTNAME.match(host):
                    continue
                found.setdefault(host, set()).add(
                    str(path.relative_to(PACKAGE_ROOT.parent))
                )
    return found


def test_the_package_reaches_no_host_that_is_not_on_the_list() -> None:
    """A new destination fails here before it reaches a user."""
    found = _hosts_named_in_source()
    unexpected = {host: sorted(where) for host, where in found.items() if host not in ALLOWED}
    assert not unexpected, (
        "A host appears in the source that is not on the egress allowlist. If a "
        "user's own action is what reaches it, add it to ALLOWED with the reason. "
        "If nothing a user did causes this request, it does not belong in this "
        "application:\n"
        + "\n".join(f"  {host} — {', '.join(mods)}" for host, mods in sorted(unexpected.items()))
    )


def test_the_list_has_no_entries_that_nothing_uses() -> None:
    """An allowlist that outlives its code stops describing the application."""
    stale = sorted(set(ALLOWED) - set(_hosts_named_in_source()))
    assert not stale, (
        "These hosts are allowed but no longer named anywhere. Remove them so the "
        "list keeps meaning what it says:\n  " + "\n  ".join(stale)
    )


def test_no_module_reports_usage_anywhere() -> None:
    """The specific thing this application promises never to do.

    Named separately from the allowlist because it is the claim a user actually
    cares about, and because a future contributor reaching for a metrics library
    should meet a test whose name says why the answer is no.
    """
    banned = (
        "sentry_sdk", "posthog", "mixpanel", "amplitude", "segment", "analytics",
        "bugsnag", "rollbar", "datadog", "newrelic", "opentelemetry",
        "google-analytics", "googletagmanager", "plausible", "matomo",
    )
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0].lower()
                if root in banned:
                    offenders.append(f"{path.relative_to(PACKAGE_ROOT.parent)} imports {name}")
    assert not offenders, (
        "Telemetry or crash-reporting was added. Arelis reports nothing about "
        "anyone. A diagnostic bundle the user reads and sends themselves is the "
        "supported route:\n  " + "\n  ".join(offenders)
    )
