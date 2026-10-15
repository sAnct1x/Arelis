"""No tracked file may carry anything that identifies a real person.

This repo is going public. A tracked file is public the instant it is pushed, and
a mistake found a month later is permanent — deleting the file does not remove it
from anyone's clone or from the forks. "Remember not to paste a real number into a
fixture" is not a strategy that survives a tired evening, so it is a machine's job
instead of a person's discipline.

The checks come in two kinds.

The *shape* rules below need no knowledge of who anyone is: a path under a real
Windows home directory, a phone number outside the ranges reserved for fiction, a
personal mailbox at a consumer provider, a credential with a value in it, and a
place — coordinates, a US state, a postal code — that is not the one fixture
place this project declares. Those run everywhere, including CI, and they are
what protects a contributor who has never heard of this file.

The *name* rules read `data/scrub-names.local.txt`, which
`scripts/build_scrub_list.py` generates from the operator's own contacts and
profile and which `.gitignore` keeps local. They are skipped when that file is
absent. Putting the names in a tracked test would have published them, which is
the leak this test exists to prevent.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRUB_LIST = PROJECT_ROOT / "data" / "scrub-names.local.txt"
# Terms a user may legitimately need to allow back: a place name that is also a
# library, a surname that is also a common word.
SCRUB_ALLOW = PROJECT_ROOT / "data" / "scrub-allow.local.txt"

BINARY_SUFFIXES = frozenset(
    {".ico", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ttf", ".otf", ".woff",
     ".woff2", ".zip", ".db", ".onnx", ".bin", ".jar", ".keystore"}
)

# This file necessarily contains examples of every pattern it bans.
SELF = Path(__file__).name


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        pytest.skip("git is not available, so the tracked file list is unknowable")
    return [PROJECT_ROOT / line for line in out.stdout.splitlines() if line.strip()]


def _readable_tracked() -> list[tuple[Path, str]]:
    """Tracked text files and their contents, with this file excluded."""
    files: list[tuple[Path, str]] = []
    for path in _tracked_files():
        if path.suffix.lower() in BINARY_SUFFIXES or path.name == SELF:
            continue
        try:
            files.append((path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    return files


def _report(hits: list[str]) -> str:
    """Name the file and line, never the matched text.

    A failure message that quoted the value would print a private phone number
    into CI logs, which are more public than the commit would have been.
    """
    listed = "\n".join(f"  {hit}" for hit in sorted(hits)[:40])
    more = f"\n  … and {len(hits) - 40} more" if len(hits) > 40 else ""
    return listed + more


# ---------------------------------------------------------------- shape rules

# A home directory named after a real Windows account. Placeholders are the
# whole point of a placeholder, so they are allowed by name.
HOME_PATH = re.compile(r"(?i)[a-z]:[\\/]users[\\/]([a-z0-9._-]+)")
HOME_PLACEHOLDERS = frozenset(
    {"you", "your", "user", "username", "name", "x", "xxx", "someone", "example",
     "public", "default", "all users", "%username%"}
)


# Scoped to North American numbers on purpose. A bare run of ten digits is not
# enough to go on — this repo contains Windows exit codes, IP addresses and
# timestamps that are all ten digits long, and the first version of this test
# flagged every one of them. What separates a phone number from a large integer
# is the numbering plan's own rules: an area code and an exchange both have to
# start with 2-9. Applying them turns a noisy heuristic into a precise one.
#
# The limit that buys: a number in a country with different rules would not be
# caught here. The name check below covers the operator's own contacts wherever
# they live, and this rule is what protects a contributor who has no scrub list.
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# And digests, for the same reason one step further out. A sha256 is 64 hex characters,
# so roughly four in ten of them contain a run of ten digits somewhere, and a run
# preceded by a letter satisfies the lookbehind below as readily as one at the start of
# a line. The installer's lockfile is 76 of them and tripped this three times.
#
# Safe to blank because the thing being looked for cannot be in here: a phone number
# nobody should publish does not arrive embedded in a 32-character hexadecimal string.
# Deliberately not `[0-9a-fA-F]` and deliberately 32 rather than a smaller bound --
# tight enough that it blanks digests and nothing that reads like prose.
HEX_DIGEST = re.compile(r"\b[0-9a-f]{32,}\b")
# The lookbehind rejects a dot, the lookahead does not, and the asymmetry is
# deliberate. A dot *before* the digits means they are the fractional part of a
# decimal — a latitude, a version. A dot *after* them is a full stop ending a
# sentence, and excluding that let a real number sitting at the end of an
# assertion message through on the first run.
PHONE = re.compile(
    r"(?<![\d.])(?:\+?1[\s.-]?)?"
    r"\(?([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})"
    r"(?!\d)"
)


def _is_reserved(area: str, exchange: str, line_number: str) -> bool:
    """True for the ranges that exist so fiction can print a number safely.

    A 555 area code is not dialable at all, and 555-0100..555-0199 is the block
    reserved for use in film and television.
    """
    if area == "555":
        return True
    return exchange == "555" and line_number.startswith("01")


def test_blanking_digests_did_not_open_a_hole_in_the_phone_rule() -> None:
    """How wide the digest strip is, since a strip in a guard is a hole by definition.

    The digest below is msal's line from the installer lockfile, one of three that
    failed this rule. It contains 8108113438: a valid area code, a valid exchange, four
    more digits, and a letter on either side satisfying both the lookbehind and the
    lookahead. So the first assertion is that the strip is needed at all, and the rest
    are that it did not take the rule with it.
    """
    digest = "dd17e95a7c71bce75e8108113438ba7c4a086b3bcad4f57a8c09b7af3d753c2d"
    real = "416-987-6543"

    def flagged(line: str) -> list[tuple[str, str, str]]:
        return PHONE.findall(HEX_DIGEST.sub(" ", IPV4.sub(" ", line)))

    assert PHONE.findall(digest), "the digest no longer trips the rule; pick another one"
    assert not flagged(f"msal==1.37.0 --hash=sha256:{digest}")
    assert flagged(f"reach me on {real}")
    assert flagged(real.replace("-", ""))
    assert flagged(f"msal==1.37.0 --hash=sha256:{digest}  {real}"), (
        "a number on the same line as a digest has to still be caught"
    )


CONSUMER_MAIL = re.compile(
    r"(?i)\b([a-z0-9._%+-]+)@(gmail|googlemail|outlook|hotmail|live|yahoo|"
    r"ymail|icloud|me|aol|proton|protonmail|gmx|mail)\.[a-z.]{2,}\b"
)
MAILBOX_PLACEHOLDERS = frozenset(
    {"you", "your", "user", "username", "name", "me", "someone", "somebody",
     "example", "test", "sender", "recipient", "person", "first.last", "a", "b",
     "x", "w", "no-reply", "noreply"}
)


# Deliberately not a guess at what a secret looks like. Nothing can tell a real
# app password from a convincing fake by shape, and trying produced exactly the
# wrong answer: it flagged the test that proves app passwords parse correctly,
# which has to contain something realistically shaped in order to test anything.
#
# So the question is narrowed to where it is decidable. A test is allowed a fake
# credential because that is what a fixture is for. Config, documentation and
# shipped code are not, because nothing there needs one, and a value that turns
# up in them is far more likely to be somebody's real key pasted in a hurry.
CREDENTIAL = re.compile(
    r"(?i)\b(password|passwd|app_password|secret|client_secret|token|"
    r"api[_-]?key|ingest_token|refresh_token)\b\s*[:=]\s*"
    r"[\"']([^\"'\n]{6,})[\"']"
)
CREDENTIAL_PLACEHOLDERS = re.compile(
    r"(?i)^(|\s*|x+|\.+|<.*>|\{.*\}|\$.*|%.*%|.*example.*|.*your.*|.*placeholder.*"
    r"|.*redacted.*|.*dummy.*|.*fake.*|.*changeme.*|.*[a-z_]+_here.*"
    r"|secret|token|password|id|rt|abc\w*|test\w*|some\w*)$"
)


# ---------------------------------------------------------------- place rules

# One fixture place for the whole tree, declared once, here.
#
# Springfield, Illinois: a state capital, the stock example city in American
# writing, and a published civic reference point rather than anybody's address.
# The rules below exist because the tree held two different fixture places at
# the same time — one set had been scrubbed and another had not, so they
# disagreed, and the disagreement was the only reason anyone looked.
FIXTURE_STATE = "Illinois"
FIXTURE_POSTAL = "62701"

# Magnitudes, because a sign is not what identifies a place. A candidate passes
# when it is a *prefix* of one of these, which is what lets a file write the same
# place to two decimals instead of four without needing a second entry.
FIXTURE_COORDS = frozenset({"39.7817", "89.6501"})
# San Francisco, the most widely published pair in existence. Two tests need a
# place that is deliberately not the fixture: one proves the profile beats
# coordinates a model invented, the other proves a per-field merge can keep the
# city from the profile while taking coordinates from an IP lookup. Both need
# somewhere to be wrong about.
DECOY_COORDS = frozenset({"37.7749", "122.4194"})
ALLOWED_COORDS = FIXTURE_COORDS | DECOY_COORDS

# Whole words only. "calculator" contains "lat", and so does "latency"; the
# first version of this matched both and reported a calculator expression as a
# leaked position, which is precisely how a rule earns its way onto the list of
# things everyone ignores.
COORD_CONTEXT = re.compile(
    r"(?i)(?<![a-z])(?:lat|lon|lats|lons|latitude|longitude|coord|coords|"
    r"coordinate|coordinates|geo|geocode|loc)(?![a-z])"
)
# One to three digits before the point and at least two after it. Refusing a
# leading zero is what stops a rate of 0.25, sitting on a line that happens to
# mention a location, from being reported as somebody's house. The price is a
# coordinate within one degree of the equator or the prime meridian, which the
# name rules still cover for the operator's own.
COORDINATE = re.compile(r"\b(?!0\.)\d{1,3}\.\d{2,}\b")
# A bare pair is unmistakable without any context word to help.
COORD_PAIR = re.compile(
    r"\b(?!0\.)\d{1,3}\.\d{2,}\s*,\s*-?(?!0\.)\d{1,3}\.\d{2,}\b"
)
# GLSL RGB / sample positions look like lat,lon pairs: vec3(1.42, 1.24, 0.90).
# Strip those literals before the pair rule runs, or every shader commit fails
# the place guard and CI goes red for a colour, not a house.
GLSL_VEC = re.compile(r"\bvec[234]\s*\([^)]*\)")

US_STATES = frozenset(
    {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming",
    }
)


def _state_pattern(states: frozenset[str]) -> re.Pattern[str]:
    """Match these state names as whole words, spaces meaning any whitespace.

    A space rather than a permissive separator on purpose: it leaves
    ``America/New_York`` unmatched, and an IANA timezone is a statement about
    a clock rather than about where anybody lives.
    """
    names = sorted(states, key=len, reverse=True)
    alternation = "|".join(name.replace(" ", r"\s+") for name in names)
    return re.compile(rf"(?i)(?<![a-z.])(?:{alternation})(?![a-z.])")


ANY_STATE = _state_pattern(US_STATES)
FOREIGN_STATE = _state_pattern(frozenset(US_STATES - {FIXTURE_STATE.lower()}))

# The key form, not the bare word, so Python's own zip() is left alone.
POSTAL_KEY = re.compile(
    r"(?i)(?<![a-z])(?:zip|postal|postcode|postal_code|post_code)[\"']?\s*[:=]"
)
POSTAL = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def _coordinates_on(line: str) -> list[str]:
    """Decimals on this line being used as a position rather than as a number."""
    stripped = GLSL_VEC.sub(" ", line)
    if COORD_PAIR.search(stripped) or COORD_CONTEXT.search(stripped):
        return COORDINATE.findall(stripped)
    return []


def _public_globe(path: Path) -> bool:
    """Earth-zone catalog: published city/port pins, not a house.

    The rest of the tree still has one fixture place. The globe cannot.
    """
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    return (
        rel.startswith("arelis/earth/")
        or rel.startswith("tests/fixtures/earth/")
        or rel in {
        "tests/test_earth.py",
        "tests/test_earth_goto.py",
        "tests/test_egress.py",
        "tests/test_earth_inspect.py",
        "tests/test_earth_field.py",
        "tests/test_earth_polish.py",
        "tests/test_earth_audit.py",
        "tests/test_earth_break.py",
        "tests/test_globe_stack.py",
        "docs/roadmap/earth-reality.md",
        "arelis/ui/earth_globe/bridge.js",
        "docs/earth.md",
        "data/secrets.example.yaml",
        # Public US gazetteer: "Baltimore, OH" vs "baltimore ohio".
        "arelis/tools/weather.py",
        "tests/test_weather_tool.py",
        }
    )


def _is_allowed_coordinate(value: str) -> bool:
    return any(allowed.startswith(value) for allowed in ALLOWED_COORDS)


# ----------------------------------------------------------------- name rules


def _local_terms(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


# SHA-256 of the lowercased surname. The letters are not stored. A word is a
# run of ASCII letters, so punctuation beside the name does not hide it, and
# capitalization does not either. This file is included in the scan: the hash
# means the check no longer has to spell what it forbids.
_SURNAME_SHA256 = "6d09c24b943ecae5a22ee52595fb0f0556d17d62ae14b5c0b07df540d582a61c"
_LETTER_WORD = re.compile(r"[A-Za-z]+")


