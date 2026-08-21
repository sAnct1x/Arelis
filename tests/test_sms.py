from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from arelis.contacts import (
    Contact,
    contacts_prompt_line,
    load_contacts,
    normalize_phone,
    resolve_contact,
    to_e164,
)
from arelis.core.agent_loop import TOOL_POLICY
from arelis.mail import MailAccount
from arelis.sms import (
    format_sms_confirm,
    prepare_body,
    resolve_operator_sms_target,
    resolve_sms_target,
    send_operator_sms,
)
from arelis.sms_android import (
    AndroidSmsProvider,
    SmsGateAccount,
    load_sms_account,
)
from arelis.tools.base import NEVER_BATCH, ToolRegistry
from arelis.tools.sms_send import SendSmsTool


def _contacts_file(tmp_path, text: str):
    path = tmp_path / "contacts.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "")
        raw_aliases = fields.get("aliases") or ()
        if isinstance(raw_aliases, str):
            raw_aliases = (raw_aliases,)
        out[alias] = Contact(
            alias=alias,
            name=str(fields.get("name") or ""),
            phone=phone,
            digits=normalize_phone(phone),
            email=str(fields.get("email") or ""),
            aliases=tuple(str(a).lower() for a in raw_aliases),
        )
    return out


def _secrets_file(tmp_path: Path, sms: dict | None = None, email: dict | None = None) -> Path:
    path = tmp_path / "secrets.yaml"
    body: dict = {}
    if email is not None:
        body["email"] = email
    if sms is not None:
        body["sms"] = sms
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


# ------------------------------------------------------------------ contacts


def test_missing_contacts_file_is_empty(tmp_path) -> None:
    assert load_contacts(tmp_path / "absent.yaml") == {}


def test_blank_phone_is_skipped(tmp_path) -> None:
    path = _contacts_file(
        tmp_path,
        "contacts:\n  wife:\n    name: W\n    phone: ''\n",
    )
    assert load_contacts(path) == {}


def test_load_and_resolve_strips_my_and_matches_case(tmp_path) -> None:
    path = _contacts_file(
        tmp_path,
        "contacts:\n"
        "  wife:\n"
        "    name: Partner\n"
        "    phone: '+1 (555) 111-2222'\n",
    )
    book = load_contacts(path)
    assert resolve_contact("my Wife", book) is book["wife"]
    assert book["wife"].digits == "5551112222"
    assert book["wife"].display_name == "Partner"
    assert book["wife"].e164 == "+15551112222"


def test_resolve_by_phone_digits() -> None:
    book = _book(mom={"name": "Mom", "phone": "5553334444"})
    assert resolve_contact("1-555-333-4444", book) is book["mom"]


def test_unknown_alias_is_none() -> None:
    assert resolve_contact("stranger", _book()) is None


def test_extra_aliases_and_my_phone_resolve(tmp_path) -> None:
    path = _contacts_file(
        tmp_path,
        "contacts:\n"
        "  me:\n"
        "    name: Sam Whitlock\n"
        "    phone: '5555550123'\n"
        "    aliases:\n"
        "      - myself\n"
        "      - my phone\n"
        "      - sam whitlock\n",
    )
    book = load_contacts(path)
    assert resolve_contact("myself", book) is book["me"]
    assert resolve_contact("my phone", book) is book["me"]
    assert resolve_contact("Sam Whitlock", book) is book["me"]
    assert resolve_contact("text-not-a-name", book) is None


def test_bare_sam_does_not_steal_sam_brightly() -> None:
    """'sam' → me; friend is 'brightly' / 'sam brightly' only."""
    book = _book(
        me={
            "name": "Sam Whitlock",
            "phone": "5555550123",
            "aliases": ("sam", "myself"),
        },
        brightly={
            "name": "Sam Brightly",
            "phone": "5555550123",
            "aliases": ("sam brightly",),
        },
    )
    assert resolve_contact("sam", book) is book["me"]
    assert resolve_contact("brightly", book) is book["brightly"]
    assert resolve_contact("sam brightly", book) is book["brightly"]


