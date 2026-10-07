"""Follow-up phrases land on the last file, page, mail, person, or image."""

from __future__ import annotations

import pytest

from arelis.core.reliance.last_object import StickyDesk

_FILE = "docs/budget.pdf"
_PAGE = "https://example.com/q3"
_MAIL = "thread-441"
_PERSON = "contact-7"
_IMAGE = "shots/desk.png"


@pytest.mark.parametrize(
    "phrase",
    [
        "that file",
        "the file",
        "this file",
        "that pdf",
        "the pdf",
        "that spreadsheet",
        "that doc",
        "that document",
        "THAT PDF",
        "summarize budget",
        "what about Budget",
    ],
)
def test_file_phrases_and_stem(phrase: str) -> None:
    desk = StickyDesk()
    desk.remember("file", _FILE, "budget.pdf")
    hit = desk.resolve(phrase)
    assert hit is not None
    assert hit.kind == "file"
    assert hit.ref == _FILE
    assert hit.label == "budget.pdf"


@pytest.mark.parametrize(
    "phrase",
    ["that page", "the page", "that site", "that article", "that link", "That Site"],
)
def test_page_phrases(phrase: str) -> None:
    desk = StickyDesk()
    desk.remember("page", _PAGE, "Q3 writeup")
    hit = desk.resolve(phrase)
    assert hit is not None
    assert hit.kind == "page"
    assert hit.ref == _PAGE


@pytest.mark.parametrize(
    "phrase",
    [
        "that email",
        "that thread",
        "that message",
        "reply to that",
        "reply to it",
        "That Thread",
    ],
)
def test_mail_phrases(phrase: str) -> None:
    desk = StickyDesk()
    desk.remember("mail", _MAIL, "Re: budget")
    hit = desk.resolve(phrase)
    assert hit is not None
    assert hit.kind == "mail"
    assert hit.ref == _MAIL


@pytest.mark.parametrize(
    "phrase",
    ["text them", "text him", "text her", "tell them", "Text Them"],
)
def test_person_phrases(phrase: str) -> None:
    desk = StickyDesk()
    desk.remember("person", _PERSON, "Sam")
    hit = desk.resolve(phrase)
    assert hit is not None
    assert hit.kind == "person"
    assert hit.ref == _PERSON


@pytest.mark.parametrize(
    "phrase",
    ["that image", "that picture", "that screenshot", "That Screenshot"],
)
def test_image_phrases(phrase: str) -> None:
    desk = StickyDesk()
    desk.remember("image", _IMAGE, "desk.png")
    hit = desk.resolve(phrase)
    assert hit is not None
    assert hit.kind == "image"
    assert hit.ref == _IMAGE


def test_current_without_kind_is_most_recent() -> None:
    desk = StickyDesk()
    assert desk.current() is None
    desk.remember("file", _FILE, "budget.pdf")
    desk.remember("mail", _MAIL, "Re: budget")
    assert desk.current() is not None
    assert desk.current().kind == "mail"
    assert desk.current().ref == _MAIL
    assert desk.current("file") is not None
    assert desk.current("file").ref == _FILE
    desk.remember("file", "docs/other.pdf", "other.pdf")
    assert desk.current().kind == "file"
    assert desk.current().ref == "docs/other.pdf"
    assert desk.current("file").ref == "docs/other.pdf"
    assert desk.resolve("that pdf").ref == "docs/other.pdf"
    assert desk.resolve("summarize budget") is None
    assert desk.resolve("open other").ref == "docs/other.pdf"


def test_reply_to_that_prefers_mail_over_a_newer_file() -> None:
    desk = StickyDesk()
    desk.remember("mail", _MAIL, "Re: budget")
    desk.remember("file", _FILE, "budget.pdf")
    assert desk.current().kind == "file"
    reply = desk.resolve("reply to that")
    assert reply is not None
    assert reply.kind == "mail"
    assert reply.ref == _MAIL
    again = desk.resolve("Reply To It")
    assert again is not None
    assert again.kind == "mail"
    assert desk.resolve("that pdf").ref == _FILE


def test_explicit_path_does_not_steal_the_sticky_file() -> None:
    desk = StickyDesk()
    desk.remember("file", _FILE, "budget.pdf")
    assert desk.resolve(r"open C:\docs\other.pdf") is None
    assert desk.resolve("read notes/q3.xlsx") is None
    assert desk.resolve("open other.pdf") is None
    assert desk.resolve("edit main.py") is None
    sticky = desk.resolve("that pdf")
    assert sticky is not None
    assert sticky.ref == _FILE
    same_name = desk.resolve("open budget.pdf")
    assert same_name is not None
    assert same_name.ref == _FILE


def test_resolve_none_when_that_kind_was_never_remembered() -> None:
    desk = StickyDesk()
    assert desk.resolve("") is None
    assert desk.resolve("   ") is None
    assert desk.resolve("that pdf") is None
    assert desk.resolve("that thread") is None
    desk.remember("file", _FILE, "budget.pdf")
    assert desk.resolve("that page") is None
    assert desk.resolve("that email") is None
    assert desk.resolve("reply to that") is None
    assert desk.resolve("text them") is None
    assert desk.resolve("that screenshot") is None
    assert desk.current("mail") is None
    assert desk.current("page") is None
    assert desk.current("person") is None
    assert desk.current("image") is None
