from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from arelis.contacts import (
    Contact,
    load_contacts,
    normalize_phone,
)
from arelis.mail import MailAccount
from arelis.sms import (
    format_sms_confirm,
    resolve_sms_target,
    send_operator_sms,
)
from arelis.sms_android import (
    AndroidSmsProvider,
    SmsGateAccount,
)
from arelis.tools.base import ToolRegistry
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


# --------------------------------------------------------------------- sms


def test_agent_target_still_refuses_unknown_names() -> None:
    err = resolve_sms_target("xyzzy", {})
    assert isinstance(err, str)
    assert "No number" in err


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
async def test_android_provider_companion_401_does_not_blame_smsgate(
    monkeypatch,
) -> None:
    transport = _Transport(status=401, body={"error": "unauthorized"})
    account = SmsGateAccount(
        "http://192.168.1.10:8080", "arelis", "key", via="companion"
    )
    provider = AndroidSmsProvider(account, timeout_s=5)
    original = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    with pytest.raises(Exception) as caught:
        await provider.send(phone="+15551112222", body="hello")
    text = str(caught.value).lower()
    assert "radio key" in text
    assert "smsgate" not in text
    assert "secrets.yaml" not in text


# ------------------------------------------------------------------- tool


class _FakeProvider:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send(self, *, phone: str, body: str) -> str:
        self.sent.append({"phone": phone, "body": body})
        return "<sms-id>"


@pytest.mark.asyncio
async def test_unknown_contact_refused_before_send(tmp_path) -> None:
    path = _contacts_file(tmp_path, "contacts: {}\n")
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: load_contacts(path))
    result = await tool.run(to="wife", body="hi")
    assert not result.ok
    assert not provider.sent


# ---------------------------------------------------------------- confirm


def _registry_with_sms() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SendSmsTool(_FakeProvider(), contacts_loader=lambda: {}))
    return registry


def test_sms_is_gated_by_confirm_send() -> None:
    registry = _registry_with_sms()
    assert registry.needs_confirm("send_sms", {})
    assert registry.needs_confirm("send_sms", {}, confirm_image=False)
    assert registry.needs_confirm("send_sms", {}, confirm_send=False)


# -------------------------------------------------------------- registration


def test_no_sms_secrets_means_no_sms_tool(tmp_path, monkeypatch) -> None:
    from arelis import tools as tools_pkg
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


