"""The startup line about a missing model is plain speech."""

from __future__ import annotations

import asyncio

from arelis.core.events import Event
from arelis.llm.startup import run_model_preflight


class _Bus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


class _Models:
    async def list_models(self) -> list[str]:
        return ["llama3.2:3b"]


def test_missing_model_status_does_not_name_the_role() -> None:
    bus = _Bus()
    asyncio.run(
        run_model_preflight(
            bus,  # type: ignore[arg-type]
            _Models(),  # type: ignore[arg-type]
            {"chat": "qwen3.5:9b"},
        )
    )
    messages = [
        str(event.payload.get("message") or "")
        for event in bus.events
        if "qwen3.5:9b" in str(event.payload.get("message") or "")
    ]
    assert messages
    text = messages[0]
    assert "isn't downloaded yet" in text
    assert "qwen3.5:9b" in text
    assert "role" not in text.lower()
    assert "`" not in text
    assert "ollama pull" not in text.lower()