def test_to_e164_handles_us_and_already_international() -> None:
    assert to_e164("5551112222") == "+15551112222"
    assert to_e164("+44 7700 900123") == "+447700900123"
    assert to_e164("1-555-111-2222") == "+15551112222"
    assert to_e164("") == ""


def test_legacy_carrier_fields_are_ignored(tmp_path) -> None:
    """Old contacts.yaml files still load; carrier/sms_email are not required."""
    path = _contacts_file(
        tmp_path,
        "contacts:\n"
        "  wife:\n"
        "    name: Partner\n"
        "    phone: '5551112222'\n"
        "    carrier: verizon\n"
        "    sms_email: '5551112222@vtext.com'\n",
    )
    book = load_contacts(path)
    assert "wife" in book
    assert book["wife"].e164 == "+15551112222"
    assert not hasattr(book["wife"], "carrier")
    assert not hasattr(book["wife"], "sms_email")


# --------------------------------------------------------------------- sms


def test_resolve_sms_target_unknown_alias() -> None:
    err = resolve_sms_target("wife", {})
    assert isinstance(err, str)
    assert "Unknown contact" in err


def test_resolve_sms_target_ok() -> None:
    book = _book(wife={"name": "W", "phone": "5551112222"})
    resolved = resolve_sms_target("my wife", book)
    assert not isinstance(resolved, str)
    assert resolved.phone_e164 == "+15551112222"
    assert resolved.label == "W"


def test_operator_target_accepts_digits_without_a_contact() -> None:
    resolved = resolve_operator_sms_target(phone="5551112222", contacts={})
    assert not isinstance(resolved, str)
    assert resolved.phone_e164 == "+15551112222"


def test_agent_target_still_refuses_unknown_names() -> None:
    err = resolve_sms_target("5551112222", {})
    assert isinstance(err, str)


@pytest.mark.asyncio
async def test_operator_send_hits_the_radio_without_confirm() -> None:
    sent: list[tuple[str, str]] = []

    class _Prov:
        async def send(self, *, phone: str, body: str) -> str:
            sent.append((phone, body))
            return "op-1"

    message_id = await send_operator_sms(
        phone="+15551112222", body="good night", provider=_Prov()
    )
    assert message_id == "op-1"
    assert sent == [("+15551112222", "good night")]


def test_prepare_body_truncates() -> None:
    text, truncated = prepare_body("x" * 2000, max_chars=1600)
    assert truncated and len(text) == 1600


def test_confirm_card_shows_phone_gateway_and_body() -> None:
    book = _book(wife={"name": "Partner", "phone": "5551112222"})
    detail = format_sms_confirm("wife", "running late", contacts=book)
    assert "Partner" in detail
    assert "5551112222" in detail
    assert "your phone" in detail
    assert "vtext.com" not in detail
    assert "email-to-SMS" not in detail
    assert detail.endswith("running late")


# ------------------------------------------------------------------- secrets


def test_load_sms_account_missing_is_none(tmp_path) -> None:
    assert load_sms_account(tmp_path / "absent.yaml") is None


def test_load_sms_account_incomplete_is_none(tmp_path) -> None:
    path = _secrets_file(
        tmp_path, sms={"base_url": "http://192.168.1.10:8080", "username": "u"}
    )
    assert load_sms_account(path) is None


def test_load_sms_account_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ARELIS_SMSGATE_PASSWORD", raising=False)
    path = _secrets_file(
        tmp_path,
        sms={
            "base_url": "http://192.168.1.10:8080",
            "username": "u",
            "password": "p",
        },
    )
    account = load_sms_account(path)
    assert account is not None
    assert account.messages_url == "http://192.168.1.10:8080/messages"


def test_messages_url_does_not_double_messages() -> None:
    account = SmsGateAccount(
        "https://api.sms-gate.app/3rdparty/v1/messages", "u", "p"
    )
    assert account.messages_url == "https://api.sms-gate.app/3rdparty/v1/messages"


