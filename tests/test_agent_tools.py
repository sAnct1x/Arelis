from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.json_tools import extract_native_tool_calls, parse_fallback_payload
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.safety import is_blocked_url, redact_secrets
from arelis.tools.web import WebFetchTool


def test_ollama_tools_schema_shape() -> None:
    reg = ToolRegistry()
    reg.register(CodeWorkspaceTool(["."]))
    reg.register(WebFetchTool("test-agent", block_private_urls=True))
    tools = reg.ollama_tools()
    assert len(tools) == 2
    for t in tools:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "parameters" in t["function"]
        assert t["function"]["parameters"]["type"] == "object"


def test_needs_confirm_gate() -> None:
    reg = ToolRegistry()
    reg.register(CodeWorkspaceTool(["."]))

    class Img:
        name = "image"
        description = "img"
        risk = "side_effect"
        parameters_schema = {"type": "object", "properties": {}}

        async def run(self, **kwargs: Any) -> ToolResult:
            return ToolResult(ok=True, output="ok")

    reg.register(Img())
    assert not reg.needs_confirm("workspace", {"action": "read", "path": "README.md"})
    assert not reg.needs_confirm("workspace", {"action": "list"})
    assert reg.needs_confirm("workspace", {"action": "write", "path": "x", "content": "y"})
    assert reg.needs_confirm("workspace", {"action": "edit", "path": "x", "old": "a", "new": "b"})
    assert reg.needs_confirm("workspace", {"action": "keep", "text": "spare key"})
    assert reg.needs_confirm("image", {"prompt": "nebula"})
    assert not reg.needs_confirm(
        "workspace", {"action": "write", "path": "x", "content": "y"}, confirm_writes=False
    )


def test_json_fallback_parser() -> None:
    tool = parse_fallback_payload('{"tool":"workspace","args":{"action":"read","path":"README.md"}}')
    assert tool == {
        "kind": "tool",
        "name": "workspace",
        "args": {"action": "read", "path": "README.md"},
    }
    openai_style = parse_fallback_payload(
        '{\n  "name": "workspace",\n  "arguments": {\n    "action": "write",\n    "path": "data/x.txt",\n    "content": "hi"\n  }\n}'
    )
    assert openai_style == {
        "kind": "tool",
        "name": "workspace",
        "args": {"action": "write", "path": "data/x.txt", "content": "hi"},
    }
    final = parse_fallback_payload('Here you go:\n```json\n{"final":"hello"}\n```')
    assert final == {"kind": "final", "text": "hello"}
    assert parse_fallback_payload("just chatting") is None


def test_extract_native_tool_calls() -> None:
    calls = extract_native_tool_calls(
        [
            {
                "type": "function",
                "function": {
                    "name": "scrape",
                    "arguments": {"url": "https://example.com"},
                },
            }
        ]
    )
    assert calls == [("scrape", {"url": "https://example.com"})]


def test_private_url_block() -> None:
    assert is_blocked_url("http://127.0.0.1/secret")
    assert is_blocked_url("http://localhost/x")
    assert is_blocked_url("file:///C:/Windows/win.ini")
    assert is_blocked_url("http://169.254.169.254/latest")
    assert is_blocked_url("https://example.com") is None


def test_redact_secrets() -> None:
    text = "api_key=sk-abcdefghijklmnop1234 and password=hunter2"
    out = redact_secrets(text)
    assert "sk-abcdefghijklmnop1234" not in out or "[redacted]" in out
    assert "password=hunter2" not in out


class _MockProvider:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0

    async def stream_chat(self, model, messages, **kwargs):
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item

    async def list_models(self):
        return []

    async def unload(self, model):
        return None

    async def close(self):
        return None


class _MockRouter:
    def __init__(self, provider: _MockProvider) -> None:
        self.provider = provider
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        async for item in self.provider.stream_chat("mock", messages, **kwargs):
            yield item


@pytest.mark.asyncio
async def test_agent_loop_tool_then_final(tmp_path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Hello Arelis\n", encoding="utf-8")

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)

    provider = _MockProvider(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "workspace",
                                "arguments": {"action": "read", "path": str(readme)},
                            },
                        }
                    ],
                )
            ],
            [("token", "README says Hello Arelis.")],
        ]
    )
    router = _MockRouter(provider)
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool([str(tmp_path)]))
    memory = SessionMemory()
    config = {
        "agent": {
            "max_rounds": 8,
            "tool_output_chars": 14000,
            "confirm_writes": True,
            "confirm_image": True,
            "json_fallback": True,
        },
        "ollama": {"base_url": "http://127.0.0.1:11434"},
        "voice": {"enabled": False},
    }

    async def confirm(cid, tool, args, summary):
        return "allow"

    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        memory,
        "You are Arelis.",
        config,
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    await loop.run("open README and summarize", "fast")
    await bus.drain()
    bus.stop()
    bus_task.cancel()

    types = [e.type for e in events]
    assert EventType.TOOL_START in types
    assert EventType.TOOL_RESULT in types
    assert EventType.ASSISTANT_DONE in types
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "Hello Arelis" in (done.payload.get("text") or "")
