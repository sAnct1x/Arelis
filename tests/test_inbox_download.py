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

from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from arelis.mail import MailAccount
from arelis.tools.inbox import (
    InboxTool,
)


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


# ------------------------------------------------------------------ the bytes


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
async def test_an_oversized_attachment_is_refused_not_streamed_to_disk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = _message([("huge.bin", b"x" * 5000)])
    tool, _ = _tool(monkeypatch, tmp_path, raw, max_attachment_bytes=1000)

    result = await tool.run(action="download", id="11")

    assert not result.ok
    assert "too large" in result.output.lower()
    assert not _written(tmp_path)


# ------------------------------------------------------------------ the gate


