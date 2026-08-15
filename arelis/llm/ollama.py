from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

log = logging.getLogger(__name__)

# Yield kinds from stream_chat
# ("thinking", str) | ("token", str) | ("tool_calls", list[dict])
# | ("metrics", dict)  # final chunk only; prompt_eval_count lives here


def same_ollama_model(name: str, *candidates: str) -> bool:
    """True if `name` is the same Ollama tag as any candidate (or a variant).

    Config often says `qwen2.5:7b` while `/api/ps` lists `qwen2.5:7b:latest`
    or `qwen2.5:7b-instruct`. Must not treat `qwen2.5:7b` as `qwen2.5:14b`.
    """
    raw = (name or "").strip()
    if not raw:
        return False
    for item in candidates:
        other = (item or "").strip()
        if not other:
            continue
        if raw == other:
            return True
        if raw.startswith(f"{other}:") or other.startswith(f"{raw}:"):
            return True
        if raw.startswith(f"{other}-") or other.startswith(f"{raw}-"):
            return True
    return False


def _new_slot() -> dict[str, Any]:
    return {"type": "function", "function": {"name": "", "arguments": {}}}


def _merge_tool_calls(dst: list[dict[str, Any]], incoming: list[Any]) -> None:
    """Accumulate streamed partial tool_calls into dst.

    Two wire formats have to coexist. Ollama normally sends each tool call
    complete in a single chunk with no index. OpenAI-compatible endpoints send
    deltas: one chunk carrying the name, then further chunks carrying slices of
    the argument JSON, all tagged with an index.

    When index is absent the two are told apart by whether the chunk names a
    tool. A named chunk starts a new call; an unnamed chunk is an argument
    continuation and belongs to the call already in progress. Appending on every
    unnamed chunk instead, which is what a naive len(dst) fallback does, splits
    one call into several partial ones and can turn a single confirmed write
    into repeated writes.
    """
    for item in incoming:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        idx = item.get("index")
        if idx is None:
            if fn.get("name") or not dst:
                dst.append(_new_slot())
            idx = len(dst) - 1
        while len(dst) <= idx:
            dst.append(_new_slot())

        slot = dst[idx]
        slot_fn = slot.setdefault("function", {"name": "", "arguments": {}})
        if fn.get("name"):
            slot_fn["name"] = fn["name"]
        if "arguments" in fn:
            args = fn["arguments"]
            if isinstance(args, str):
                # Streamed JSON string: concatenate now, parse once at the end.
                # Parsing per chunk would fail on every incomplete fragment.
                slot_fn["_args_raw"] = slot_fn.get("_args_raw", "") + args
            elif isinstance(args, dict):
                slot_fn["arguments"] = args
        if item.get("type"):
            slot["type"] = item["type"]


