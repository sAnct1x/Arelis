"""Attachments were named and thrown away. Now they can land on disk.

Roadmap item: `inbox` could tell you an email had `invoice.pdf` on it and had
no way to get it, so every attachment task stopped one step from done —
"she can start a task but not finish it", which is the complaint this whole
phase is about. `extract_body` walked straight past the payload:

    if filename or "attachment" in disposition:
        attachments.append(_decode(filename) or "(unnamed)")
        continue            # <- the bytes went in the bin here

The interesting half of this is not the download, it is the filename. Every
attachment name is a string chosen by whoever sent the mail, and it arrives
before anyone has decided to trust them. `Content-Disposition:
attachment; filename="../../../../.ssh/authorized_keys"` is a valid header.
So the name is treated as hostile input and never as a path: basename only,
non-alphanumerics collapsed, leading dots stripped, Windows device names
defused, length capped. Those are the tests below that would matter if
someone rewrote this function.

Reading still does not mark mail read — BODY.PEEK, readonly select — because
fetching a file is not the same as opening the message.
"""

from __future__ import annotations

import email
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from arelis.mail import MailAccount
from arelis.tools.base import capability_class
from arelis.tools.inbox import (
    INBOX_READ_ACTIONS,
    INBOX_WRITE_ACTIONS,
    InboxTool,
    iter_attachments,
    safe_attachment_name,
)
from arelis.tools.policy import action_is_delete, action_is_write


