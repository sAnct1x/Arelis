from __future__ import annotations

import email
import smtplib

import pytest

from arelis.core.agent_loop import TOOL_POLICY
from arelis.mail import (
    PASSWORD_ENV,
    MailAccount,
    build_message,
    explain_smtp_error,
    load_account,
    markdown_to_html,
    valid_address,
)
from arelis.tools.base import NEVER_BATCH, ToolRegistry
from arelis.tools.email_send import SendEmailTool
from arelis.tools.inbox import (
    InboxTool,
    _build_criteria,
    _decode,
    _imap_date,
    _list_criteria,
    _quote,
    extract_body,
)


def _secrets(tmp_path, text: str):
    path = tmp_path / "secrets.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ credentials


def test_no_secrets_file_means_no_account(tmp_path) -> None:
    """None, not an exception. The tools then stay unregistered entirely."""
    assert load_account(tmp_path / "absent.yaml") is None


def test_a_half_filled_file_is_not_an_account(tmp_path) -> None:
    path = _secrets(tmp_path, "email:\n  address: me@example.com\n  app_password: ''\n")
    assert load_account(path) is None


def test_the_spaces_google_shows_are_not_part_of_the_password(tmp_path) -> None:
    """People paste app passwords exactly as displayed, in four groups of four."""
    path = _secrets(
        tmp_path,
        "email:\n  address: me@example.com\n  app_password: 'abcd efgh ijkl mnop'\n",
    )
    account = load_account(path)
    assert account is not None
    assert account.password == "abcdefghijklmnop"


def test_the_environment_wins_over_the_file(tmp_path, monkeypatch) -> None:
    path = _secrets(
        tmp_path, "email:\n  address: me@example.com\n  app_password: fromfile\n"
    )
    monkeypatch.setenv(PASSWORD_ENV, "fromenv")
    account = load_account(path)
    assert account is not None and account.password == "fromenv"


def test_a_corrupt_file_does_not_raise(tmp_path) -> None:
    path = _secrets(tmp_path, "email: [this is not a mapping\n")
    assert load_account(path) is None


def test_recipient_falls_back_to_the_user(tmp_path) -> None:
    account = MailAccount("me@example.com", "pw", default_recipient="digest@example.com")
    assert account.recipient("someone@else.com") == "someone@else.com"
    assert account.recipient("") == "digest@example.com"
    assert MailAccount("me@example.com", "pw").recipient("") == "me@example.com"


def test_address_validation_is_loose_but_catches_nonsense() -> None:
    assert valid_address("a.b+c@example.co.uk")
    assert not valid_address("not-an-address")
    assert not valid_address("two@@example.com")
    assert not valid_address("a@b, c@d")


# --------------------------------------------------------------------- message


def test_message_carries_both_plain_text_and_html() -> None:
    message = build_message(
        sender="me@example.com",
        from_name="Arelis",
        to="you@example.com",
        subject="Digest",
        body="# Today\n\nSomething **happened**.",
    )
    assert message["From"] == "Arelis <me@example.com>"
    assert message["To"] == "you@example.com"
    types = {part.get_content_type() for part in message.walk() if not part.is_multipart()}
    assert types == {"text/plain", "text/html"}


def test_html_never_lets_source_markup_render() -> None:
    """An answer can quote a scraped page. That page must not render in a inbox."""
    rendered = markdown_to_html('<script>alert(1)</script> and <b>bold</b>')
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_html_renders_the_marks_that_actually_turn_up() -> None:
    rendered = markdown_to_html(
        "## Heading\n\n- one\n- two\n\n**bold** and [a link](https://example.com/x)"
    )
    assert "<h3>Heading</h3>" in rendered
    assert rendered.count("<li>") == 2
    assert "<strong>bold</strong>" in rendered
    assert '<a href="https://example.com/x"' in rendered


def test_a_non_http_link_is_not_made_clickable() -> None:
    rendered = markdown_to_html("[click](javascript:alert(1))")
    assert "javascript:" not in rendered
    assert "click" in rendered


def test_bare_urls_become_links() -> None:
    assert '<a href="https://example.org/a"' in markdown_to_html("see https://example.org/a")


def test_auth_failure_says_app_password() -> None:
    """The single most likely first-run failure deserves the real answer."""
    message = explain_smtp_error(smtplib.SMTPAuthenticationError(535, b"nope"))
    assert "app password" in message.lower()
    assert "2-step verification" in message.lower()


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
    account = MailAccount("me@example.com", "pw", **account_kwargs)
    return SendEmailTool(account, mailer)


