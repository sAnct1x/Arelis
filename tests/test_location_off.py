"""Location off must not share country, time zone, or any other place."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arelis.location import build_location
from arelis.tools.user_location import UserLocationTool


def test_location_off_shares_no_country_or_timezone(tmp_path: Path) -> None:
    """location.enabled false stops the tool from sharing the computer place.

    The leak was SystemProvider still filling country and time zone after
    location was turned off. The tool must say location is off and leave
    those fields empty, including a saved profile city.
    """
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "location:\n"
        "  city: Springfield\n"
        "  region: Illinois\n"
        "  country: US\n"
        "  timezone: America/Chicago\n",
        encoding="utf-8",
    )
    resolver = build_location(
        {
            "location": {
                "enabled": False,
                "profile_path": str(profile),
                "network": {"enabled": False},
            }
        }
    )
    result = asyncio.run(UserLocationTool(resolver).run())
    assert result.ok
    low = result.output.lower()
    assert "location is off" in low
    assert "springfield" not in low
    assert "chicago" not in low
    assert "country:" not in low
    assert "timezone:" not in low
    assert "utc_offset:" not in low
    assert not result.data.get("country")
    assert not result.data.get("timezone")
    assert not result.data.get("utc_offset")
    assert not result.data.get("city")
