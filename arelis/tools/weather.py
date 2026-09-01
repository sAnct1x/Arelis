"""Local weather via Open-Meteo — no model-invented URLs, no JS weather sites."""

from __future__ import annotations

import re
from typing import Any

from arelis.briefing.weather import (
    describe_weather_code,
    fetch_forecast,
    geocode_place,
)
from arelis.tools.base import ToolResult


class WeatherTool:
    """Forecast for the user's place, or a named city via ``place``. Confirm not required.

    Only the user's place, unless they named another city in ``place``.
    Coordinates cannot be passed in, and that is on purpose: small models invent
    the lat/lon of whichever large city they have seen most often for "weather
    outside", which returns a confident forecast for somewhere the user is not.
    ``test_weather_ignores_model_invented_coords`` pins that.

    ``run`` used to read latitude/longitude from kwargs as a fallback, which four
    different places then described four different ways — the schema declared
    neither, the description forbade both, the skill card said to pass them for a
    named place, and the failure message asked for them. None of it worked: the
    profile always won, so a named place silently returned home weather, and once
    the cross-tool-args gate declared its keys an undeclared latitude would have
    been rejected outright. A named city is ``place``: this tool geocodes it.
    """

    name = "weather"
    description = (
        "Get current conditions and the next few days of forecast from Open-Meteo. "
        "Default is the user's profile location. For another city pass place "
        "(a name this tool geocodes — never coordinates). "
        "days is how many daily rows including today: 1 is today only, "
        "tomorrow needs 2 or more, default 3. "
        "Do not scrape AccuWeather, weather.com, or invent Open-Meteo query strings."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": (
                    "Daily rows including today (1-7). 1=today only. "
                    "Tomorrow needs 2+. Default 3."
                ),
            },
            "place": {
                "type": "string",
                "description": (
                    "City to forecast, e.g. 'Springfield, Illinois'. Geocoded here. "
                    "Omit for the user's own location. Never pass coordinates."
                ),
            },
        },
        "required": [],
    }

    def __init__(self, location: Any | None = None) -> None:
        self.location = location

    async def run(self, **kwargs: Any) -> ToolResult:
        asked = str(kwargs.get("place") or "").strip()
        snap = None
        if self.location is not None and hasattr(self.location, "snapshot"):
            snap = self.location.snapshot()
        refresh = getattr(self.location, "refresh", None)
        # Kept so the failure below can name its real cause. "No coordinates on
        # file" sends the user to edit a profile that was never the problem.
        refresh_failed = ""
        lat: float | None = None
        lon: float | None = None
        place = ""
        if asked:
            place = asked
            try:
                coords = await geocode_place(asked)
            except Exception as exc:
                return ToolResult(
                    ok=False,
                    output=f"[fail:weather] weather failed: {exc}",
                )
            if coords is None:
                return ToolResult(
                    ok=False,
                    output=(
                        f"[fail:weather] Could not geocode {asked!r}. "
                        "Name a real city; do not pass coordinates."
                    ),
                )
            lat, lon = coords
        else:
            if (
                snap is not None
                and not snap.has_coordinates()
                and callable(refresh)
            ):
                try:
                    maybe = refresh()
                    if hasattr(maybe, "__await__"):
                        snap = await maybe
                    else:
                        snap = maybe
                except Exception as exc:
                    refresh_failed = str(exc) or type(exc).__name__
            place = snap.place() if snap is not None else ""
            if snap is not None and snap.has_coordinates():
                lat = float(snap.latitude)
                lon = float(snap.longitude)
            elif place:
                try:
                    coords = await geocode_place(place)
                except Exception as exc:
                    return ToolResult(
                        ok=False,
                        output=f"[fail:weather] weather failed: {exc}",
                    )
                if coords is not None:
                    lat, lon = coords
        if lat is None or lon is None:
            cause = (
                f" The location refresh failed first: {refresh_failed}."
                if refresh_failed
                else ""
            )
            return ToolResult(
                ok=False,
                output=(
                    "[fail:weather] No coordinates on file, so there is no "
                    f"location to forecast.{cause} Set city plus latitude and "
                    "longitude in data/profile.yaml, or call user_location after "
                    "enabling location.network. Do not pass coordinates to "
                    "weather; it does not accept them."
                ),
            )

        raw_days = kwargs.get("days")
        try:
            days = int(raw_days) if raw_days not in (None, "") else 3
        except (TypeError, ValueError):
            # The 9B often passes days="today" instead of 1.
            days = 3
        days = max(1, min(7, days))
        try:
            data = await fetch_forecast(lat, lon, days=days)
        except Exception as exc:
            return ToolResult(ok=False, output=f"weather failed: {exc}")

        lines: list[str] = []
        if place:
            lines.append(f"Place: {place}")
        lines.append(f"Coordinates: {lat:.4f}, {lon:.4f}")
        current = data.get("current") or {}
        if current:
            code = describe_weather_code(current.get("weather_code"))
            lines.append(
                "Now: "
                f"{current.get('temperature_2m')}°F "
                f"(feels {current.get('apparent_temperature')}°F), "
                f"{code or 'conditions unknown'}, "
                f"precip {current.get('precipitation')}."
            )
        daily = data.get("daily") or []
        if daily:
            lines.append("Daily:")
            for row in daily:
                code = describe_weather_code(row.get("weather_code"))
                lines.append(
                    f"- {row.get('date')}: high {row.get('temperature_2m_max')}°F / "
                    f"low {row.get('temperature_2m_min')}°F, "
                    f"{code or 'conditions unknown'}, "
                    f"precip chance {row.get('precipitation_probability_max')}%."
                )
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"latitude": lat, "longitude": lon, "daily": daily, "current": current},
        )


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
    r"today|tomorrow|weekend|week|"
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
    r"weather|forecast|temperature|temps?|rain(?:y|ing)?|snow(?:y|ing)?|"
    r"humid(?:ity)?|umbrella|conditions?|report|"
    r"today|tonight|tomorrow|weekend|"
    r"outside|outdoors|"
    r"e-?mail|mail|inbox|send|summary|digest|briefing|every|day|"
    r"call|use|run|try|invoke|tool|days|"
    r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)"
    r")\b"
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
    return bool(_BEYOND_TODAY.search(text or ""))


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
    raw = " ".join((text or "").split())
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
        key = weather_place_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= _MAX_WEATHER_PLACES:
            break
    if re.search(
        r"(?i)\b(?:here|home|outside|outdoors|near\s+me)\b", raw
    ):
        want_home = True
    if want_home and "" not in seen and len(out) < _MAX_WEATHER_PLACES:
        out.insert(0, "")
    return out


