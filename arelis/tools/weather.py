"""Local weather via Open-Meteo — no model-invented URLs, no JS weather sites."""

from __future__ import annotations

from typing import Any

from arelis.briefing.weather import (
    describe_weather_code,
    fetch_forecast,
    geocode_place,
)
from arelis.tools.base import ToolResult


class WeatherTool:
    """Forecast for the user's own place. Confirm not required.

    Only the user's place. Coordinates cannot be passed in, and that is on
    purpose: small models invent the lat/lon of whichever large city they have
    seen most often for "weather outside", which returns a confident forecast
    for somewhere the user is not.
    ``test_weather_ignores_model_invented_coords`` pins that.

    ``run`` used to read latitude/longitude from kwargs as a fallback, which four
    different places then described four different ways — the schema declared
    neither, the description forbade both, the skill card said to pass them for a
    named place, and the failure message asked for them. None of it worked: the
    profile always won, so a named place silently returned home weather, and once
    the cross-tool-args gate declared its keys an undeclared latitude would have
    been rejected outright. Naming a place is a real gap, but it wants a ``place``
    argument the tool geocodes itself, not coordinates a 7B guessed.
    """

    name = "weather"
    description = (
        "Get current conditions and the next few days of forecast from Open-Meteo "
        "for the user's own location, which the tool reads from their profile. "
        "Takes no location argument: call it with no arguments, or days only. "
        "It cannot report another city. Do not scrape AccuWeather, weather.com, "
        "or invent Open-Meteo query strings."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "How many daily rows to include (1-7). Default 3.",
            },
        },
        "required": [],
    }

    def __init__(self, location: Any | None = None) -> None:
        self.location = location

    async def run(self, **kwargs: Any) -> ToolResult:
        # The profile is the only source of coordinates. Anything the caller
        # passed is ignored rather than trusted.
        snap = None
        if self.location is not None and hasattr(self.location, "snapshot"):
            snap = self.location.snapshot()
        refresh = getattr(self.location, "refresh", None)
        # Kept so the failure below can name its real cause. "No coordinates on
        # file" sends the user to edit a profile that was never the problem.
        refresh_failed = ""
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
        lat: float | None = None
        lon: float | None = None
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

        days = int(kwargs.get("days") or 3)
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