# --------------------------------------------------------------- provider


class _Transport(httpx.AsyncBaseTransport):
    def __init__(self, *, status: int = 200, body: dict | None = None) -> None:
        self.status = status
        self.body = body if body is not None else {"id": "msg-1", "state": "Pending"}
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body, request=request)


@pytest.mark.asyncio
async def test_android_provider_posts_text_message(monkeypatch) -> None:
    transport = _Transport()
    account = SmsGateAccount("http://192.168.1.10:8080", "user", "pass")
    provider = AndroidSmsProvider(account, timeout_s=5)

    original = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    message_id = await provider.send(phone="+15551112222", body="hello")
    assert message_id == "msg-1"
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.url.path.endswith("/messages")
    assert request.headers.get("authorization", "").startswith("Basic ")
    raw = request.content
    assert b"+15551112222" in raw
    assert b"hello" in raw
    assert b"textMessage" in raw


@pytest.mark.asyncio
async def test_live_provider_posts_to_fresh_companion_url(monkeypatch) -> None:
    transport = _Transport()
    stale = SmsGateAccount(
        "http://192.168.1.10:8080", "arelis", "old", via="companion"
    )
    fresh = SmsGateAccount(
        "http://192.168.1.99:8080", "arelis", "new", via="companion"
    )
    provider = AndroidSmsProvider(stale, timeout_s=5, live=True)
    monkeypatch.setattr("arelis.sms_android.load_sms_account", lambda: fresh)
    original = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    await provider.send(phone="+15551112222", body="hello")
    assert str(transport.requests[0].url).startswith("http://192.168.1.99:8080/")


@pytest.mark.asyncio
async def test_android_provider_auth_failure_is_readable(monkeypatch) -> None:
    transport = _Transport(status=401, body={"message": "unauthorized"})
    account = SmsGateAccount("http://192.168.1.10:8080", "user", "pass")
    provider = AndroidSmsProvider(account, timeout_s=5)
    original = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    with pytest.raises(Exception) as caught:
        await provider.send(phone="+15551112222", body="hello")
    assert "credentials" in str(caught.value).lower()


# ------------------------------------------------------------------- tool


class _FakeProvider:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, phone: str, body: str) -> str:
        self.sent.append({"phone": phone, "body": body})
        return "<sms-id>"


@pytest.mark.asyncio
async def test_send_sms_uses_phone_digits(tmp_path) -> None:
    path = _contacts_file(
        tmp_path,
        "contacts:\n  mom:\n    name: Mom\n    phone: '5559998888'\n",
    )
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: load_contacts(path))
    result = await tool.run(to="mom", body="hello")
    assert result.ok
    assert provider.sent[0]["phone"] == "+15559998888"
    assert provider.sent[0]["body"] == "hello"
    assert "txt.att.net" not in result.output
    assert "your phone" in result.output


@pytest.mark.asyncio
async def test_unknown_contact_refused_before_send(tmp_path) -> None:
    path = _contacts_file(tmp_path, "contacts: {}\n")
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: load_contacts(path))
    result = await tool.run(to="wife", body="hi")
    assert not result.ok
    assert not provider.sent


@pytest.mark.asyncio
async def test_empty_body_refused() -> None:
    tool = SendSmsTool(_FakeProvider(), contacts_loader=lambda: {})
    result = await tool.run(to="wife", body="   ")
    assert not result.ok


# ---------------------------------------------------------------- confirm


def _registry_with_sms() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SendSmsTool(_FakeProvider(), contacts_loader=lambda: {}))
    return registry


def test_sms_is_gated_by_confirm_send() -> None:
    registry = _registry_with_sms()
    assert registry.needs_confirm("send_sms", {})
    assert registry.needs_confirm("send_sms", {}, confirm_image=False)
    assert not registry.needs_confirm("send_sms", {}, confirm_send=False)