def _finalize_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse accumulated argument text and drop slots that never got a name."""
    out: list[dict[str, Any]] = []
    for call in calls:
        fn = dict(call.get("function") or {})
        raw = fn.pop("_args_raw", None)
        if raw is not None and not fn.get("arguments"):
            try:
                fn["arguments"] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError:
                # Preserve the text so the tool layer can report a precise
                # argument error instead of silently running with no arguments.
                fn["arguments"] = {"_raw": raw}
        elif isinstance(fn.get("arguments"), str):
            try:
                fn["arguments"] = json.loads(fn["arguments"])
            except json.JSONDecodeError:
                pass
        if not fn.get("name"):
            continue
        if not isinstance(fn.get("arguments"), dict):
            fn["arguments"] = {}
        out.append({"type": call.get("type") or "function", "function": fn})
    return out


class OllamaProvider:
    """HTTP client for a local Ollama server."""

    # Real host: after /api/ps is empty, settle and refuse 14B if the card
    # is still full (Comfy, Chrome, a stuck runner). Fake providers omit this
    # so unit tests do not shell out to Get-Counter.
    guard_host_vram = True

    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout_s: float = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s)

    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield (kind, payload): thinking/token strings, then tool_calls if any.

        Tool calls are emitted once at the end rather than as they arrive,
        because a call is only actionable after its arguments are complete.
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if options:
            payload["options"] = options
        if tools:
            payload["tools"] = tools

        accumulated_calls: list[dict[str, Any]] = []
        done_metrics: dict[str, Any] | None = None
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code >= 400:
                # A streaming response has no body until it is read, and the
                # body is where Ollama explains itself ("model not found").
                # Without this, a missing model surfaces as a bare 404 and the
                # agent loop wrongly retries in JSON fallback mode.
                await response.aread()
                detail = response.text.strip()[:400]
                raise RuntimeError(
                    f"Ollama returned HTTP {response.status_code} for model `{model}`"
                    + (f": {detail}" if detail else "")
                )
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # Keep-alive noise or a partial frame. Skipping is right:
                    # raising here would be misread upstream as "native tool
                    # calling is broken" and trigger a pointless fallback.
                    continue
                if data.get("error"):
                    raise RuntimeError(f"Ollama error: {data['error']}")
                msg = data.get("message") or {}
                thinking = msg.get("thinking") or ""
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []
                if thinking:
                    yield ("thinking", thinking)
                if content:
                    yield ("token", content)
                if tool_calls:
                    _merge_tool_calls(accumulated_calls, tool_calls)
                if data.get("done"):
                    # prompt_eval_count is how many tokens the prompt actually
                    # used. The context fitter calibrates chars-per-token from
                    # it; without this yield the number is discarded here.
                    metrics = {
                        key: data[key]
                        for key in (
                            "prompt_eval_count",
                            "eval_count",
                            "prompt_eval_duration",
                            "eval_duration",
                        )
                        if key in data
                    }
                    if metrics:
                        done_metrics = metrics
                    break

        if done_metrics is not None:
            yield ("metrics", done_metrics)
        finalized = _finalize_tool_calls(accumulated_calls)
        if finalized:
            yield ("tool_calls", finalized)

    async def chat_with_images(
        self,
        model: str,
        prompt: str,
        images_b64: list[str],
        *,
        keep_alive: str | int = 0,
        options: dict[str, Any] | None = None,
    ) -> str:
        """One-shot multimodal chat (VL). Returns assistant text; no tools.

        Images are raw base64 (no data: URL prefix). keep_alive defaults to 0 so
        the VL model does not sit on a 12GB card next to chat.
        """
        if not images_b64:
            raise ValueError("chat_with_images needs at least one image")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt or "Describe this image.",
                    "images": list(images_b64),
                }
            ],
            "stream": False,
            "keep_alive": keep_alive,
        }
        if options:
            payload["options"] = options
        response = await self._client.post("/api/chat", json=payload)
        if response.status_code >= 400:
            detail = response.text.strip()[:400]
            raise RuntimeError(
                f"Ollama returned HTTP {response.status_code} for model `{model}`"
                + (f": {detail}" if detail else "")
            )
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"Ollama error: {data['error']}")
        msg = data.get("message") or {}
        return str(msg.get("content") or "").strip()

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed texts with /api/embed. Used for recall, not for chat turns.

        keep_alive is 0 so nomic does not sit on the card after a batch or a
        single recall query. A mid-turn recall still costs a reload of the chat
        model afterward; that is the price of an explicit memory search, and the
        background indexer never runs while a turn is in flight.
        """
        if not texts:
            return []
        response = await self._client.post(
            "/api/embed",
            json={"model": model, "input": texts, "keep_alive": 0},
        )
        if response.status_code >= 400:
            detail = response.text.strip()[:400]
            raise RuntimeError(
                f"Ollama embed returned HTTP {response.status_code} for model `{model}`"
                + (f": {detail}" if detail else "")
            )
        data = response.json()
        vectors = data.get("embeddings")
        if not isinstance(vectors, list):
            raise RuntimeError(f"Ollama embed response missing embeddings for `{model}`")
        out: list[list[float]] = []
        for item in vectors:
            if not isinstance(item, list):
                raise RuntimeError(f"Ollama embed returned a malformed vector for `{model}`")
            out.append([float(x) for x in item])
        if len(out) != len(texts):
            raise RuntimeError(
                f"Ollama embed returned {len(out)} vectors for {len(texts)} inputs"
            )
        return out

    async def list_models(self) -> list[str]:
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        models = response.json().get("models") or []
        return [m.get("name", "") for m in models if m.get("name")]

    async def running_models(self) -> list[str]:
        """Names currently resident according to `/api/ps`."""
        response = await self._client.get("/api/ps")
        response.raise_for_status()
        models = response.json().get("models") or []
        names: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("model") or ""
            if name:
                names.append(str(name))
        return names

    async def wait_until_unloaded(
        self,
        models: list[str],
        *,
        timeout_s: float = 15.0,
    ) -> list[str]:
        """Poll `/api/ps` until none of `models` remain. Returns leftovers."""
        wanted = {str(name).strip() for name in models if str(name).strip()}
        if not wanted:
            return []
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        still: list[str] = []
        while True:
            running = await self.running_models()
            still = [
                name for name in running if same_ollama_model(name, *wanted)
            ]
            if not still:
                return []
            if time.monotonic() >= deadline:
                return still
            await asyncio.sleep(0.4)

    async def unload(self, model: str) -> None:
        """Ask Ollama to drop a model from VRAM immediately.

        keep_alive=0 with an empty prompt is the documented way to evict without
        generating. This is what lets one 7B model be hot at a time on a 12GB
        card when roles switch. Callers that need the card empty before a 14B
        load should poll `wait_until_unloaded` afterward — Ollama's 200 is not
        the same as VRAM actually freed.
        """
        await self.pin(model, keep_alive=0)
        # Some Ollama builds evict the chat runner only via /api/chat.
        try:
            await self._client.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": [],
                    "keep_alive": 0,
                    "stream": False,
                },
            )
        except Exception:
            log.debug("chat keep_alive=0 after unload of %s failed", model, exc_info=True)

    async def pin(self, model: str, *, keep_alive: str | int = "30m") -> None:
        """Load (or refresh) a model in VRAM without generating tokens.

        Used at UI/CLI start and after a research/code detour so the next
        conversation turn does not pay a cold TTFT. keep_alive=0 unloads.
        """
        response = await self._client.post(
            "/api/generate",
            json={
                "model": model,
                "prompt": "",
                "keep_alive": keep_alive,
                "stream": False,
            },
        )
        if response.status_code >= 400:
            detail = response.text.strip()[:400]
            raise RuntimeError(
                f"Ollama returned HTTP {response.status_code} pinning `{model}`"
                + (f": {detail}" if detail else "")
            )

    async def close(self) -> None:
        await self._client.aclose()
