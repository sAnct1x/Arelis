"""Fail when the text of a pull request or issue carries personal data.

Why this exists: `tests/test_no_personal_data.py` guards what is committed. It cannot see
what is typed into GitHub. A pull request description once carried a local Windows path
(with the PC username in it), and nothing looked at it. This script is the missing check
for PR and issue titles, bodies and comments.

What it looks for, and nothing else:

    local path        C:\\Users\\<name>\\, C:/Users/<name>/, /Users/<name>/, /home/<name>/
    PC username       names listed in the optional env var PRIVACY_CHECK_USERNAMES
    email             any address that is not an obvious placeholder
    phone number      US/Canada and international (+ prefix), with false-positive guards
    token or key      ghp_/gho_/ghs_/github_pat_, sk-, Bearer, AKIA, xox*, labeled key=value
    street address    HEURISTIC: number + street name + suffix (St, Ave, Rd ...), or a PO box

Hard rule: the output names a category and a place ("email found in PR body, line 3")
and never the matched text. A CI log is more public than the thing it was protecting.
Every pattern lives in this file, in the block marked PATTERNS, so a reviewer reads one
page, not five.

Input never goes through a shell. The workflow hands this script GITHUB_EVENT_PATH (a JSON
file the runner writes) and files of API results. Text can also come from named env vars
or a JSON file for local use. Exit codes: 0 clean, 1 something found, 2 input unreadable
(which also fails the job: a check that cannot read its input must not pass).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# ----------------------------------------------------------------------------- PATTERNS

# --- local paths -------------------------------------------------------------------
# A name segment ends at a separator, whitespace, quote, bracket, or a character that a
# placeholder uses (<name>, {name}, $USER, %USERNAME%). Placeholders therefore never
# produce a name at all; the set below catches the plain-word ones.
_PATH_NAME = r"([^\\/\s\"'`<>|:*?()\[\]{}$%,;]+)"
WIN_HOME_PATH = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]+Users[\\/]+" + _PATH_NAME, re.IGNORECASE
)
UNIX_HOME_PATH = re.compile(r"(?<![A-Za-z0-9_.~:/\\-])/(?:Users|home)/+" + _PATH_NAME)

# Account names that identify nobody: documentation words and the generic accounts that
# CI images and installers create.
GENERIC_ACCOUNT_NAMES = frozenset(
    {
        "you", "your", "yours", "me", "user", "username", "yourname", "myname", "name",
        "someone", "somebody", "example", "foo", "bar", "test", "testuser", "x", "xx",
        "xxx", "public", "default", "defaultuser0", "all", "shared", "guest", "admin",
        "administrator", "root", "runner", "runneradmin", "vsts", "ubuntu", "ec2-user",
        "vagrant", "docker", "jenkins", "circleci", "appveyor", "builder",
    }
)  # fmt: skip
_PLACEHOLDER_SHAPES = re.compile(
    r"(?:[-_.*x]+|(?:your|my|the)?[-_]?(?:user[-_]?)?name\d*|user\d*|account\d*)",
    re.IGNORECASE,
)

# --- emails ------------------------------------------------------------------------
EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b"
)
EMAIL_PLACEHOLDER_LOCALS = frozenset(
    {
        "you", "your", "user", "username", "name", "someone", "somebody", "email", "mail",
        "me", "foo", "bar", "test", "first.last", "firstname.lastname", "sender",
        "recipient", "person", "git", "noreply", "no-reply", "donotreply", "do-not-reply",
    }
)  # fmt: skip
# RFC 2606 reserved names, plus file suffixes that read like a domain (image@2x.png).
EMAIL_RESERVED_LABELS = frozenset({"example", "invalid", "localhost", "test"})
EMAIL_FILE_SUFFIXES = frozenset(
    {
        "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "ts", "py", "json",
        "md", "txt", "yml", "yaml", "html", "toml", "cfg", "ini", "lock", "log", "pdf",
    }
)  # fmt: skip

# --- phone numbers -----------------------------------------------------------------
# North American: area code and exchange both start 2-9, which is the numbering plan's own
# rule and what separates a phone number from a large integer. Formatted numbers (a
# dash, dot, parentheses, or a +1) are flagged anywhere; ten bare digits, or digits split
# by spaces only, are flagged only right after a word like "phone" or "call", because
# those shapes are ids, hashes, timestamps and columns of counts.
PHONE_NANP = re.compile(
    r"(?<![\w.+/#=-])(\+?1[\s.-]?)?(?:(\()([2-9]\d{2})\)|([2-9]\d{2}))"
    r"([\s.-]?)([2-9]\d{2})([\s.-]?)(\d{4})(?![\w-]|\.\d)"
)
PHONE_CONTEXT = re.compile(
    r"(?i)\b(?:phone|tel|telephone|call|cell|mobile|fax|sms|text|whatsapp|contact)\b[^\n]{0,20}$"
)
# International: a plus sign, a country code, 9 to 15 digits in all. +1 is left to the
# North American rule above.
PHONE_INTL = re.compile(r"(?<![\w.+/#=-])\+\d[\d\s().-]{7,20}\d(?![\w-]|\.\d)")
PHONE_DIFF_STAT = re.compile(r"\s-\d")  # "+12000 -30000" in a diffstat is not a phone number

# --- tokens and keys ---------------------------------------------------------------
GITHUB_TOKEN = re.compile(r"(?<![A-Za-z0-9])gh[pousr]_([A-Za-z0-9]{20,})")
GITHUB_FINE_GRAINED = re.compile(r"(?<![A-Za-z0-9])github_pat_([A-Za-z0-9_]{22,})")
SK_KEY = re.compile(r"(?<![A-Za-z0-9])sk-([A-Za-z0-9_-]{20,})")
BEARER = re.compile(r"(?i)\bbearer[ \t]+([A-Za-z0-9._~+/=-]{16,})")
AWS_KEY = re.compile(r"(?<![A-Za-z0-9])(?:AKIA|ASIA)([0-9A-Z]{16})(?![A-Za-z0-9])")
SLACK_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:xox[abprs]|xapp)-([A-Za-z0-9-]{10,})")
JWT = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")
# Long hex or base64 counts only when something says it is a secret: key=..., token: ...
LABELED_SECRET = re.compile(
    r"(?i)[\w-]*(?:api[_-]?key|secret|token|passw(?:or)?d|access[_-]?key|private[_-]?key"
    r"|auth)[\w-]*[ \t]*[:=][ \t]*[\"']?([A-Za-z0-9+/_=-]{32,})"
)
FILL_WORDS = ("example", "placeholder", "redacted", "dummy", "fake", "changeme", "yourtoken")

# --- street addresses (HEURISTIC) -------------------------------------------------
_SUFFIXES = (
    "Street", "St", "Avenue", "Ave", "Road", "Rd", "Boulevard", "Blvd", "Drive", "Dr",
    "Lane", "Ln", "Court", "Ct", "Parkway", "Pkwy", "Terrace", "Ter", "Circle", "Cir",
    "Place", "Pl",
)  # fmt: skip
_SUFFIX_ALT = "|".join(sorted({f(s) for s in _SUFFIXES for f in (str, str.upper)}, key=len, reverse=True))
_NAME_WORD = r"(?:[A-Z][A-Za-z'\u2019-]*|\d{1,3}(?:st|nd|rd|th))"
STREET_ADDRESS = re.compile(
    r"(?<![\w#.:/\\$-])(\d{1,6})[ \t]+"
    r"(?:(?:N|S|E|W|NE|NW|SE|SW|North|South|East|West)\.?[ \t]+)?"
    rf"((?:{_NAME_WORD}[ \t]+){{1,3}})({_SUFFIX_ALT})\b"
)
PO_BOX = re.compile(r"(?i)(?<![A-Za-z])P\.?[ \t]?O\.?[ \t]+Box[ \t]+\d+")
# Words that make "<number> <words> Drive/Court" a product or a thing, not a street.
NOT_A_STREET_WORD = frozenset(
    {
        "Google", "Dev", "Hard", "Flash", "USB", "Test", "Disk", "Disc", "Network", "Cloud",
        "Shared", "Virtual", "RAM", "SSD", "Optical", "Mapped", "Local", "External",
        "Internal", "Boot", "System", "Supreme", "Food", "OneDrive", "Pen", "Thumb",
    }
)  # fmt: skip

# ------------------------------------------------------------------------ end of PATTERNS

CATEGORY_PATH = "local path"
CATEGORY_USERNAME = "PC username"
CATEGORY_EMAIL = "email"
CATEGORY_PHONE = "phone number"
CATEGORY_SECRET = "token or key"
CATEGORY_ADDRESS = "street address (heuristic)"

MAX_REPORT_LINES = 50
MIN_USERNAME_LENGTH = 3


@dataclass(frozen=True)
class Hit:
    """A category and a line number. Deliberately holds no matched text."""

    category: str
    line: int


@dataclass(frozen=True)
class Item:
    """One piece of text to scan and the human name of where it came from."""

    location: str
    text: str


Detector = Callable[[str, "re.Pattern[str] | None"], bool]


# ------------------------------------------------------------------------------ detectors


def _is_placeholder_name(name: str) -> bool:
    lowered = name.lower().strip(".")
    if not lowered or lowered in GENERIC_ACCOUNT_NAMES:
        return True
    return bool(_PLACEHOLDER_SHAPES.fullmatch(lowered))


def _detect_paths(line: str, usernames: re.Pattern[str] | None) -> bool:
    for pattern in (WIN_HOME_PATH, UNIX_HOME_PATH):
        for match in pattern.finditer(line):
            if not _is_placeholder_name(match.group(1)):
                return True
    return False


def _detect_username(line: str, usernames: re.Pattern[str] | None) -> bool:
    return usernames is not None and usernames.search(line) is not None


def _detect_email(line: str, usernames: re.Pattern[str] | None) -> bool:
    for match in EMAIL.finditer(line):
        local, domain = match.group(1).lower(), match.group(2).lower()
        labels = domain.split(".")
        if local in EMAIL_PLACEHOLDER_LOCALS or "noreply" in local or "no-reply" in local:
            continue
        if domain.endswith("noreply.github.com"):
            continue
        if any(label in EMAIL_RESERVED_LABELS for label in labels):
            continue
        if labels[-1] in EMAIL_FILE_SUFFIXES:
            continue
        return True
    return False


def _is_reserved_fiction(area: str, exchange: str, line_number: str) -> bool:
    """555 area codes and 555-01xx are set aside for fiction, and the repo uses them."""
    return area == "555" or (exchange == "555" and line_number.startswith("01"))


def _detect_phone(line: str, usernames: re.Pattern[str] | None) -> bool:
    for match in PHONE_NANP.finditer(line):
        prefix, paren, area_p, area_b, sep1, exchange, sep2, number = match.groups()
        area = area_p or area_b
        if _is_reserved_fiction(area, exchange, number):
            continue
        # Parentheses, a plus, a dash or a dot are strong signals. Spaces alone are not:
        # Three space-separated numbers are as likely a column of counts as a phone number,
        # so they need a phone word before them.
        strong = bool(prefix and "+" in prefix) or bool(paren) or any(c in "-." for c in sep1 + sep2)
        if strong or PHONE_CONTEXT.search(line[: match.start()]):
            return True
    for match in PHONE_INTL.finditer(line):
        candidate = match.group(0)
        digits = re.sub(r"\D", "", candidate)
        if not 9 <= len(digits) <= 15 or digits.startswith("1"):
            continue
        if PHONE_DIFF_STAT.search(candidate):
            continue
        country_group = re.match(r"\+(\d+)", candidate)
        spaced = bool(re.search(r"[\s().-]", candidate))
        if spaced and country_group and len(country_group.group(1)) > 3:
            continue  # "+2000 30000" is a count, not a country code
        return True
    return False


def _is_fill(value: str) -> bool:
    """True for a value that is clearly a stand-in: one repeated character or a fill word."""
    lowered = value.lower()
    if len(set(lowered)) <= 2:
        return True
    return any(word in lowered for word in FILL_WORDS) or "xxxx" in lowered


def _detect_secret(line: str, usernames: re.Pattern[str] | None) -> bool:
    for pattern in (GITHUB_TOKEN, GITHUB_FINE_GRAINED, SLACK_TOKEN):
        for match in pattern.finditer(line):
            if not _is_fill(match.group(1)):
                return True
    for match in SK_KEY.finditer(line):
        body = match.group(1)
        long_run = re.search(r"[A-Za-z0-9]{16,}", body)
        if long_run and re.search(r"\d", body) and not _is_fill(body):
            return True
    for match in BEARER.finditer(line):
        value = match.group(1)
        if re.search(r"\d", value) and re.search(r"[A-Za-z]", value) and not _is_fill(value):
            return True
    for match in AWS_KEY.finditer(line):
        if not _is_fill(match.group(1)) and not match.group(1).endswith("EXAMPLE"):
            return True
    if JWT.search(line) or PRIVATE_KEY_BLOCK.search(line):
        return True
    for match in LABELED_SECRET.finditer(line):
        value = match.group(1)
        if re.search(r"\d", value) and re.search(r"[A-Za-z]", value) and not _is_fill(value):
            return True
    return False


def _detect_address(line: str, usernames: re.Pattern[str] | None) -> bool:
    if PO_BOX.search(line):
        return True
    for match in STREET_ADDRESS.finditer(line):
        words = match.group(2).split()
        if any(word in NOT_A_STREET_WORD for word in words):
            continue
        return True
    return False


# The one list that decides what is checked. A test swaps it out to prove the suite fails
# without it.
DETECTORS: tuple[tuple[str, Detector], ...] = (
    (CATEGORY_PATH, _detect_paths),
    (CATEGORY_USERNAME, _detect_username),
    (CATEGORY_EMAIL, _detect_email),
    (CATEGORY_PHONE, _detect_phone),
    (CATEGORY_SECRET, _detect_secret),
    (CATEGORY_ADDRESS, _detect_address),
)


# ---------------------------------------------------------------------------- scanning


def parse_usernames(raw: str | None) -> tuple[re.Pattern[str] | None, int]:
    """Build the whole-word, case-insensitive username matcher.

    Returns (matcher or None, count of entries ignored for being too short). Nothing here
    is ever printed. Entries under three characters are dropped because they would match
    inside ordinary words, and the count of dropped entries is all anyone is told.
    """
    if not raw:
        return None, 0
    names: list[str] = []
    ignored = 0
    for part in re.split(r"[,\n;]", raw):
        name = part.strip()
        if not name:
            continue
        if len(name) < MIN_USERNAME_LENGTH:
            ignored += 1
            continue
        if name.lower() not in (n.lower() for n in names):
            names.append(name)
    if not names:
        return None, ignored
    alternation = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alternation})(?![A-Za-z0-9])", re.IGNORECASE), ignored


def scan_text(text: str, usernames: re.Pattern[str] | None = None) -> list[Hit]:
    """Every (category, line) hit in this text. Never returns the matched text."""
    hits: list[Hit] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for category, detect in DETECTORS:
            if detect(line, usernames):
                hits.append(Hit(category, number))
    return hits


# ------------------------------------------------------------------------------- input


class InputError(Exception):
    """The input could not be read. The message never carries any of the text."""


def _clean(value: object) -> str:
    return value if isinstance(value, str) else ""


def _comment_label(prefix: str, ident: object) -> str:
    # An id is a number GitHub made up; anything else is dropped rather than echoed.
    return f"{prefix} {ident}" if isinstance(ident, int) and not isinstance(ident, bool) else prefix


def items_from_event(event_name: str, event: dict) -> list[Item]:
    """The text a webhook payload carries, labelled by where a person would look for it."""
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        return [
            Item("PR title", _clean(pr.get("title"))),
            Item("PR body", _clean(pr.get("body"))),
        ]
    if event_name == "issues":
        issue = event.get("issue") or {}
        return [
            Item("issue title", _clean(issue.get("title"))),
            Item("issue body", _clean(issue.get("body"))),
        ]
    if event_name == "issue_comment":
        on_pr = bool((event.get("issue") or {}).get("pull_request"))
        comment = event.get("comment") or {}
        label = _comment_label("PR comment" if on_pr else "issue comment", comment.get("id"))
        return [Item(label, _clean(comment.get("body")))]
    if event_name == "pull_request_review_comment":
        comment = event.get("comment") or {}
        label = _comment_label("PR review comment", comment.get("id"))
        return [Item(label, _clean(comment.get("body")))]
    if event_name == "pull_request_review":
        review = event.get("review") or {}
        return [Item(_comment_label("PR review", review.get("id")), _clean(review.get("body")))]
    raise InputError(f"event type {event_name!r} is not one this check handles")


def _json_values(raw: str) -> Iterator[object]:
    """Yield every JSON value in a stream: one document, JSON lines, or paginated arrays."""
    decoder = json.JSONDecoder()
    position = 0
    while True:
        while position < len(raw) and raw[position].isspace():
            position += 1
        if position >= len(raw):
            return
        value, position = decoder.raw_decode(raw, position)
        yield value


def items_from_stream(label: str, path: Path) -> list[Item]:
    """Comments saved by `gh api --paginate`: objects with an `id` and a `body`."""
    try:
        raw = path.read_text(encoding="utf-8")
        values = list(_json_values(raw))
    except (OSError, ValueError) as exc:
        raise InputError(f"could not read {label} file ({type(exc).__name__})") from None
    items: list[Item] = []
    for value in values:
        for entry in value if isinstance(value, list) else [value]:
            if isinstance(entry, dict):
                items.append(Item(_comment_label(label, entry.get("id")), _clean(entry.get("body"))))
    return items


def items_from_json_file(path: Path) -> list[Item]:
    """A plain list of {"location": ..., "text": ...} for local use."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"could not read the JSON input ({type(exc).__name__})") from None
    if not isinstance(data, list):
        raise InputError("the JSON input must be a list of {location, text} objects")
    return [
        Item(_clean(entry.get("location")) or "input", _clean(entry.get("text")))
        for entry in data
        if isinstance(entry, dict)
    ]


