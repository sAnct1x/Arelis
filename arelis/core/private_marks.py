"""Private text seen this turn, and whether a URL is about to carry it out.

A model that just read a mail can put an account number, or a sentence from
that mail, into a web address. The Allow card is for that case. A normal
lookup stays quiet. Marks live on the turn and die with it.

A token is a run of 8 or more characters from letters, digits, and
``@._+-`` that also contains a digit or ``@``. A long word with no digit,
such as "together", is not a token.

A phrase is four words in a row. Short words stay in the row, because
"meet me at the clinic" is the address this card exists for. A row whose
words are all shorter than three letters is not a phrase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote_plus, urlsplit

_TOKEN = re.compile(r"[A-Za-z0-9@._+-]{8,}")
_WORD = re.compile(r"[A-Za-z]+")
_NOT_LETTER = re.compile(r"[^a-z0-9]+")

_MAX_MARKS = 20_000
_PREVIEW = 6

_FILE_TOOLS = frozenset(
    {
        "doc_extract",
        "analyze",
        "sql",
        "ocr",
        "vision",
        "transcribe",
        "pdf",
        "data_cell",
    }
)
_MEMORY_TOOLS = frozenset({"memory", "recall", "notes", "tasks", "goals"})
_WORKSPACE_READS = frozenset({"list", "read", "grep", "find"})
_BROWSER_URL_ACTIONS = frozenset({"open", "navigate", "reserve", "relaunch"})

_NOTE = "This web address includes text from {source}: {preview}"


@dataclass(frozen=True)
class _Mark:
    source: str
    kind: str
    text: str


@dataclass(frozen=True)
class PrivateHit:
    """One private fragment found in a URL the model built."""

    source: str
    kind: str
    text: str
    host: str

    @property
    def note(self) -> str:
        if len(self.text) <= _PREVIEW:
            preview = self.text
        else:
            preview = self.text[:_PREVIEW] + "..."
        return _NOTE.format(source=self.source, preview=preview)


@dataclass
class PrivateMarks:
    """Tokens, phrases, and raw tool outputs for one turn."""

    marks: list[_Mark] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    allowed_hosts: set[str] = field(default_factory=set)
    _seen: set[tuple[str, str, str]] = field(default_factory=set)

    def record(self, tool: str, args: dict[str, Any] | None, output: str) -> None:
        """Remember private text from a tool that just succeeded."""
        source = _source_label(tool, args)
        if source is None:
            return
        text = str(output or "")
        if not text:
            return
        self.outputs.append(text)
        if len(self.marks) >= _MAX_MARKS:
            return
        for token in _tokens(text):
            self._add(source, "token", token)
            if len(self.marks) >= _MAX_MARKS:
                return
        for phrase in _phrases(text):
            self._add(source, "phrase", phrase)
            if len(self.marks) >= _MAX_MARKS:
                return

    def allow_host(self, host: str) -> None:
        """One Allow covers this host for the rest of the turn."""
        cleaned = _clean_host(host)
        if cleaned:
            self.allowed_hosts.add(cleaned)

    def _add(self, source: str, kind: str, text: str) -> None:
        key = (source, kind, text.casefold())
        if key in self._seen or len(self.marks) >= _MAX_MARKS:
            return
        self._seen.add(key)
        self.marks.append(_Mark(source=source, kind=kind, text=text))


def private_url_hit(ctx: Any, name: str, args: dict[str, Any] | None) -> PrivateHit | None:
    """A private fragment in this call's URL, or None when the call is ordinary.

    web_search, and browser search or maps, are not checked. A link copied
    whole from a recorded output is not a hit. A token the user typed this
    turn is not a hit either.
    """
    marks = getattr(ctx, "private_marks", None)
    if not isinstance(marks, PrivateMarks):
        return None
    if not marks.marks and not marks.outputs:
        return None
    raw_args = args if isinstance(args, dict) else {}
    url = _call_url(name, raw_args)
    if not url:
        return None
    host = _url_host(url)
    if host and host in marks.allowed_hosts:
        return None
    if _copied_whole(url, marks.outputs):
        return None
    if not marks.marks:
        return None
    body = _url_body(url)
    if not body:
        return None
    user = str(getattr(ctx, "text", "") or "").casefold()
    phrase_body = f" {_NOT_LETTER.sub(' ', body).strip()} "
    for mark in marks.marks:
        if mark.kind == "token":
            needle = mark.text.casefold()
            if not needle or needle not in body:
                continue
            if needle in user:
                continue
            return PrivateHit(
                source=mark.source, kind="token", text=mark.text, host=host
            )
        if mark.kind == "phrase" and f" {mark.text} " in phrase_body:
            return PrivateHit(
                source=mark.source, kind="phrase", text=mark.text, host=host
            )
    return None


def _source_label(tool: str, args: dict[str, Any] | None) -> str | None:
    name = (tool or "").strip()
    if name == "workspace":
        action = str((args or {}).get("action") or "").strip().lower()
        if action in _WORKSPACE_READS:
            return "your files"
        return None
    if name in _FILE_TOOLS:
        return "your files"
    if name == "inbox":
        return "your email"
    if name == "inbound_sms":
        return "your texts"
    if name in _MEMORY_TOOLS:
        return "your memory"
    if name == "clipboard":
        return "your clipboard"
    if name == "agenda":
        return "your calendar"
    if name == "contacts":
        return "your contacts"
    return None


def _tokens(text: str) -> list[str]:
    found: list[str] = []
    for match in _TOKEN.finditer(text):
        # A sentence period is in the class because emails contain dots.
        # Drop dots that only trail the match, then keep it if it is still
        # long enough to be an account, a code, or an address.
        token = match.group(0).rstrip(".")
        if len(token) < 8:
            continue
        if any(ch.isdigit() for ch in token) or "@" in token:
            found.append(token)
    return found


def _phrases(text: str) -> list[str]:
    words = _WORD.findall(text.casefold())
    found: list[str] = []
    for index in range(len(words) - 3):
        window = words[index : index + 4]
        if not any(len(word) >= 3 for word in window):
            continue
        found.append(" ".join(window))
    return found


def _call_url(name: str, args: dict[str, Any]) -> str:
    tool = (name or "").strip()
    if tool == "web_search":
        return ""
    if tool in {"web_fetch", "scrape"}:
        return str(args.get("url") or "").strip()
    if tool != "browser":
        return ""
    action = str(args.get("action") or "").strip().lower()
    if action not in _BROWSER_URL_ACTIONS:
        return ""
    return str(args.get("url") or "").strip()


def _copied_whole(url: str, outputs: list[str]) -> bool:
    needle = url.strip()
    if len(needle) < 12:
        return False
    return any(needle in output for output in outputs)


def _url_host(url: str) -> str:
    parsed = urlsplit(url.strip())
    return _clean_host(parsed.hostname or "")


def _clean_host(host: str) -> str:
    return (host or "").strip().casefold().rstrip(".")


def _url_body(url: str) -> str:
    """Host, path, query, and fragment, decoded twice and casefolded.

    ``unquote_plus`` turns ``+`` into a space and ``%41`` into ``A``. Doing
    it twice covers a value that was encoded twice.
    """
    parsed = urlsplit(url.strip())
    if parsed.scheme and parsed.netloc:
        rest = parsed.netloc + parsed.path
        if parsed.query:
            rest += "?" + parsed.query
        if parsed.fragment:
            rest += "#" + parsed.fragment
    else:
        rest = url.strip()
        if "://" in rest:
            rest = rest.split("://", 1)[1]
    decoded = unquote_plus(unquote_plus(rest))
    return decoded.casefold()
