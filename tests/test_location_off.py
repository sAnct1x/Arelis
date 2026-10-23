"""Location off must not share country, time zone, or any other place."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from arelis.core.agent_loop import now_line
from arelis.location import build_location
from arelis.tools.user_location import UserLocationTool


def test_location_off_shares_no_country_or_timezone(tmp_path: Path) -> None:
    """location.enabled false shares no place, and the clock names no zone.

    The tool leak was SystemProvider still filling country and time zone
    after location was turned off. The clock leak was now_line putting
    strftime %Z in the system prompt with no location gate.
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

    clock = now_line(
        {
            "location": {
                "enabled": False,
                "profile_path": str(profile),
                "network": {"enabled": False},
            }
        }
    )
    clock_low = clock.lower()
    here = datetime.now().astimezone()
    zone = here.strftime("%Z")
    offset = here.strftime("%z")
    assert "(" not in clock
    assert ")" not in clock
    if zone:
        assert zone.lower() not in clock_low
    if offset:
        assert offset not in clock
        assert offset.replace("+", "") not in clock
    assert "local time" not in clock_low
    assert "utc" not in clock_low
    assert "gmt" not in clock_low
    assert "edt" not in clock_low
    assert "est" not in clock_low
