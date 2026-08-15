"""Texts through your own Android phone, using SMSGate.

The phone is the radio and Arelis is the brain. SMSGate (https://sms-gate.app)
runs a small HTTP server on the handset, and a POST here becomes a normal SMS
off the SIM already in it. So the text arrives from your number, the reply comes
back to your phone, and it costs nothing beyond the plan you already pay for —
which is the whole reason this replaced carrier email gateways.

Credentials live in data/secrets.yaml beside the mail account and load the same
way: absent means None, and None means send_sms is never registered at all.
Nothing here touches the mail account; configuring one does not configure the
other.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from arelis.paths import state_dir
from arelis.sms import SmsSendError

log = logging.getLogger(__name__)

PASSWORD_ENV = "ARELIS_SMSGATE_PASSWORD"
SECRETS_PATH = state_dir() / "secrets.yaml"

SETUP_HINT = (
    "SMS is not configured. Install SMSGate (https://sms-gate.app) on your "
    "Android phone, then copy the base URL, username, and password it shows "
    "into the sms: block of data/secrets.yaml. See README > SMS."
)


@dataclass(frozen=True)
class SmsGateAccount:
    """Where SMSGate is listening, and how to log in to it."""

    base_url: str
    username: str
    password: str
    # 0 leaves the choice to the app's own setting, which is right for a
    # single-SIM phone and for anyone who already picked a line in SMSGate.
    sim_number: int = 0
    # Inbound list (GET /inbox) is Local Server only. Cloud has no sync inbox
    # read — see arelis/sms_inbound.py. When outbound uses Cloud, point this at
    # the phone's LAN URL so send and receive can use different bases.
    inbox_base_url: str = ""
    inbox_username: str = ""
    inbox_password: str = ""

    @property
    def messages_url(self) -> str:
        """The send endpoint.

        Only the last segment is ours to add. The prefix in front of it differs
        per mode and guessing it is exactly how you earn a 404: Cloud is
        https://api.sms-gate.app/3rdparty/v1, a phone on the LAN is
        http://PHONE_IP:8080, a private server ends in /api/3rdparty/v1. All
        three take /messages underneath, so the user pastes the base for the
        mode they turned on and this appends the rest.
        """
        base = self.base_url.strip().rstrip("/")
        if base.endswith("/messages"):
            return base
        return f"{base}/messages"

    @property
    def _inbox_base(self) -> str:
        return (self.inbox_base_url or self.base_url).strip().rstrip("/")

    @property
    def inbox_url(self) -> str:
        """Local Server GET /inbox. Not available on the Cloud API."""
        base = self._inbox_base
        if base.endswith("/inbox"):
            return base
        return f"{base}/inbox"

    @property
    def inbox_refresh_url(self) -> str:
        """Local Server POST /inbox/refresh — re-indexes device SMS into GET /inbox."""
        inbox = self.inbox_url
        if inbox.endswith("/refresh"):
            return inbox
        return f"{inbox}/refresh"

    @property
    def inbox_auth(self) -> tuple[str, str]:
        user = (self.inbox_username or self.username).strip()
        password = (self.inbox_password or self.password).strip()
        return user, password

    def supports_inbox_poll(self) -> bool:
        """True when the inbox base is a Local Server URL, not Cloud."""
        base = (self.inbox_base_url or self.base_url).strip().lower()
        return bool(base) and "api.sms-gate.app" not in base


def load_sms_account(path: Path | None = None) -> SmsGateAccount | None:
    """Read the SMSGate account, or None when it has not been set up yet.

    None rather than an exception, for the same reason mail does it: a missing
    config should become "she has no way to text" instead of "she has a tool
    that fails every time she reaches for it".
    """
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return None

    section = raw.get("sms") if isinstance(raw, dict) else None
    data = section if isinstance(section, dict) else {}

    base_url = str(data.get("base_url") or "").strip()
    username = str(data.get("username") or "").strip()
    raw_password = os.environ.get(PASSWORD_ENV) or str(data.get("password") or "")
    password = raw_password.strip()
    if not (base_url and username and password):
        return None

    try:
        sim_number = int(data.get("sim_number") or 0)
    except (TypeError, ValueError):
        sim_number = 0

    inbox_base_url = str(data.get("inbox_base_url") or "").strip()
    inbox_username = str(data.get("inbox_username") or "").strip()
    raw_inbox_password = str(data.get("inbox_password") or "")
    inbox_password = raw_inbox_password.strip()
    return SmsGateAccount(
        base_url=base_url,
        username=username,
        password=password,
        sim_number=sim_number,
        inbox_base_url=inbox_base_url,
        inbox_username=inbox_username,
        inbox_password=inbox_password,
    )


class AndroidSmsProvider:
    """One POST per text. No pooling; sends are rare and far apart.

    A successful call means SMSGate queued the message on the phone, which is
    still not a read receipt. It is a much better claim than the old one: the
    handset either sends it or reports why, rather than an SMTP server accepting
    mail for a domain that stopped existing.
    """

    def __init__(self, account: SmsGateAccount, *, timeout_s: float = 30.0) -> None:
        self.account = account
        self.timeout_s = timeout_s

    async def send(self, *, phone: str, body: str) -> str:
        payload: dict[str, Any] = {
            "phoneNumbers": [phone],
            "textMessage": {"text": body},
        }
        if self.account.sim_number:
            payload["simNumber"] = self.account.sim_number

        url = self.account.messages_url
        # Deliberately not run through check_url_allowed, unlike the web tools.
        # A private LAN address is the point of Local Server mode, and this URL
        # came out of the user's own secrets file rather than out of a model.
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    url,
                    json=payload,
                    auth=(self.account.username, self.account.password),
                )
        except httpx.TimeoutException:
            raise SmsSendError(
                f"SMSGate did not answer within {self.timeout_s:g}s. Check the "
                f"phone is awake, on the network, and still running the server."
            )
        except httpx.HTTPError as exc:
            raise SmsSendError(
                f"Could not reach SMSGate at {url}: {exc}. Local Server mode "
                f"needs the phone on this network with the server switched on; "
                f"Cloud mode needs the phone online."
            )

        if response.status_code in {401, 403}:
            raise SmsSendError(
                "SMSGate rejected the credentials. Copy the username and "
                "password the app shows into the sms: block of "
                "data/secrets.yaml."
            )
        if response.status_code == 404:
            raise SmsSendError(
                f"SMSGate returned 404 for {url}. base_url needs the prefix for "
                f"the mode you turned on: https://api.sms-gate.app/3rdparty/v1 "
                f"for Cloud, http://PHONE_IP:8080 for Local Server."
            )
        if response.status_code >= 400:
            raise SmsSendError(
                f"SMSGate refused the message ({response.status_code}): "
                f"{_detail(response)}"
            )
        return _message_id(response)


def _message_id(response: httpx.Response) -> str:
    """SMSGate answers with the queued message's id and state."""
    data = _json(response)
    if isinstance(data, dict):
        return str(data.get("id") or "")
    return ""


def _detail(response: httpx.Response) -> str:
    data = _json(response)
    if isinstance(data, dict):
        message = data.get("message") or data.get("error")
        if message:
            return str(message)
    return response.text.strip()[:200] or "(no detail)"


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
