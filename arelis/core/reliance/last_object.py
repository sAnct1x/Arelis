"""In-memory desk for "that pdf" and "that thread".

People name a thing once and then point at it. This remembers the last
ref of each kind and maps a follow-up phrase back onto it. An explicit
path stays an explicit path so the caller does not get the sticky file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# Longer alternatives first. Word-bounded so "that doc" does not eat
# "that document", and case-insensitive so "That PDF" still lands.
_FILE_PHRASE = re.compile(
    r"(?i)\b(?:"
    r"that document|that spreadsheet|this file|that file|the file|"
    r"that pdf|the pdf|that doc"
    r")\b"
)
_PAGE_PHRASE = re.compile(
    r"(?i)\b(?:that article|that page|that site|the page|that link)\b"
)
_MAIL_PHRASE = re.compile(
    r"(?i)\b(?:that email|that thread|that message|reply to that|reply to it)\b"
)
# "reply to that" is also a mail phrase, and it wins over a file
# even when the file was remembered later.
_REPLY_PHRASE = re.compile(r"(?i)\breply to (?:that|it)\b")
_PERSON_PHRASE = re.compile(r"(?i)\b(?:text them|text him|text her|tell them)\b")
_IMAGE_PHRASE = re.compile(r"(?i)\b(?:that screenshot|that picture|that image)\b")

_KNOWN_EXTS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".xlsm",
        ".csv",
        ".ppt",
        ".pptx",
        ".txt",
        ".md",
        ".rtf",
        ".odt",
        ".ods",
        ".odp",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".svg",
        ".bmp",
        ".tif",
        ".tiff",
        ".heic",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".html",
        ".htm",
        ".css",
    }
)

_EDGE_PUNCT = ".,;:!?\"'`()[]{}<>"


@dataclass
class StickyRef:
    kind: str  # file, page, mail, person, image
    ref: str
    label: str = ""


def _filename_stem(label: str) -> str:
    cleaned = label.strip().replace("\\", "/")
    if not cleaned:
        return ""
    return PurePosixPath(cleaned).stem


def _stem_in_text(text: str, stem: str) -> bool:
    if not stem:
        return False
    pattern = rf"(?i)(?<!\w){re.escape(stem)}(?!\w)"
    return re.search(pattern, text) is not None


def _token_suffix(token: str) -> str:
    slashless = token.replace("\\", "/")
    return PurePosixPath(slashless).suffix.casefold()


def _names_explicit_path(text: str, remembered_stem: str) -> bool:
    """True when the text names a path the caller should use itself.

    A slash or backslash is always explicit. A known extension is explicit
    when the token is more than the remembered file's filename stem
    (so "budget.pdf" still points at the sticky file labeled budget).
    """
    remembered = remembered_stem.casefold()
    for raw in text.split():
        token = raw.strip(_EDGE_PUNCT)
        if not token:
            continue
        if "/" in token or "\\" in token:
            return True
        suffix = _token_suffix(token)
        if suffix not in _KNOWN_EXTS:
            continue
        token_stem = _filename_stem(token)
        if remembered and token_stem.casefold() == remembered:
            continue
        return True
    return False


class StickyDesk:
    """Last ref of each kind, plus which one was said most recently."""

    def __init__(self) -> None:
        self._by_kind: dict[str, StickyRef] = {}
        self._recent: list[str] = []

    def remember(self, kind: str, ref: str, label: str = "") -> None:
        self._by_kind[kind] = StickyRef(kind=kind, ref=ref, label=label)
        if kind in self._recent:
            self._recent.remove(kind)
        self._recent.append(kind)

    def current(self, kind: str | None = None) -> StickyRef | None:
        """kind=None returns the most recently remembered ref of any kind."""
        if kind is None:
            if not self._recent:
                return None
            return self._by_kind[self._recent[-1]]
        return self._by_kind.get(kind)

    def resolve(self, text: str) -> StickyRef | None:
        """Map a follow-up phrase onto a remembered ref.

        None if the text names something new or nothing matches.
        """
        if not text or not text.strip():
            return None
        file_ref = self.current("file")
        stem = _filename_stem(file_ref.label) if file_ref is not None else ""
        if _names_explicit_path(text, stem):
            return None
        if _REPLY_PHRASE.search(text) is not None:
            mail = self.current("mail")
            if mail is not None:
                return mail
        if file_ref is not None and (
            _FILE_PHRASE.search(text) is not None or _stem_in_text(text, stem)
        ):
            return file_ref
        page = self.current("page")
        if page is not None and _PAGE_PHRASE.search(text) is not None:
            return page
        mail = self.current("mail")
        if mail is not None and _MAIL_PHRASE.search(text) is not None:
            return mail
        person = self.current("person")
        if person is not None and _PERSON_PHRASE.search(text) is not None:
            return person
        image = self.current("image")
        if image is not None and _IMAGE_PHRASE.search(text) is not None:
            return image
        return None