def items_from_env(spec: str) -> Item:
    label, _, var = spec.partition("=")
    if not label or not var:
        raise InputError("--env-text expects LABEL=ENV_VAR_NAME")
    return Item(label, os.environ.get(var, ""))


# ------------------------------------------------------------------------------ output


def scan_items(
    items: Iterable[Item], usernames: re.Pattern[str] | None = None
) -> list[tuple[str, Hit]]:
    found: list[tuple[str, Hit]] = []
    for item in items:
        found.extend((item.location, hit) for hit in scan_text(item.text, usernames))
    return found


def format_report(found: list[tuple[str, Hit]], annotate: bool) -> list[str]:
    lines: list[str] = []
    for location, hit in found[:MAX_REPORT_LINES]:
        message = f"{hit.category} found in {location} (line {hit.line})"
        lines.append(f"::error title=PR text privacy::{message}" if annotate else message)
    if len(found) > MAX_REPORT_LINES:
        lines.append(f"... and {len(found) - MAX_REPORT_LINES} more")
    return lines


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--event-file", type=Path, help="webhook payload (GITHUB_EVENT_PATH)")
    parser.add_argument("--event-name", help="webhook event name (GITHUB_EVENT_NAME)")
    parser.add_argument(
        "--stream",
        action="append",
        default=[],
        metavar="LABEL=FILE",
        help="comments saved by `gh api --paginate`; repeatable",
    )
    parser.add_argument("--json-file", type=Path, help="list of {location, text} objects")
    parser.add_argument(
        "--env-text",
        action="append",
        default=[],
        metavar="LABEL=ENV_VAR",
        help="scan the text held in this environment variable; repeatable",
    )
    return parser


