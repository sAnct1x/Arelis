"""Follow-up phrases land on the last file, page, mail, person, or image."""

from __future__ import annotations

from arelis.core.reliance.last_object import StickyDesk

_FILE = "docs/budget.pdf"
_PAGE = "https://example.com/q3"
_MAIL = "thread-441"
_PERSON = "contact-7"
_IMAGE = "shots/desk.png"


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


