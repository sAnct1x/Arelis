"""Where the user is, resolved from a chain of providers.

A desktop does not know its own city. There is no GPS in it, and nothing on the
disk says "Springfield". What looks like a computer knowing where it is -- typing
"weather" into a search engine and being told your local forecast -- is the
other end of the connection geolocating your IP address and telling you what it
guessed. The client is never told. So the city has to come from one of exactly
two places: the user typing it once, or a network call that asks somebody else.

Hence a chain rather than a setting. Providers are ordered by precedence and
merged field by field, so a profile naming only a city still gets its timezone
from the operating system and, if the network layer is switched on, its
coordinates from an IP lookup. Every field remembers which provider produced it,
because "how do you know that" has to have an answer.

The order matters more than the list:

    100  manual profile   data/profile.yaml, always wins, costs nothing
     90  device GPS       reserved for a mobile build
     80  OS location      reserved; on Windows this is a cloud call in disguise
     40  IP geolocation   opt-in, one request, cached to disk for a day
     20  system locale    timezone and UTC offset, no network, always present

Adding the mobile case later is a class registered at precedence 90, not a
rewrite: the merge, the prompt rendering, and the tool all read UserLocation and
do not care where a field came from.

Nothing here calls the network unless location.network.enabled is set. That is
deliberate and not merely a default: silently asking a third party where this
machine is, on every start, is not a thing a local-first assistant should do
without being told to.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from arelis.location.providers import (
    IPGeolocationProvider,
    LocalProvider,
    ManualProfileProvider,
    NetworkProvider,
    SystemProvider,
)
from arelis.paths import state_dir, user_data_dir

log = logging.getLogger(__name__)

# Every mergeable field. sources is excluded: it is provenance about the others
# rather than a value in its own right, and it is filled in as they are copied.
_ALL_FIELDS = (
    "city",
    "region",
    "postal_code",
    "country",
    "latitude",
    "longitude",
    "timezone",
    "utc_offset",
)

_CACHE_NAME = "location_cache.json"
_DEFAULT_TTL_S = 86400


@dataclass
class UserLocation:
    """Where the user is, as far as anything has been able to establish."""

    city: str = ""
    region: str = ""
    country: str = ""
    postal_code: str = ""
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = ""
    utc_offset: str = ""
    # field name -> provider that supplied it
    sources: dict[str, str] = field(default_factory=dict)

    def known(self) -> bool:
        """True when there is enough here to answer a place-sensitive question."""
        return bool(self.city or self.postal_code or self.has_coordinates())

    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def place(self) -> str:
        """City, region, postal, country -- whichever of those are known.

        The postal code rides with the region rather than standing on its own,
        because that is how an address is written: "Illinois 62701", not "Illinois,
        62701". The country then reads as a separate part instead of running
        into the digits.
        """
        locality = " ".join(p for p in (self.region, self.postal_code) if p)
        return ", ".join(p for p in (self.city, locality, self.country) if p)

    def coordinates(self) -> str:
        if not self.has_coordinates():
            return ""
        return f"{self.latitude:.4f}, {self.longitude:.4f}"

    def prompt_line(self) -> str | None:
        """The system line injected into every turn, or None when nothing is known.

        Kept to one sentence of facts plus one of instruction. It is paid for on
        every turn, and a 7B model given a paragraph about location starts
        mentioning the user's city in answers that have nothing to do with it.
        """
        if not self.known():
            return None
        facts = [f"The user is in {self.place() or 'an unnamed place'}"]
        if self.has_coordinates():
            facts.append(f"at latitude {self.latitude:.4f}, longitude {self.longitude:.4f}")
        clock = self.timezone or self.utc_offset
        if clock:
            facts.append(f"in timezone {clock}")
        return (
            " ".join(facts)
            + ". Use that for anything place-sensitive, such as weather or local "
            "time, instead of asking, unless the user names somewhere else."
        )

    def describe(self) -> str:
        """Multi-line rendering with provenance, for the tool and for humans."""
        lines: list[str] = []
        for name in _ALL_FIELDS:
            value = getattr(self, name)
            if value in ("", None):
                continue
            origin = self.sources.get(name, "unknown")
            lines.append(f"{name}: {value}  (from {origin})")
        if not lines:
            return (
                "No location is known. Set one in data/profile.yaml, or enable "
                "location.network in config to look it up from the IP address."
            )
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def merge_locations(candidates: list[tuple[str, UserLocation]]) -> UserLocation:
    """Combine provider results, highest precedence first, field by field.

    Per field rather than per provider on purpose. Writing only `city:
    Springfield` in the profile should not cost you the timezone the operating
    system already knows, and it should not stop an enabled IP lookup from
    filling in coordinates precise enough for a weather API.
    """
    merged = UserLocation()
    for origin, candidate in candidates:
        for name in _ALL_FIELDS:
            if getattr(merged, name) not in ("", None):
                continue
            value = getattr(candidate, name)
            if value in ("", None):
                continue
            setattr(merged, name, value)
            merged.sources[name] = candidate.sources.get(name, origin)
    return merged


class LocationResolver:
    """Holds the provider chain and the last network answer.

    snapshot() is synchronous and never touches the network, because it is
    called while composing a prompt and a turn must not wait on an HTTP request
    that may time out. refresh() is the only thing that goes out, and it is
    called once at startup and whenever the user explicitly asks.
    """

    def __init__(
        self,
        local: list[LocalProvider],
        network: NetworkProvider | None = None,
        *,
        cache_path: Path | None = None,
        ttl_s: int = _DEFAULT_TTL_S,
    ) -> None:
        self._local = sorted(local, key=lambda p: -p.precedence)
        self._network = network
        self._ttl_s = max(0, int(ttl_s))
        self._cache_path = cache_path or (state_dir() / _CACHE_NAME)
        self._network_result: UserLocation | None = None
        self._network_at = 0.0
        self._load_cache()

    # -------------------------------------------------------------- reading

    def snapshot(self) -> UserLocation:
        """The best current answer. No I/O beyond re-reading a small local file."""
        candidates: list[tuple[str, UserLocation]] = []
        for provider in self._local:
            try:
                result = provider.resolve()
            except Exception:
                log.exception("Location provider %s failed", provider.name)
                continue
            if result is not None:
                candidates.append((provider.name, result))
        if self._network_result is not None and self._network is not None:
            candidates.append((self._network.name, self._network_result))
            # Re-sorted because the network answer is not necessarily last: a
            # future GPS provider outranks it, the system locale does not.
            candidates.sort(key=lambda pair: -self._precedence(pair[0]))
        return merge_locations(candidates)

    def prompt_line(self) -> str | None:
        return self.snapshot().prompt_line()

    def network_enabled(self) -> bool:
        return self._network is not None

    def stale(self) -> bool:
        if self._network is None:
            return False
        if self._network_result is None:
            return True
        return (time.time() - self._network_at) > self._ttl_s

    # -------------------------------------------------------------- writing

    async def refresh(self, *, force: bool = False) -> UserLocation:
        """Run the network provider if it is enabled and due, then re-merge."""
        if self._network is None:
            return self.snapshot()
        if not force and not self.stale():
            return self.snapshot()
        try:
            result = await self._network.resolve()
        except Exception as exc:
            log.warning("Location lookup failed: %s", exc)
            return self.snapshot()
        if result is not None:
            self._network_result = result
            self._network_at = time.time()
            self._save_cache()
        return self.snapshot()

    def _precedence(self, name: str) -> int:
        for provider in self._local:
            if provider.name == name:
                return provider.precedence
        if self._network is not None and self._network.name == name:
            return self._network.precedence
        return 0

    # ---------------------------------------------------------------- cache

    def _load_cache(self) -> None:
        """Reuse yesterday's answer so a restart is not a fresh lookup."""
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        payload = raw.get("location")
        if not isinstance(payload, dict):
            return
        known = {f.name for f in UserLocation.__dataclass_fields__.values()}
        self._network_result = UserLocation(
            **{k: v for k, v in payload.items() if k in known}
        )
        try:
            self._network_at = float(raw.get("resolved_at") or 0.0)
        except (TypeError, ValueError):
            self._network_at = 0.0

    def _save_cache(self) -> None:
        if self._network_result is None:
            return
        payload = {
            "resolved_at": self._network_at,
            "location": self._network_result.as_dict(),
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except OSError:
            # Losing the cache costs one extra request next start, nothing more.
            log.debug("Could not write the location cache", exc_info=True)


def build_location(config: dict[str, Any]) -> LocationResolver:
    """Assemble the chain this config enables."""
    cfg = config.get("location") or {}
    profile_path = Path(str(cfg.get("profile_path") or "data/profile.yaml"))
    if not profile_path.is_absolute():
        profile_path = user_data_dir() / profile_path

    local: list[LocalProvider] = [ManualProfileProvider(profile_path)]
    if cfg.get("use_system", True):
        local.append(SystemProvider())

    network_cfg = cfg.get("network") or {}
    network: NetworkProvider | None = None
    if network_cfg.get("enabled", False):
        network = IPGeolocationProvider(
            url=str(network_cfg.get("url") or IPGeolocationProvider.DEFAULT_URL),
            timeout_s=float(network_cfg.get("timeout_s", 6)),
        )

    return LocationResolver(
        local,
        network,
        ttl_s=int(network_cfg.get("cache_hours", 24)) * 3600,
    )


__all__ = [
    "LocationResolver",
    "UserLocation",
    "build_location",
    "merge_locations",
]
