"""Windows location when the machine offers it and the user allowed it.

Off Windows this is nothing. The forecast tool takes a stand-in for tests,
so this function is not on the test path.
"""

from __future__ import annotations

import sys
from typing import Any


async def read_windows_location() -> Any | None:
    """City and coordinates from Windows, or None if that is not available."""
    if sys.platform != "win32":
        return None
    try:
        return await _read_winrt()
    except Exception:  # no permission or no winsdk means there is no place
        return None


async def _read_winrt() -> Any | None:
    from winsdk.windows.devices.geolocation import (  # type: ignore[import-not-found]
        GeolocationAccessStatus,
        Geolocator,
    )

    access = await Geolocator.request_access_async()
    if access != GeolocationAccessStatus.ALLOWED:
        return None
    locator = Geolocator()
    position = await locator.get_geoposition_async()
    coord = position.coordinate
    point = coord.point
    city = ""
    region = ""
    civic = getattr(coord, "civic_address", None)
    if civic is not None:
        city = str(getattr(civic, "city", "") or "").strip()
        region = str(getattr(civic, "state", "") or "").strip()
    lat = float(point.position.latitude)
    lon = float(point.position.longitude)
    from arelis.location import UserLocation

    return UserLocation(city=city, region=region, latitude=lat, longitude=lon)
