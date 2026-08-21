from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


class LLMProvider(Protocol):
    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        ...

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        ...

    async def list_models(self) -> list[str]:
        ...

    async def unload(self, model: str) -> None:
        ...

    async def pin(
        self,
        model: str,
        *,
        keep_alive: str | int = "30m",
        options: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def close(self) -> None:
        ...
