from __future__ import annotations

import email

import pytest

from arelis.mail import (
    PASSWORD_ENV,
    MailAccount,
    save_account,
)
from arelis.tools.base import ToolRegistry, capability_class, confirm_args_blocked
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.email_send import SendEmailTool
from arelis.tools.inbox import (
    InboxTool,
)


def _secrets(tmp_path, text: str):
    path = tmp_path / "secrets.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ credentials


def test_save_account_does_not_clobber_other_secrets(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    path = _secrets(
        tmp_path,
        "sms:\n  ingest_token: keep-me\nemail:\n  address: old@example.com\n",
    )
    account = save_account(
        address="new@example.com",
        app_password="abcd efgh ijkl mnop",
        path=path,
    )
    assert account is not None
    assert account.address == "new@example.com"
    assert account.password == "abcdefghijklmnop"
    raw = path.read_text(encoding="utf-8")
    assert "keep-me" in raw
    assert "old@example.com" not in raw


# --------------------------------------------------------------------- message


# ------------------------------------------------------------------- send tool


class _FakeMailer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[dict[str, str]] = []

    async def send_async(
        self, *, to: str, subject: str, body: str, attachments=None
    ) -> str:
        if self.error:
            raise self.error
        self.sent.append({"to": to, "subject": subject, "body": body})
        return "<id@example.com>"


def _tool(mailer, **account_kwargs):
    account_kwargs.setdefault("default_recipient", "you@example.com")
    account = MailAccount("me@example.com", "pw", **account_kwargs)
    return SendEmailTool(account, mailer)


@pytest.fixture(autouse=True)
def _no_standing_inbox(monkeypatch) -> None:
    """Mail tests must not pick up the developer profile.yaml."""
    monkeypatch.setattr("arelis.profile.load_profile_email", lambda **k: "")


@pytest.mark.asyncio
async def test_a_guessed_address_is_refused_before_the_transport() -> None:
    mailer = _FakeMailer()
    result = await _tool(mailer).run(to="probably-bob", subject="Hi", body="B")
    assert not result.ok
    assert not mailer.sent
    assert "ask the user" in result.output.lower()


# ---------------------------------------------------------------- confirm gate


def _registry_with_send() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(_tool(_FakeMailer()))
    return registry


def test_sending_is_gated_by_its_own_flag_not_the_image_one() -> None:
    """confirm_image is named for the image tool. Sharing it was a trap."""
    registry = _registry_with_send()
    assert registry.needs_confirm("send_email", {})
    assert registry.needs_confirm("send_email", {}, confirm_image=False)
    assert registry.needs_confirm("send_email", {}, confirm_send=False)


# ------------------------------------------------------------------ inbox tool


def _message(raw: str):
    return email.message_from_string(raw)


class _FakeImap:
    """Minimal IMAP stand-in for summarize (BODY.PEEK paths only)."""

    def __init__(self) -> None:
        self.fetches: list[str] = []

    def __enter__(self) -> _FakeImap:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def uid(self, command: str, *args: object):
        if command == "SEARCH":
            return "OK", [b"10 11"]
        if command == "FETCH":
            uid = str(args[0])
            spec = str(args[1])
            self.fetches.append(spec)
            assert "BODY.PEEK" in spec
            assert "BODY[]" not in spec.replace("BODY.PEEK", "")
            if "HEADER.FIELDS" in spec:
                raw = (
                    f"From: Alice <alice@example.com>\r\n"
                    f"Subject: Hello {uid}\r\n"
                    f"Date: Sat, 08 Aug 2026 12:00:00 +0000\r\n\r\n"
                ).encode()
                meta = f"{uid} (FLAGS () BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{{len(raw)}}})"
                return "OK", [(meta.encode(), raw)]
            body = (
                "From: Alice <alice@example.com>\r\n"
                f"Subject: Hello {uid}\r\n"
                "Date: Sat, 08 Aug 2026 12:00:00 +0000\r\n"
                "Content-Type: text/plain; charset=utf-8\r\n"
                "\r\n"
                f"Snippet body for message {uid} with enough text to preview.\r\n"
            ).encode()
            meta = f"{uid} (BODY[] {{{len(body)}}})"
            return "OK", [(meta.encode(), body)]
        return "NO", [None]

    def status(self, _mailbox: str, _names: str):
        return "OK", [b"INBOX (MESSAGES 2 UNSEEN 2)"]


class _FakeMutatingImap(_FakeImap):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[tuple[str, tuple[object, ...]]] = []
        self.created: list[str] = []
        self.writable: bool | None = None

    def select(self, _mailbox: str, readonly: bool = False):
        self.writable = not readonly
        return "OK", [b"1"]

    def list(self, *_args: object):
        return "OK", [
            b'(\\HasNoChildren) "/" "INBOX"',
            b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
            b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
        ]

    def create(self, name: str):
        self.created.append(name)
        return "OK", [None]

    def uid(self, command: str, *args: object):
        self.commands.append((command, args))
        if command in {"MOVE", "COPY", "STORE"}:
            return "OK", [None]
        if command == "EXPUNGE":
            return "OK", [None]
        return super().uid(command, *args)

    def expunge(self):
        self.commands.append(("EXPUNGE", ()))
        return "OK", [None]


def test_inbox_write_needs_confirm_and_an_id() -> None:
    from arelis.tools.base import ToolRegistry

    registry = ToolRegistry()
    registry.register(InboxTool(MailAccount("me@example.com", "pw")))
    assert not registry.needs_confirm("inbox", {"action": "list"})
    assert registry.needs_confirm("inbox", {"action": "trash", "id": "11"})
    assert capability_class("inbox", {"action": "trash"}) == "WRITE_EXTERNAL"
    assert capability_class("inbox", {"action": "list"}) == "READ"
    assert confirm_args_blocked("inbox", {"action": "trash"})
    assert confirm_headline("inbox", {"action": "trash", "sender": "Claude Team"}) == (
        "trash mail from Claude Team"
    )


# -------------------------------------------------------------- registration


def test_no_secrets_means_no_email_tools(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(tools_pkg, "load_account", lambda: None)
    # SMS has its own secrets; stub it off so this test is about email alone.
    monkeypatch.setattr(tools_pkg, "load_sms_account", lambda: None)
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = tools_pkg.build_tool_registry({"tools": {}, "agent": {}}, workspace)

    assert "send_email" not in registry.names()
    assert "send_sms" not in registry.names()
    assert "inbox" not in registry.names()
    assert "schedule" not in registry.names()


def test_attach_path_refuses_an_arbitrary_absolute(tmp_path) -> None:
    from arelis.core.email_complete import resolve_attach_path

    secret = tmp_path / "secrets.yaml"
    secret.write_text("password: hunter2\n", encoding="utf-8")
    assert resolve_attach_path(str(secret)) == ""


def test_redact_secrets_covers_quoted_json_keys() -> None:
    from arelis.tools.safety import redact_secrets

    assert "[redacted]" in redact_secrets("password: hunter2")
    assert "[redacted]" in redact_secrets('"password": "hunter2"')


