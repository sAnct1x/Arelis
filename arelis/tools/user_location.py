from __future__ import annotations

from typing import Any

from arelis.location import LocationResolver
from arelis.tools.base import ToolResult


class UserLocationTool:
    """Where the user is, with coordinates precise enough for an API call.

    A short summary is already injected into every turn, so this tool is not how
    the model learns the city; it is how it gets the parts that are too long to
    inject on every turn -- coordinates, postal code, and which source each
    field came from -- and how the user forces a refresh after travelling.
    """

    name = "user_location"
    description = (
        "The user's home location: city, region, postal code, latitude and "
        "longitude, and timezone. Call this when you need coordinates for an "
        "API, or when the user asks where you think they are."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "refresh": {
                "type": "boolean",
                "description": (
                    "Look the location up again instead of using the cached "
                    "answer. Only does anything when network lookup is enabled."
                ),
            }
        },
    }

    def __init__(self, resolver: LocationResolver) -> None:
        self.resolver = resolver

    async def run(self, **kwargs: Any) -> ToolResult:
        if kwargs.get("refresh"):
            location = await self.resolver.refresh(force=True)
        else:
            location = self.resolver.snapshot()
        # ok even when nothing is known. The output says how to fix that, which
        # is something the user can act on, whereas a failure would invite the
        # model to retry a call that will keep returning the same emptiness.
        return ToolResult(
            ok=True,
            output=location.describe(),
            data={**location.as_dict(), "known": location.known()},
        )