def weather_places_wanted(text: str) -> list[str]:
    """Places this turn must fetch. A lone empty string is the user's home."""
    places = extract_weather_places(text)
    return places if places else [""]


def weather_places_missing(text: str, ok_keys: set[str]) -> list[str]:
    """Named (or home) places not yet covered by a successful weather call."""
    return [
        place
        for place in weather_places_wanted(text)
        if weather_place_key(place) not in ok_keys
    ]


def extract_weather_place(text: str) -> str:
    """First extra city named in the ask, or empty for the user's own location."""
    places = [p for p in extract_weather_places(text) if p]
    return places[0] if places else ""


def draft_weather_args(text: str) -> dict[str, Any]:
    """Args for an injected weather call. days always covers tomorrow."""
    out: dict[str, Any] = {"days": 3}
    place = extract_weather_place(text)
    if place:
        out["place"] = place
    return out


def fill_weather_args(args: dict[str, Any] | None, text: str) -> dict[str, Any]:
    """Keep place/days; drop model-invented coordinates; bump thin tomorrow."""
    drafted = draft_weather_args(text)
    out = dict(args or {})
    for key in _COORD_KEYS:
        out.pop(key, None)
    if drafted.get("place") and not str(out.get("place") or "").strip():
        out["place"] = drafted["place"]
    try:
        days = int(out.get("days") or 0)
    except (TypeError, ValueError):
        days = 0
    if days < 2 and weather_wants_beyond_today(text):
        out["days"] = 3
    elif days < 1:
        out["days"] = int(drafted.get("days") or 3)
    return out

