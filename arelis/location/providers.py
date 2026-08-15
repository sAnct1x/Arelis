"""The individual sources a location can come from.

Two shapes, split by cost rather than by kind. A LocalProvider reads a file or
asks the operating system and answers immediately, so it can run while a prompt
is being composed. A NetworkProvider makes a request and therefore only runs
when something explicitly refreshes it.

Adding a source means writing one class and giving it a precedence. Two slots
are deliberately left empty: a GPS provider at 90 for a mobile build, and the
Windows Location Service at 80, which despite the name resolves position by
sending the Wi-Fi networks in range to Microsoft and is a cloud call wearing an
operating system API for a costume.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

if TYPE_CHECKING:  # pragma: no cover - import cycle only exists for typing
    from arelis.location import UserLocation

log = logging.getLogger(__name__)


class LocalProvider(Protocol):
    """A source that answers without leaving the machine."""

    name: str
    precedence: int

    def resolve(self) -> UserLocation | None:
        ...


class NetworkProvider(Protocol):
    """A source that has to ask somebody else."""

    name: str
    precedence: int

    async def resolve(self) -> UserLocation | None:
        ...


class ManualProfileProvider:
    """What the user wrote in data/profile.yaml. Authoritative.

    Read on every snapshot rather than cached, so editing the file takes effect
    on the next turn instead of the next launch. It is a handful of lines and
    the operating system has it in page cache.

    The file lives under data/ rather than in the config because data/ is
    gitignored: a home address does not belong in a tracked file, and the whole
    point of this provider is that the address is real.
    """

    name = "profile"
    precedence = 100

    def __init__(self, path: Path) -> None:
        self.path = path

    def resolve(self) -> UserLocation | None:
        from arelis.location import UserLocation

        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        except FileNotFoundError:
            return None
        except (OSError, yaml.YAMLError) as exc:
            log.warning("Could not read %s: %s", self.path, exc)
            return None
        if not isinstance(raw, dict):
            return None
        section = raw.get("location")
        data = section if isinstance(section, dict) else raw

        found = UserLocation(
            city=_text(data.get("city")),
            region=_text(data.get("region") or data.get("state")),
            country=_text(data.get("country")),
            postal_code=_text(data.get("postal_code") or data.get("zip")),
            latitude=_number(data.get("latitude") or data.get("lat")),
            longitude=_number(data.get("longitude") or data.get("lon")),
            timezone=_text(data.get("timezone")),
        )
        _stamp(found, self.name)
        return found


class SystemProvider:
    """Timezone and country from the operating system. No network, no permission.

    This is the only layer that is genuinely free, and it is worth having on its
    own: knowing the user's offset from UTC is most of what "what time is it for
    them" needs, and it is correct even on a machine that has never been told
    where it is.

    The IANA name is only reported when tzlocal is installed, because there is
    no portable way to get one out of Windows -- the operating system stores
    "Eastern Standard Time", not "America/New_York", and mapping between the two
    needs a table this does not carry. The UTC offset is always available and is
    what the fallback rests on.
    """

    name = "system"
    precedence = 20

    def resolve(self) -> UserLocation | None:
        from arelis.location import UserLocation

        found = UserLocation(
            country=_system_country(),
            timezone=_iana_timezone(),
            utc_offset=_utc_offset(),
        )
        _stamp(found, self.name)
        return found


class IPGeolocationProvider:
    """City-level position inferred from the public IP address. Opt-in.

    Accuracy is whatever the address database thinks: usually the right metro
    area, sometimes the wrong suburb, and confidently wrong behind a VPN. Good
    enough for a forecast, not good enough to override something the user typed,
    which is why it sits below the profile rather than replacing it.

    The response shape is not standardised across services, so field names are
    matched against a few common spellings. That keeps location.network.url
    swappable between providers without code changes.
    """

    name = "ip"
    precedence = 40
    DEFAULT_URL = "https://ipapi.co/json/"

    def __init__(self, url: str = DEFAULT_URL, timeout_s: float = 6.0) -> None:
        self.url = url
        self.timeout_s = timeout_s

    async def resolve(self) -> UserLocation | None:
        import httpx

        from arelis.location import UserLocation

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.get(
                self.url, headers={"Accept": "application/json"}
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            return None
        if payload.get("error"):
            log.warning("Location lookup refused: %s", payload.get("reason") or "unknown")
            return None

        latitude = _number(_first(payload, "latitude", "lat"))
        longitude = _number(_first(payload, "longitude", "lon", "lng"))
        if latitude is None and longitude is None:
            # ipinfo.io style: a single "loc" field holding "39.78,-89.65".
            latitude, longitude = _split_loc(payload.get("loc"))

        found = UserLocation(
            city=_text(_first(payload, "city")),
            region=_text(_first(payload, "region", "region_name", "state")),
            country=_text(_first(payload, "country_name", "country", "country_code")),
            postal_code=_text(_first(payload, "postal", "postal_code", "zip")),
            latitude=latitude,
            longitude=longitude,
            timezone=_text(_first(payload, "timezone", "time_zone")),
        )
        if not found.known():
            return None
        _stamp(found, self.name)
        return found


# ------------------------------------------------------------------ helpers


def _stamp(found: UserLocation, origin: str) -> None:
    for name, value in found.as_dict().items():
        if name == "sources" or value in ("", None):
            continue
        found.sources[name] = origin


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _split_loc(value: Any) -> tuple[float | None, float | None]:
    if not isinstance(value, str) or "," not in value:
        return None, None
    lat, _, lon = value.partition(",")
    return _number(lat), _number(lon)


def _utc_offset() -> str:
    """Local offset as +HH:MM, which is always knowable without a database."""
    offset = dt.datetime.now().astimezone().utcoffset()
    if offset is None:
        return ""
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, remainder = divmod(abs(total), 3600)
    return f"UTC{sign}{hours:02d}:{remainder // 60:02d}"


def _iana_timezone() -> str:
    try:
        import tzlocal
    except ImportError:
        return ""
    try:
        return str(tzlocal.get_localzone_name() or "")
    except Exception:
        return ""


def _system_country() -> str:
    """Two-letter country from the OS locale, when it can be had cheaply."""
    if sys.platform == "win32":
        name = _windows_locale_name()
        if name:
            return _country_from_tag(name)
    for key in ("LC_ALL", "LC_CTYPE", "LANG"):
        tag = os.environ.get(key, "")
        country = _country_from_tag(tag)
        if country:
            return country
    return ""


def _windows_locale_name() -> str:
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, 85):  # type: ignore[attr-defined]
            return buffer.value
    except Exception:
        return ""
    return ""


def _country_from_tag(tag: str) -> str:
    """en-US, en_US.UTF-8, en_US@euro -> US."""
    if not tag:
        return ""
    head = tag.split(".")[0].split("@")[0]
    parts = head.replace("-", "_").split("_")
    if len(parts) < 2:
        return ""
    code = parts[1].strip().upper()
    return code if len(code) == 2 and code.isalpha() else ""
