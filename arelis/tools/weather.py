"""Forecast for a named place, or for where the user is."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

from arelis.briefing.weather import (
    describe_weather_code,
    fetch_forecast,
    geocode_search_names,
    place_region_match,
    search_geocode,
)
from arelis.location.windows import read_windows_location
from arelis.tools.base import ToolResult


class WeatherTool:
    """One forecast. ``place`` is their words, or empty for where they are.

    Coordinates are not a parameter.
    """

    name = "weather"
    description = (
        "Forecast. Pass place as the user said it. "
        "Leave place empty for where they are."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "place": {
                "type": "string",
                "description": "The place in the user's words. Empty for where they are.",
            },
        },
        "required": [],
    }

    def __init__(
        self,
        location: Any | None = None,
        *,
        windows_location: Any = None,
        home_city: Any = None,
        ip_location: Any = None,
        ip_enabled: bool | None = None,
        geocode: Any = None,
        forecast: Any = None,
    ) -> None:
        self.location = location
        self._windows_location = windows_location
        self._home_city = home_city
        self._ip_location = ip_location
        self._ip_enabled = ip_enabled
        self._geocode = geocode
        self._forecast = forecast

    async def run(self, **kwargs: Any) -> ToolResult:
        asked = " ".join(str(kwargs.get("place") or "").split())
        if asked:
            return await self._for_place(asked)
        here = await self._resolve_here()
        if here is None:
            return ToolResult(
                ok=True,
                output="I couldn't tell where you are. Which city should I check?",
                data={"need_place": True},
            )
        if here.latitude is not None and here.longitude is not None:
            label = here.place or "Your location"
            return await self._sentence(label, here.latitude, here.longitude)
        if here.place:
            return await self._for_place(here.place)
        return ToolResult(
            ok=True,
            output="I couldn't tell where you are. Which city should I check?",
            data={"need_place": True},
        )

    async def _resolve_here(self) -> Here | None:
        windows = await _maybe_await(self._windows_fn())
        found = _as_here(windows)
        if found is not None and (found.place or found.latitude is not None):
            return found
        home = self._home_fn()
        if isinstance(home, str) and home.strip():
            return Here(place=home.strip())
        if not self._ip_on():
            return None
        ip = await _maybe_await(self._ip_fn())
        found = _as_here(ip)
        if found is not None and (found.place or found.latitude is not None):
            return found
        return None

    def _windows_fn(self) -> Any:
        if self._windows_location is not None:
            return self._windows_location()
        return read_windows_location()

    def _home_fn(self) -> str:
        if self._home_city is not None:
            value = self._home_city()
            return str(value or "")
        location = self.location
        reader = getattr(location, "home_city", None)
        if callable(reader):
            return str(reader() or "")
        return ""

    def _ip_fn(self) -> Any:
        if self._ip_location is not None:
            return self._ip_location()
        location = self.location
        reader = getattr(location, "lookup_ip", None)
        if callable(reader):
            return reader()
        return None

    def _ip_on(self) -> bool:
        """IP lookup is opt-in. Missing means off, and the call is not made."""
        if self._ip_enabled is not None:
            return bool(self._ip_enabled)
        flag = getattr(self.location, "network_enabled", None)
        if callable(flag):
            return bool(flag())
        return False

    def _home_region(self) -> str:
        home = self._home_fn()
        if not isinstance(home, str):
            return ""
        parts = [part.strip() for part in home.split(",") if part.strip()]
        if len(parts) >= 2:
            return parts[-1]
        return ""

    async def _for_place(self, asked: str) -> ToolResult:
        try:
            rows = await self._geocode_rows(asked)
        except Exception as exc:  # a dead lookup is the plain failure line
            if _service_down(exc):
                return _unreachable()
            return _miss(asked)
        named = _rows_for_named_region(asked, rows)
        if named is not None:
            if not named:
                return _miss(asked)
            return await self._from_row(asked, named[0])
        choice = self._pick_open(rows)
        if isinstance(choice, list):
            labels = [place_label(row) for row in choice]
            labels = [label for label in labels if label]
            return ToolResult(
                ok=True,
                output=clarify(labels[:3]),
                data={"ambiguous": True, "alternatives": labels[:3]},
            )
        if choice is None:
            return _miss(asked)
        return await self._from_row(asked, choice)

    async def _geocode_rows(self, asked: str) -> list[dict[str, Any]]:
        names = [name for name in geocode_search_names(asked) if name]
        if not names:
            return []
        if len(names) == 1:
            return await self._rows_named(names[0])
        # The shorter name is the city. One lookup is enough when a hit's
        # own state or country is the trailing word.
        short = await self._rows_named(names[-1])
        if any(place_region_match(asked, row) for row in short):
            return short
        full = await self._rows_named(names[0])
        # "Paris today" is not a region. The full string comes back empty.
        # The shorter name already has the cities, so the usual pick runs.
        if _full_string_usable(asked, full):
            return full
        return short

    async def _rows_named(self, query: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        hits = await _maybe_await(self._geocode_fn(query))
        for row in hits or []:
            if not isinstance(row, dict):
                continue
            key = (
                str(row.get("name") or "").casefold(),
                str(row.get("admin1") or "").casefold(),
                str(row.get("country") or "").casefold(),
                str(row.get("latitude") or ""),
                str(row.get("longitude") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
        return rows

    def _pick_open(
        self, rows: list[dict[str, Any]]
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        distinct: list[dict[str, Any]] = []
        labels: list[str] = []
        for row in rows:
            label = place_label(row)
            if not label or label in labels:
                continue
            labels.append(label)
            distinct.append(row)
        if not distinct:
            return None
        if len(distinct) == 1:
            return distinct[0]
        ranked = sorted(distinct, key=_population, reverse=True)
        top = _population(ranked[0])
        nxt = _population(ranked[1])
        # Five times the next city's population is one clear place.
        if top > 0 and (nxt <= 0 or top >= 5 * nxt):
            return ranked[0]
        home = self._home_region()
        if home:
            hits = [row for row in distinct if place_region_match(home, row)]
            if len(hits) == 1:
                return hits[0]
        return distinct

    async def _from_row(self, asked: str, row: dict[str, Any]) -> ToolResult:
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            return _miss(asked)
        return await self._sentence(place_label(row) or asked, lat, lon, fallback=asked)

    async def _sentence(
        self,
        label: str,
        lat: float,
        lon: float,
        *,
        fallback: str = "",
    ) -> ToolResult:
        try:
            data = await _maybe_await(self._forecast_fn(lat, lon))
        except Exception as exc:  # a dead forecast is the plain failure line
            if _service_down(exc):
                return _unreachable()
            return _miss(fallback or label)
        if not isinstance(data, dict):
            return _miss(fallback or label)
        line = forecast_sentence(label, data)
        if not line:
            return _miss(fallback or label)
        return ToolResult(
            ok=True,
            output=line,
            data={"place": label, "latitude": lat, "longitude": lon},
        )

    def _geocode_fn(self, query: str) -> Any:
        if self._geocode is not None:
            return self._geocode(query)
        return search_geocode(query)

    def _forecast_fn(self, lat: float, lon: float) -> Any:
        if self._forecast is not None:
            return self._forecast(lat, lon)
        return fetch_forecast(lat, lon, days=1)


_HOMEISH_PLACE = frozenset(
    {
        "outside",
        "outdoors",
        "here",
        "home",
        "there",
        "local",
        "nearby",
        "me",
        "us",
        "it",
        "this",
        "that",
        "my",
        "our",
    }
)
_NOT_A_PLACE = re.compile(
    r"(?i)^(?:the\s+)?(?:"
    r"outside|outdoors|here|home|there|local|nearby|my|"
    r"morning|afternoon|evening|night|tonight|"
    r"today|tonight|tomorrow|morrow|weekend|week|"
    r"going(?:\s+to(?:\s+be)?)?|gonna|will|be|right|currently|"
    r"celsius|fahrenheit|degrees|"
    r"a\s+(?:few\s+)?days?|\d+\s+days?|"
    r"call|use|run|try|invoke|tool|days"
    r")$"
)
_DATEISH = re.compile(
    r"(?i)\b(?:"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|\d{1,2}/\d{1,2}(?:/\d{2,4})?"
    r")\b"
)
_WEEKDAY = re.compile(
    r"(?i)\b(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|"
    r"thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b"
)
_TOOL_INSTRUCTION = re.compile(
    r"(?i)\b(?:please\s+)?(?:call|use|run|try|invoke)\s+"
    r"(?:the\s+)?(?:weather\s+)?tool\b.*$"
)
_WEATHER_NOISE = re.compile(
    r"(?i)\b(?:"
    r"web\s+search|search(?:\s+the\s+web)?(?:\s+for)?|google|"
    r"look(?:ing)?\s+up|lookup|"
    r"what(?:'s|s|\s+is)|how(?:'s|\s+is)|tell\s+me|give\s+me|check|"
    r"the|a|an|like|of|on|at|this|that|please|now|right|then|"
    r"going(?:\s+to)?|gonna|will|be|currently|looking|"
    r"does|say|after|still|even|maybe|than|about|just|"
    r"weather|forecast|temperature|temps?|rain(?:y|ing)?|snow(?:y|ing)?|"
    r"humid(?:ity)?|umbrella|conditions?|report|"
    r"today|tonight|tomorrow|morrow|weekend|"
    r"outside|outdoors|"
    r"e-?mail|mail|inbox|send|summary|digest|briefing|every|day|"
    r"call|use|run|try|invoke|tool|days|"
    r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)"
    r")\b"
)
_LEADING_CHAT = re.compile(
    r"(?i)^(oh|hey|hay|hi|yo|well|yeah|yep|yes|so|um+|uh+)\b[\s,]+"
)
_PLACE_PROSE = frozenset(
    {
        "does",
        "say",
        "after",
        "before",
        "still",
        "even",
        "maybe",
        "than",
        "then",
        "just",
        "really",
        "very",
        "almost",
        "every",
        "other",
        "going",
        "gonna",
        "will",
        "been",
        "like",
        "about",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "why",
        "to",
        "from",
        "with",
        "into",
    }
)
_IN_PLACE = re.compile(r"(?i)\b(?:in|near|around|for)\s+")
_PLACE_SPLIT = re.compile(r"(?i)\s*,?\s*\b(?:and|or)\b\s*")
_MAX_WEATHER_PLACES = 4
_BEYOND_TODAY = re.compile(
    r"(?i)\b(?:"
    r"tomorrow|weekend|next\s+(?:week|mon|tue|wed|thu|fri|sat|sun)"
    r"|this\s+weekend"
    r"|(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}"
    r")\b"
)
_COORD_KEYS = ("latitude", "longitude", "lat", "lon")


def weather_wants_beyond_today(text: str) -> bool:
    return bool(_BEYOND_TODAY.search(normalize_weather_ask(text)))


# City + state: "Baltimore, OH" and "baltimore ohio" are one place.
# Phrases first so West Virginia does not become Virginia.
_US_STATE_PHRASES: dict[tuple[str, ...], str] = {
    ("new", "hampshire"): "nh",
    ("new", "jersey"): "nj",
    ("new", "mexico"): "nm",
    ("new", "york"): "ny",
    ("north", "carolina"): "nc",
    ("south", "carolina"): "sc",
    ("north", "dakota"): "nd",
    ("south", "dakota"): "sd",
    ("rhode", "island"): "ri",
    ("west", "virginia"): "wv",
    ("district", "of", "columbia"): "dc",
}
_US_STATE_NAME_TO_ABBR = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virginia": "va",
    "washington": "wa",
    "wisconsin": "wi",
    "wyoming": "wy",
}
def _state_display(abbr: str) -> str:
    if abbr == "dc":
        return "District of Columbia"
    for parts, code in _US_STATE_PHRASES.items():
        if code == abbr:
            return " ".join(word.capitalize() for word in parts)
    for name, code in _US_STATE_NAME_TO_ABBR.items():
        if code == abbr:
            return name.capitalize()
    return abbr


_ABBR_TO_NAME = {
    abbr: _state_display(abbr)
    for abbr in set(_US_STATE_NAME_TO_ABBR.values())
    | {code for _parts, code in _US_STATE_PHRASES.items()}
}


@dataclass(frozen=True)
class Here:
    """A place the machine already knows, before any forecast."""

    place: str = ""
    latitude: float | None = None
    longitude: float | None = None


def _miss(place: str) -> ToolResult:
    return ToolResult(
        ok=False,
        output=f"I couldn't get the forecast for {place}.",
    )


def _unreachable() -> ToolResult:
    return ToolResult(
        ok=False,
        output="I couldn't reach the weather service.",
    )


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _as_here(value: Any) -> Here | None:
    if value is None:
        return None
    if isinstance(value, Here):
        if value.place.strip() or value.latitude is not None:
            return value
        return None
    city = str(getattr(value, "city", "") or "").strip()
    region = str(getattr(value, "region", "") or "").strip()
    place = ", ".join(part for part in (city, region) if part)
    if not place:
        place = str(getattr(value, "place", "") or "").strip()
    lat = getattr(value, "latitude", None)
    lon = getattr(value, "longitude", None)
    try:
        lat_f = float(lat) if lat is not None else None
        lon_f = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lat_f = lon_f = None
    if not place and lat_f is None:
        return None
    return Here(place=place, latitude=lat_f, longitude=lon_f)


def _population(row: dict[str, Any]) -> float:
    try:
        return float(row.get("population") or 0)
    except (TypeError, ValueError):
        return 0.0


def _rows_for_named_region(
    asked: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Matching rows when they named a region. None when they did not."""
    raw = " ".join((asked or "").split())
    if not raw:
        return []
    matched = [row for row in rows if place_region_match(raw, row)]
    if "," in raw:
        return matched
    if matched:
        return matched
    return None