def collect_items(args: argparse.Namespace) -> list[Item]:
    items: list[Item] = []
    if args.event_file:
        if not args.event_name:
            raise InputError("--event-file needs --event-name")
        try:
            event = json.loads(args.event_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InputError(f"could not read the event file ({type(exc).__name__})") from None
        if not isinstance(event, dict):
            raise InputError("the event file is not a JSON object")
        items.extend(items_from_event(args.event_name, event))
    for spec in args.stream:
        label, _, file_name = spec.partition("=")
        if not label or not file_name:
            raise InputError("--stream expects LABEL=FILE")
        items.extend(items_from_stream(label, Path(file_name)))
    if args.json_file:
        items.extend(items_from_json_file(args.json_file))
    items.extend(items_from_env(spec) for spec in args.env_text)
    return items


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    try:
        items = collect_items(args)
    except InputError as exc:
        print(f"privacy check could not run: {exc}", file=sys.stderr)
        return 2
    if not items:
        print("privacy check could not run: no text to scan was given", file=sys.stderr)
        return 2

    usernames, ignored = parse_usernames(os.environ.get("PRIVACY_CHECK_USERNAMES"))
    if usernames is None:
        reason = "not set (fork PRs and Dependabot never receive secrets)"
        print(f"{'::notice::' if annotate else 'note: '}PC username check skipped: {reason}")
    if ignored:
        print(f"note: {ignored} username entr{'y' if ignored == 1 else 'ies'} too short, ignored")

    found = scan_items(items, usernames)
    if not found:
        print(f"privacy check passed: scanned {len(items)} piece(s) of text")
        return 0
    for line in format_report(found, annotate):
        print(line)
    print(
        f"privacy check failed: {len(found)} finding(s). Matched text is never printed. "
        "Edit the text to remove it, and check its edit history. A real secret must be "
        "rotated, because deleting it does not un-leak it."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