def test_sms_can_never_be_batch_approved() -> None:
    assert "send_sms" in NEVER_BATCH


def test_describe_call_uses_full_sms_body(tmp_path) -> None:
    path = _contacts_file(
        tmp_path,
        "contacts:\n  wife:\n    name: Partner\n    phone: '5551112222'\n",
    )
    book = load_contacts(path)
    registry = ToolRegistry()
    registry.register(SendSmsTool(_FakeProvider(), contacts_loader=lambda: book))
    body = "Dear Partner, " + ("late. " * 30)
    args = {"to": "wife", "body": body}
    summary = registry.summarize_call("send_sms", args)
    detail = registry.describe_call("send_sms", args)
    assert "…" in summary
    assert "Partner" in detail
    assert "your phone" in detail
    assert "vtext.com" not in detail
    assert detail.endswith(body.strip())


# -------------------------------------------------------------- registration


def test_no_sms_secrets_means_no_sms_tool(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.mail import MailAccount
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(tools_pkg, "load_sms_account", lambda: None)
    monkeypatch.setattr(
        tools_pkg, "load_account", lambda: MailAccount("me@example.com", "pw")
    )
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = tools_pkg.build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "send_email" in registry.names()
    assert "send_sms" not in registry.names()
    assert "inbound_sms" not in registry.names()


def test_sms_without_email_still_registers(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(tools_pkg, "load_account", lambda: None)
    monkeypatch.setattr(
        tools_pkg,
        "load_sms_account",
        lambda: SmsGateAccount("http://192.168.1.10:8080", "u", "p"),
    )
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = tools_pkg.build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "send_email" not in registry.names()
    assert "send_sms" in registry.names()
    assert "inbound_sms" in registry.names()


def test_job_runner_gets_no_sms(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.workspace import WorkspaceRoots

    monkeypatch.setattr(
        tools_pkg,
        "load_sms_account",
        lambda: SmsGateAccount("http://192.168.1.10:8080", "u", "p"),
    )
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    attended = tools_pkg.build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert "send_sms" in attended.names()
    unattended = tools_pkg.build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, allow_send=False
    )
    assert "send_sms" not in unattended.names()


def test_sms_can_be_disabled_in_config(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
    from arelis.mail import MailAccount
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
    registry = tools_pkg.build_tool_registry(
        {"tools": {"sms": {"enabled": False}}, "agent": {}}, workspace
    )
    assert "send_email" in registry.names()
    assert "send_sms" not in registry.names()


def test_contacts_prompt_line_lists_aliases(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.sms_android.load_sms_account",
        lambda: SmsGateAccount("http://192.168.1.10:8080", "u", "p"),
    )
    monkeypatch.setattr(
        "arelis.mail.load_account",
        lambda: MailAccount("me@example.com", "pw"),
    )
    path = _contacts_file(
        tmp_path,
        """
contacts:
  wife:
    name: Robin
    phone: "5555550123"
    email: "robbie@example.com"
    aliases: [robbie]
""",
    )
    line = contacts_prompt_line(path)
    assert "wife" in line
    assert "robbie" in line
    assert "send_sms" in line
    assert "send_email" in line
    assert "robbie@example.com" in line
    assert contacts_prompt_line(tmp_path / "missing.yaml") == ""


def test_contacts_prompt_line_does_not_offer_send_when_disconnected(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("arelis.sms_android.load_sms_account", lambda: None)
    monkeypatch.setattr("arelis.mail.load_account", lambda: None)
    path = _contacts_file(
        tmp_path,
        """
contacts:
  wife:
    name: Robin
    phone: "5555550123"
    email: "robbie@example.com"
""",
    )
    line = contacts_prompt_line(path)
    assert "wife" in line
    assert "send_sms" not in line
    assert "send_email" not in line


def test_tool_policy_tells_model_to_call_send_sms_not_reask() -> None:
    text = TOOL_POLICY.lower()
    assert "call send_sms immediately" in text
    assert "do not re-ask for the body" in text