def _full_string_usable(asked: str, rows: list[dict[str, Any]]) -> bool:
    """True when the full-string search itself has a city to use."""
    if not rows:
        return False
    named = _rows_for_named_region(asked, rows)
    if named is None:
        return True
    return bool(named)


def _service_down(exc: BaseException) -> bool:
    """Timeouts, connection errors, 429, and 5xx. Not the error text."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = int(getattr(exc.response, "status_code", 0) or 0)
        return code == 429 or code >= 500
    return False


_US_COUNTRY_NAMES = frozenset(
    {
        "us",
        "usa",
        "united states",
        "united states of america",
    }
)


def _is_us_place(entry: dict[str, Any]) -> bool:
    code = " ".join(str(entry.get("country_code") or "").split()).casefold()
    if code in _US_COUNTRY_NAMES:
        return True
    country = " ".join(str(entry.get("country") or "").split()).casefold()
    return country in _US_COUNTRY_NAMES


def place_label(entry: dict[str, Any]) -> str:
    """City, State in the US. City, Country everywhere else.

    The country is the geocoder's country name. A region is not a substitute
    for it.
    """
    name = " ".join(str(entry.get("name") or "").split())
    admin = " ".join(str(entry.get("admin1") or "").split())
    country = " ".join(str(entry.get("country") or "").split())
    if _is_us_place(entry):
        if name and admin and admin.casefold() != name.casefold():
            return f"{name}, {admin}"
        if name and country and country.casefold() != name.casefold():
            return f"{name}, {country}"
        return name
    if name and country and country.casefold() != name.casefold():
        return f"{name}, {country}"
    if name and admin and admin.casefold() != name.casefold():
        return f"{name}, {admin}"
    return name


def clarify(labels: list[str]) -> str:
    if len(labels) >= 3:
        return f"Did you mean {', '.join(labels[:-1])}, or {labels[-1]}?"
    if len(labels) == 2:
        return f"Did you mean {labels[0]} or {labels[1]}?"
    if labels:
        return f"Did you mean {labels[0]}?"
    return "Which city should I check?"


def _whole(value: Any) -> str:
    try:
        return str(round(float(value)))
    except (TypeError, ValueError):
        return ""


def forecast_sentence(label: str, data: dict[str, Any]) -> str:
    current = data.get("current") or {}
    daily = data.get("daily") or []
    today = daily[0] if daily else {}
    temp = _whole(current.get("temperature_2m"))
    high = _whole(today.get("temperature_2m_max"))
    low = _whole(today.get("temperature_2m_min"))
    if not label or not temp or not high or not low:
        return ""
    condition = describe_weather_code(current.get("weather_code")) or "unknown"
    return f"{label}: {temp}°F and {condition}, high {high}°F, low {low}°F."


def place_query_for_geocode(name: str) -> str:
    """Put a comma back before a state so the gazetteer can find the city.

    Place extraction drops commas, and "Springfield Illinois" is not a
    search the gazetteer answers. "Springfield, Illinois" is.
    """
    tokens = [part for part in (name or "").split() if part]
    if len(tokens) >= 4:
        phrase3 = tuple(part.lower() for part in tokens[-3:])
        if phrase3 in _US_STATE_PHRASES and tokens[:-3]:
            return " ".join(tokens[:-3]) + ", " + " ".join(tokens[-3:])
    if len(tokens) >= 3:
        phrase2 = tuple(part.lower() for part in tokens[-2:])
        if phrase2 in _US_STATE_PHRASES and tokens[:-2]:
            return " ".join(tokens[:-2]) + ", " + " ".join(tokens[-2:])
    if len(tokens) >= 2 and tokens[-1].lower() in _US_STATE_NAME_TO_ABBR:
        return " ".join(tokens[:-1]) + ", " + tokens[-1]
    return " ".join(tokens)


def normalize_weather_ask(text: str) -> str:
    """Fold split day-words ('to morrow') before extract and tomorrow matching."""
    raw = text or ""
    raw = re.sub(r"(?i)\bto[\s-]+morrow\b", "tomorrow", raw)
    raw = re.sub(r"(?i)\bto[\s-]+day\b", "today", raw)
    raw = re.sub(r"(?i)\bto[\s-]+night\b", "tonight", raw)
    return raw


def _is_place_candidate(candidate: str) -> bool:
    """True for a city-ish name, not leftover chat ('Oh does it say after to')."""
    text = _LEADING_CHAT.sub("", candidate or "").strip(" -,")
    if not text or _NOT_A_PLACE.match(text):
        return False
    tokens = [t for t in re.findall(r"[A-Za-z]+", text) if t]
    if not tokens or len(tokens) > 4:
        return False
    abbrs = set(_US_STATE_NAME_TO_ABBR.values())
    if len(tokens) == 1 and tokens[0].lower() in abbrs:
        return False
    if len(tokens) == 1 and tokens[0].lower() in _US_STATE_NAME_TO_ABBR:
        return False
    substance = [
        t
        for t in tokens
        if t.lower() not in _PLACE_PROSE and t.lower() not in _HOMEISH_PLACE
    ]
    if not substance:
        return False
    # 'to morrow' is prose + one leftover token, not a city. Real places
    # with a function word in them still have two substance tokens.
    if any(t.lower() in _PLACE_PROSE for t in tokens) and (
        len(tokens) >= 3 or len(substance) < 2
    ):
        return False
    return True


def weather_place_key(place: str | None) -> str:
    """Compare places without caring about case, commas, or OH vs Ohio."""
    raw = (place or "").strip().casefold()
    raw = re.sub(r"[^\w\s]", " ", raw)
    tokens = raw.split()
    if len(tokens) >= 3:
        phrase3 = tuple(tokens[-3:])
        if phrase3 in _US_STATE_PHRASES:
            tokens = [*tokens[:-3], _US_STATE_PHRASES[phrase3]]
    if len(tokens) >= 2:
        phrase2 = tuple(tokens[-2:])
        if phrase2 in _US_STATE_PHRASES:
            tokens = [*tokens[:-2], _US_STATE_PHRASES[phrase2]]
        elif tokens[-1] in _US_STATE_NAME_TO_ABBR:
            tokens = [*tokens[:-1], _US_STATE_NAME_TO_ABBR[tokens[-1]]]
    return " ".join(tokens)


def extract_weather_places(text: str) -> list[str]:
    """Named cities in the ask, in order, at most four. Empty list means home."""
    raw = " ".join(normalize_weather_ask(text).split())
    if not raw:
        return []
    raw = _TOOL_INSTRUCTION.sub(" ", raw)
    raw = " ".join(raw.split())
    if not raw:
        return []
    hits = list(_IN_PLACE.finditer(raw))
    if hits:
        chunks = []
        for i, match in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(raw)
            chunks.append(raw[match.end() : end])
        blob = " ".join(chunks)
    else:
        blob = raw
    blob = _DATEISH.sub(" ", blob)
    blob = _WEEKDAY.sub(" ", blob)
    blob = _WEATHER_NOISE.sub(" ", blob)
    want_home = False
    out: list[str] = []
    seen: set[str] = set()
    for part in _PLACE_SPLIT.split(blob):
        candidate = re.sub(r"[?!.,:;]+", " ", part)
        candidate = " ".join(candidate.split()).strip(" -")
        if not candidate or _NOT_A_PLACE.match(candidate):
            continue
        if candidate.lower() in _HOMEISH_PLACE:
            want_home = True
            continue
        if not re.search(r"[A-Za-z]", candidate):
            continue
        if not _is_place_candidate(candidate):
            continue
        key = weather_place_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= _MAX_WEATHER_PLACES:
            break
    if re.search(r"(?i)\b(?:here|home|outside|outdoors|near\s+me)\b", raw):
        want_home = True
    if want_home and "" not in seen and len(out) < _MAX_WEATHER_PLACES:
        out.insert(0, "")
    return out


def weather_places_wanted(text: str) -> list[str]:
    """Places this turn must fetch. A lone empty string is the user's home."""
    places = extract_weather_places(text)
    return places if places else [""]


