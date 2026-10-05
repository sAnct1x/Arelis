"""Confirm-card redaction must never rewrite the payload that will be sent.

describe_call used to assign redact_secrets() back onto send_sms / send_email
args, so an approved text containing a wifi password went out as
"[redacted]". The card may hide secrets; the transport must not.
"""

from __future__ import annotations

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.dash_filter import clean_dashes
from arelis.mail import MailAccount
from arelis.tools.base import ToolRegistry
from arelis.tools.email_send import SendEmailTool
from arelis.tools.safety import redact_secrets
from arelis.tools.sms_send import SendSmsTool

SECRET_BODY = "password: xyz"
DASH_BODY = "Meet at noon \u2014 bring the key"


class _FakeMailer:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_async(
        self, *, to: str, subject: str, body: str, attachments=None
    ) -> str:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return "<id@example.com>"


class _FakeSmsProvider:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, phone: str, body: str) -> str:
        self.sent.append({"phone": phone, "body": body})
        return "<sms-id>"


def _email_registry(mailer: _FakeMailer) -> ToolRegistry:
    account = MailAccount(
        "me@example.com", "pw", default_recipient="you@example.com"
    )
    registry = ToolRegistry()
    registry.register(SendEmailTool(account, mailer))
    return registry


def _sms_registry(provider: _FakeSmsProvider) -> ToolRegistry:
    book = {
        "mom": Contact(
            alias="mom",
            name="Mom",
            phone="5559998888",
            digits=normalize_phone("5559998888"),
            email="",
            aliases=(),
        )
    }
    registry = ToolRegistry()
    registry.register(SendSmsTool(provider, contacts_loader=lambda: book))
    return registry


def test_redact_secrets_would_eat_the_wifi_password() -> None:
    """The card filter is doing its job. That is why write-back is the bug."""
    assert "[redacted]" in redact_secrets(SECRET_BODY)
    assert "xyz" not in redact_secrets(SECRET_BODY)


@pytest.mark.asyncio
async def test_approved_email_sends_secret_and_only_cleans_dashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.profile.load_profile_email", lambda **k: "")
    mailer = _FakeMailer()
    registry = _email_registry(mailer)
    secret_args = {
        "to": "you@example.com",
        "subject": "wifi",
        "body": SECRET_BODY,
    }
    dash_args = {
        "to": "you@example.com",
        "subject": "lunch",
        "body": DASH_BODY,
    }

    secret_card = registry.describe_call("send_email", secret_args)
    dash_card = registry.describe_call("send_email", dash_args)

    assert "[redacted]" in secret_card
    assert "xyz" not in secret_card
    assert secret_args["body"] == SECRET_BODY

    expected_dash = clean_dashes(DASH_BODY).strip()
    assert expected_dash in dash_card
    assert dash_args["body"] == DASH_BODY

    secret_result = await registry.call("send_email", **secret_args)
    dash_result = await registry.call("send_email", **dash_args)
    assert secret_result.ok and dash_result.ok
    assert mailer.sent[0]["body"] == SECRET_BODY
    assert mailer.sent[1]["body"] == expected_dash
    assert "\u2014" not in mailer.sent[1]["body"]


@pytest.mark.asyncio
async def test_approved_sms_sends_secret_and_only_cleans_dashes() -> None:
    provider = _FakeSmsProvider()
    registry = _sms_registry(provider)
    secret_args = {"to": "mom", "body": SECRET_BODY}
    dash_args = {"to": "mom", "body": DASH_BODY}

    secret_card = registry.describe_call("send_sms", secret_args)
    dash_card = registry.describe_call("send_sms", dash_args)

    assert "[redacted]" in secret_card
    assert "xyz" not in secret_card
    assert secret_args["body"] == SECRET_BODY

    expected_dash = clean_dashes(DASH_BODY).strip()
    assert expected_dash in dash_card
    assert dash_args["body"] == DASH_BODY

    secret_result = await registry.call("send_sms", **secret_args)
    dash_result = await registry.call("send_sms", **dash_args)
    assert secret_result.ok and dash_result.ok
    assert provider.sent[0]["body"] == SECRET_BODY
    assert provider.sent[1]["body"] == expected_dash
    assert "\u2014" not in provider.sent[1]["body"]