@pytest.mark.asyncio
async def test_send_goes_to_the_user_when_no_recipient_is_named() -> None:
    mailer = _FakeMailer()
    result = await _tool(mailer).run(subject="Hi", body="Body")
    assert result.ok
    assert mailer.sent[0]["to"] == "me@example.com"


@pytest.mark.asyncio
async def test_send_reaches_any_recipient() -> None:
    """No allowlist. The confirm card is the gate, not a config file."""
    mailer = _FakeMailer()
    result = await _tool(mailer).run(to="stranger@elsewhere.org", subject="Hi", body="B")
    assert result.ok
    assert mailer.sent[0]["to"] == "stranger@elsewhere.org"


@pytest.mark.asyncio
async def test_a_guessed_address_is_refused_before_the_transport() -> None:
    mailer = _FakeMailer()
    result = await _tool(mailer).run(to="probably-bob", subject="Hi", body="B")
    assert not result.ok
    assert not mailer.sent
    assert "ask the user" in result.output.lower()


@pytest.mark.asyncio
async def test_an_empty_body_is_refused() -> None:
    result = await _tool(_FakeMailer()).run(subject="Hi", body="   ")
    assert not result.ok


@pytest.mark.asyncio
async def test_a_send_failure_is_reported_not_raised() -> None:
    mailer = _FakeMailer(smtplib.SMTPAuthenticationError(535, b"nope"))
    result = await _tool(mailer).run(subject="Hi", body="B")
    assert not result.ok
    assert "app password" in result.output.lower()


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
    assert not registry.needs_confirm("send_email", {}, confirm_send=False)


def test_sending_can_never_be_batch_approved() -> None:
    assert "send_email" in NEVER_BATCH
    assert "send_sms" in NEVER_BATCH


def test_the_card_shows_the_whole_email_not_eighty_characters() -> None:
    registry = _registry_with_send()
    body = "Dear Bob, " + ("this is a long message. " * 20)
    args = {"to": "bob@example.com", "subject": "Thursday", "body": body}

    summary = registry.summarize_call("send_email", args)
    detail = registry.describe_call("send_email", args)

    assert "…" in summary, "summarize_call still truncates, as it should"
    assert "bob@example.com" in detail
    assert "Thursday" in detail
    assert detail.endswith(body.strip())


def test_other_tools_keep_the_one_line_rendering() -> None:
    registry = _registry_with_send()
    # Workspace (and other rich tools) use a multi-line confirm card; summarize
    # stays the short trace form.
    detail = registry.describe_call("workspace", {"action": "list"})
    summary = registry.summarize_call("workspace", {"action": "list"})
    assert "Workspace" in detail
    assert summary == "workspace(action=list)" or summary.startswith("workspace(")


# ------------------------------------------------------------------ inbox tool


def _message(raw: str):
    return email.message_from_string(raw)


def test_plain_text_is_preferred_over_html() -> None:
    msg = _message(
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/alternative; boundary="b"\n\n'
        "--b\nContent-Type: text/plain\n\nthe plain part\n"
        "--b\nContent-Type: text/html\n\n<p>the html part</p>\n"
        "--b--\n"
    )
    body, attachments = extract_body(msg)
    assert "the plain part" in body
    assert "html part" not in body
    assert attachments == []


def test_html_only_mail_is_reduced_to_text() -> None:
    msg = _message(
        "MIME-Version: 1.0\nContent-Type: text/html\n\n"
        "<html><body><script>x=1</script><p>Hello there</p></body></html>\n"
    )
    body, _ = extract_body(msg)
    assert "Hello there" in body
    assert "x=1" not in body


def test_attachments_are_named_never_fetched() -> None:
    msg = _message(
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="b"\n\n'
        "--b\nContent-Type: text/plain\n\nsee attached\n"
        "--b\nContent-Type: application/pdf\n"
        'Content-Disposition: attachment; filename="invoice.pdf"\n\n'
        "JVBERi0=\n"
        "--b--\n"
    )
    body, attachments = extract_body(msg)
    assert attachments == ["invoice.pdf"]
    assert "JVBERi0=" not in body


def test_encoded_headers_are_decoded() -> None:
    assert _decode("=?utf-8?q?Caf=C3=A9?=") == "Café"
    assert _decode(None) == ""


def test_dates_are_translated_into_what_imap_wants() -> None:
    assert _imap_date("2026-08-06") == "06-Aug-2026"
    assert _imap_date("06/08/2026") == ""
    assert _imap_date("2026-13-01") == ""


def test_search_values_cannot_break_out_of_their_quotes() -> None:
    assert _quote('say "hi"') == '"say \\"hi\\""'
    criteria = _build_criteria({"sender": "bob@x.com", "since": "2026-08-06"})
    assert criteria == ["FROM", '"bob@x.com"', "SINCE", "06-Aug-2026"]