def weather_places_missing(
    text: str,
    ok_keys: set[str],
    failed_keys: set[str] | None = None,
) -> list[str]:
    """Named (or home) places not yet covered by a successful weather call."""
    skip = set(ok_keys or ()) | set(failed_keys or ())
    return [
        place
        for place in weather_places_wanted(text)
        if weather_place_key(place) not in skip
    ]


def extract_weather_place(text: str) -> str:
    """First extra city named in the ask, or empty for the user's own location."""
    places = [p for p in extract_weather_places(text) if p]
    return places[0] if places else ""


_WEATHER_HOURLY = re.compile(
    r"(?i)(?:"
    r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|o'?clock)|"
    r"\b(?:by|around|about|after|before)\s+\d{1,2}\s*(?:am|pm)|"
    r"\bthis\s+(?:morning|afternoon|evening)|"
    r"\btonight\b|"
    r"\blater\s+(?:today|on)\b|"
    r"\bin\s+(?:an\s+hour|\d{1,2}\s+hours?)|"
    r"\bnext\s+(?:few\s+)?hours?\b|"
    r"\bhourly\b|"
    r"\bby\s+the\s+hour\b|"
    r"\brush\s+hour\b|"
    r"\btime\s+of\s+day\b"
    r")"
)

_WEATHER_HOURLY_TOMORROW = re.compile(
    r"(?i)\btomorrow\s+(?:morning|afternoon|evening|night)\b|"
    r"\b(?:morning|afternoon|evening|night)\s+tomorrow\b"
)