def _message(
    parts: list[tuple[str, bytes]],
    *,
    body: str = "See attached.",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "me@example.com"
    msg["Subject"] = "Paperwork"
    msg["Date"] = "Sat, 08 Aug 2026 12:00:00 +0000"
    msg.set_content(body)
    for name, blob in parts:
        msg.add_attachment(
            blob,
            maintype="application",
            subtype="octet-stream",
            filename=name,
        )
    return msg.as_bytes()


class _FakeImap:
    """Returns one fixed message and records the fetch spec."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.fetches: list[str] = []
        self.readonly: bool | None = None

    def __enter__(self) -> _FakeImap:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def select(self, _mailbox: str, readonly: bool = False) -> tuple[str, list[Any]]:
        self.readonly = readonly
        return "OK", [b"1"]

    def uid(self, command: str, *args: object) -> tuple[str, list[Any]]:
        if command == "FETCH":
            spec = str(args[1])
            self.fetches.append(spec)
            meta = f"{args[0]} (BODY[] {{{len(self.raw)}}})"
            return "OK", [(meta.encode(), self.raw)]
        return "NO", [None]


def _tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    raw: bytes,
    **kwargs: Any,
) -> tuple[InboxTool, _FakeImap]:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    tool = InboxTool(MailAccount("me@example.com", "pw"), **kwargs)
    fake = _FakeImap(raw)
    monkeypatch.setattr(tool, "_connect", lambda **_k: fake)
    return tool, fake


def _written(tmp_path: Path) -> list[Path]:
    root = tmp_path / "outputs" / "mail"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


# ------------------------------------------------------------------ the name


@pytest.mark.parametrize(
    ("hostile", "must_not_contain"),
    [
        ("../../../../.ssh/authorized_keys", ".."),
        ("..\\..\\Windows\\System32\\evil.dll", ".."),
        ("/etc/passwd", "/"),
        ("C:\\Windows\\notes.txt", ":"),
        ("subdir/nested.pdf", "/"),
    ],
)
def test_a_sender_chosen_filename_cannot_describe_a_path(
    hostile: str, must_not_contain: str
) -> None:
    """The filename is a string from a stranger, not a location."""
    safe = safe_attachment_name(hostile, fallback="attachment")
    assert must_not_contain not in safe
    assert safe
    assert Path(safe).name == safe


@pytest.mark.parametrize("name", ["..", ".", "...", "", "   ", "/", "\\"])
def test_a_name_with_nothing_usable_in_it_falls_back(name: str) -> None:
    assert safe_attachment_name(name, fallback="attachment") == "attachment"


@pytest.mark.parametrize("device", ["CON", "nul", "COM1", "lpt9", "AUX.txt"])
def test_windows_device_names_are_defused(device: str) -> None:
    """Opening a file called NUL on Windows writes to a device, not a file."""
    safe = safe_attachment_name(device, fallback="attachment")
    stem = safe.split(".")[0].lower()
    assert stem not in {"con", "prn", "aux", "nul", "com1", "lpt9"}


def test_a_very_long_name_is_capped() -> None:
    safe = safe_attachment_name("a" * 500 + ".pdf", fallback="attachment")
    assert 0 < len(safe) <= 120


def test_a_normal_name_is_left_recognisable() -> None:
    """Sanitising must not mangle the ordinary case into gibberish."""
    assert safe_attachment_name("Invoice_2026-08.pdf", fallback="x") == ("Invoice_2026-08.pdf")


# ------------------------------------------------------------------ the bytes


def test_the_payload_is_reachable_at_all() -> None:
    """extract_body dropped this; nothing else in the tool could see it."""
    raw = _message([("notes.txt", b"hello bytes")])
    parts = iter_attachments(email.message_from_bytes(raw))
    assert [(n, b) for n, b in parts] == [("notes.txt", b"hello bytes")]


@pytest.mark.asyncio
async def test_an_attachment_lands_on_disk_with_its_bytes_intact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("invoice.pdf", b"%PDF-1.7 fake")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11")

    assert result.ok, result.output
    files = _written(tmp_path)
    assert len(files) == 1
    assert files[0].name == "invoice.pdf"
    assert files[0].read_bytes() == b"%PDF-1.7 fake"
    assert "invoice.pdf" in result.output


@pytest.mark.asyncio
async def test_a_hostile_name_stays_inside_the_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The test this feature exists to pass.

    If the sanitiser is ever removed, this writes outside the data root and
    the assertion below is what says so.
    """
    raw = _message([("../../../../pwned.txt", b"nope")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11")

    assert result.ok, result.output
    root = (tmp_path / "outputs" / "mail").resolve()
    files = _written(tmp_path)
    assert files, "nothing was written at all"
    for path in files:
        assert root in path.resolve().parents
    assert not (tmp_path.parent / "pwned.txt").exists()


@pytest.mark.asyncio
async def test_every_attachment_comes_down_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("a.txt", b"aaa"), ("b.txt", b"bbb")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11")

    assert result.ok, result.output
    assert {p.name for p in _written(tmp_path)} == {"a.txt", "b.txt"}


@pytest.mark.asyncio
async def test_one_attachment_can_be_asked_for_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("a.txt", b"aaa"), ("invoice.pdf", b"bbb")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11", name="invoice.pdf")

    assert result.ok, result.output
    assert {p.name for p in _written(tmp_path)} == {"invoice.pdf"}


@pytest.mark.asyncio
async def test_asking_for_a_name_that_is_not_there_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("a.txt", b"aaa")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11", name="invoice.pdf")

    assert not result.ok
    assert "a.txt" in result.output, "it should say what is actually attached"
    assert not _written(tmp_path)


@pytest.mark.asyncio
async def test_a_message_with_no_attachments_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Not a silent success. An empty download that reports ok is a wrong answer."""
    raw = _message([])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11")

    assert not result.ok
    assert "no attachment" in result.output.lower()


@pytest.mark.asyncio
async def test_an_unnamed_attachment_still_gets_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("", b"anonymous")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11")

    assert result.ok, result.output
    files = _written(tmp_path)
    assert len(files) == 1
    assert files[0].read_bytes() == b"anonymous"


@pytest.mark.asyncio
async def test_two_attachments_with_the_same_name_do_not_overwrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Silently keeping one of two files is data loss reported as success."""
    raw = _message([("scan.pdf", b"first"), ("scan.pdf", b"second")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download", id="11")

    assert result.ok, result.output
    files = _written(tmp_path)
    assert len(files) == 2
    assert {p.read_bytes() for p in files} == {b"first", b"second"}


@pytest.mark.asyncio
async def test_an_oversized_attachment_is_refused_not_streamed_to_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("huge.bin", b"x" * 5000)])
    tool, _ = _tool(monkeypatch, tmp_path, raw, max_attachment_bytes=1000)

    result = await tool.run(action="download", id="11")

    assert not result.ok
    assert "too large" in result.output.lower()
    assert not _written(tmp_path)


@pytest.mark.asyncio
async def test_downloading_does_not_mark_the_mail_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fetching a file is not opening the message."""
    raw = _message([("a.txt", b"aaa")])
    tool, fake = _tool(monkeypatch, tmp_path, raw)

    await tool.run(action="download", id="11")

    assert fake.fetches
    assert all("BODY.PEEK" in spec for spec in fake.fetches)
    assert fake.readonly is not False


@pytest.mark.asyncio
async def test_download_needs_an_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw = _message([("a.txt", b"aaa")])
    tool, _ = _tool(monkeypatch, tmp_path, raw)

    result = await tool.run(action="download")

    assert not result.ok
    assert "id" in result.output.lower()


# ------------------------------------------------------------------ the gate


def test_download_is_a_local_write_not_a_mailbox_change() -> None:
    """It writes files, so it needs Allow. It does not touch the mailbox.

    Classing it WRITE_EXTERNAL would be wrong twice over: nothing leaves the
    machine, and jobs would be refused an action that is safe for them.
    """
    args = {"action": "download", "id": "11"}
    assert action_is_write("inbox", args)
    assert not action_is_delete("inbox", args)
    assert capability_class("inbox", args) == "WRITE_LOCAL"
    assert capability_class("inbox", {"action": "trash"}) == "WRITE_EXTERNAL"
    assert capability_class("inbox", {"action": "list"}) == "READ"


def test_download_does_not_need_a_writable_mailbox() -> None:
    assert "download" in INBOX_READ_ACTIONS
    assert "download" not in INBOX_WRITE_ACTIONS


@pytest.mark.asyncio
async def test_a_read_only_job_can_still_fetch_a_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A briefing that saves today's invoice is the point of unattended runs."""
    raw = _message([("invoice.pdf", b"data")])
    tool, _ = _tool(monkeypatch, tmp_path, raw, allow_mutate=False)

    result = await tool.run(action="download", id="11")

    assert result.ok, result.output


def test_the_model_is_told_the_verb_exists() -> None:
    assert "download" in InboxTool.parameters_schema["properties"]["action"]["enum"]
    assert "download" in InboxTool.description.lower()