def test_an_empty_search_still_matches_everything() -> None:
    assert _build_criteria({}) == ["ALL"]


def test_list_defaults_to_unread_only_with_an_all_opt_out() -> None:
    """A 20k mailbox makes ALL a firehose; unread is the useful default."""
    assert _list_criteria("list", {}) == ["UNSEEN"]
    assert _list_criteria("list", {"unread_only": False}) == ["ALL"]
    assert _list_criteria("list", {"unread_only": True}) == ["UNSEEN"]
    assert _list_criteria("search", {}) == ["ALL"]
    assert _list_criteria("search", {"unread_only": True, "sender": "a@b.c"}) == [
        "FROM",
        '"a@b.c"',
        "UNSEEN",
    ]


@pytest.mark.asyncio
async def test_an_unknown_inbox_action_fails_without_connecting() -> None:
    tool = InboxTool(MailAccount("me@example.com", "pw"))
    result = await tool.run(action="delete")
    assert not result.ok
    assert "list, search, read, or summarize" in result.output


def test_inbox_exposes_no_mailbox_mutation_actions() -> None:
    """Capability honesty: delete is not a soft refusal, it is absent."""
    actions = InboxTool.parameters_schema["properties"]["action"]["enum"]
    assert actions == ["list", "search", "read", "summarize"]
    assert "delete" not in actions
    assert "trash" not in actions
    lowered = InboxTool.description.lower()
    assert "read-only" in lowered or "strictly read-only" in lowered
    assert "delete" in lowered
    assert "summarize" in lowered
    assert "body.peek" in lowered


def test_summarize_criteria_default_unread_like_list() -> None:
    assert _list_criteria("summarize", {}) == ["UNSEEN"]
    assert _list_criteria("summarize", {"unread_only": False}) == ["ALL"]
    assert _list_criteria(
        "summarize", {"sender": "a@b.c", "unread_only": True}
    ) == ["FROM", '"a@b.c"', "UNSEEN"]


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


@pytest.mark.asyncio
async def test_summarize_returns_structured_peek_only(monkeypatch) -> None:
    tool = InboxTool(MailAccount("me@example.com", "pw"), max_messages=5)
    fake = _FakeImap()
    monkeypatch.setattr(tool, "_connect", lambda: fake)
    result = await tool.run(action="summarize", limit=2)
    assert result.ok
    assert result.data is not None
    messages = result.data["messages"]
    assert len(messages) == 2
    assert messages[0]["subject"].startswith("Hello")
    assert messages[0]["from"]
    assert messages[0]["date"]
    assert "Snippet body" in messages[0]["snippet"]
    assert "Peek-only" in result.output
    assert all("BODY.PEEK" in spec for spec in fake.fetches)
    assert not any(
        "BODY[]" in spec.replace("BODY.PEEK", "PEEK") for spec in fake.fetches
    )


def test_tool_policy_forbids_claiming_mail_was_deleted() -> None:
    """The failure mode was narrating success after confirm with no tool."""
    text = TOOL_POLICY.lower()
    assert "read-only" in text
    assert "never claim you deleted" in text
    assert "confirmation without a tool is a lie" in text


def test_persona_forbids_narrating_side_effects_without_a_tool() -> None:
    from pathlib import Path

    text = Path("arelis/persona/arelis.md").read_text(encoding="utf-8")
    assert "Never claim you completed a side effect" in text


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


def test_the_job_runner_gets_no_way_to_send(tmp_path, monkeypatch) -> None:
    """The load-bearing guarantee: unattended turns cannot email or text anyone."""
    from arelis import tools as tools_pkg
    from arelis.sms_android import SmsGateAccount
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(
        tools_pkg, "load_account", lambda: MailAccount("me@example.com", "pw")
    )
    monkeypatch.setattr(
        tools_pkg,
        "load_sms_account",
        lambda: SmsGateAccount("http://192.168.1.10:8080", "u", "p"),
    )
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})

    attended = tools_pkg.build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "send_email" in attended.names()
    assert "send_sms" in attended.names()
    assert "schedule" in attended.names()

    unattended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert "send_email" not in unattended.names()
    assert "send_sms" not in unattended.names()
    assert "schedule" not in unattended.names()
    # Reading is still allowed: a digest may well be about your mail.
    assert "inbox" in unattended.names()
    # Chat archive tools are not: an unattended turn must not search or
    # rewrite what you said in private conversations.
    assert "recall" not in unattended.names()
    assert "memory" not in unattended.names()