_WEATHER_PAST = re.compile(
    r"(?i)(?:"
    r"\byesterday\b|"
    r"\blast\s+night\b|"
    r"\bovernight\b|"
    r"\bwhat\s+was\s+(?:the\s+)?(?:weather|it|the\s+temp\w*)|"
    r"\bhow\s+(?:much\s+)?(?:rain|snow)\s+(?:did|fell)\b|"
    r"\bwas\s+it\s+(?:rain\w*|snow\w*|hot|cold|warm|cool)\b"
    r")"
)

_HOURS_TODAY = 12
_HOURS_TOMORROW = 36


def weather_wants_hourly(text: str) -> int:
    """Hours of hourly detail this ask needs, or 0 when a daily row will do."""
    raw = normalize_weather_ask(text)
    if _WEATHER_HOURLY_TOMORROW.search(raw):
        return _HOURS_TOMORROW
    if _WEATHER_HOURLY.search(raw):
        return _HOURS_TODAY
    return 0


def weather_wants_past(text: str) -> int:
    """Days of history this ask needs, or 0. Yesterday is as far as it guesses."""
    return 1 if _WEATHER_PAST.search(text or "") else 0


def draft_weather_args(text: str) -> dict[str, Any]:
    """Args for an injected weather call. days always covers tomorrow."""
    out: dict[str, Any] = {"days": 3}
    place = extract_weather_place(text)
    if place:
        out["place"] = place
    hours = weather_wants_hourly(text)
    if hours:
        out["hours"] = hours
    past = weather_wants_past(text)
    if past:
        out["past_days"] = past
    return out


def fill_weather_args(args: dict[str, Any] | None, text: str) -> dict[str, Any]:
    """Keep a named place. Days, hours, and past days are not arguments."""
    drafted = draft_weather_args(text)
    out = dict(args or {})
    for key in _COORD_KEYS:
        out.pop(key, None)
    for key in ("days", "hours", "past_days"):
        out.pop(key, None)
    if extract_weather_place(text):
        if drafted.get("place") and not str(out.get("place") or "").strip():
            out["place"] = drafted["place"]
    else:
        out.pop("place", None)
    return out
