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

`docs/your-data.md` points at this file. That is the point of it: a privacy claim
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
    "github.com": "release assets for Kokoro, Silero and Sherpa weights",
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
