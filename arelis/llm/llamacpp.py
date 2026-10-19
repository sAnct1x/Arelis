"""HTTP client for a llama-server that is already running.

Arelis does not start llama-server. Point ``llamacpp.base_url`` at one you
launched yourself, with ``-c`` equal to the per-model cap in config. The 35B
card is full, so this provider does not do pictures or embeddings.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arelis.llm.ollama import _finalize_tool_calls, _merge_tool_calls

log = logging.getLogger(__name__)

_SAMPLING = {
    "temperature": "temperature",
    "top_p": "top_p",
    "top_k": "top_k",
    "min_p": "min_p",
    "presence_penalty": "presence_penalty",
    "frequency_penalty": "frequency_penalty",
    "repeat_penalty": "repeat_penalty",
    "seed": "seed",
    "stop": "stop",
}


def _positive_int(raw: Any) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _n_ctx_from_slots(slots: list[Any]) -> int | None:
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        found = _positive_int(slot.get("n_ctx"))
        if found:
            return found
    return None


def parse_server_n_ctx(payload: Any) -> int | None:
    """Read ``n_ctx`` from a llama-server ``/props`` or ``/slots`` body."""
    if isinstance(payload, dict):
        direct = _positive_int(payload.get("n_ctx"))
        if direct:
            return direct
        gen = payload.get("default_generation_settings")
        if isinstance(gen, dict):
            nested = _positive_int(gen.get("n_ctx"))
            if nested:
                return nested
        slots = payload.get("slots")
        if isinstance(slots, list):
            return _n_ctx_from_slots(slots)
        return None
    if isinstance(payload, list):
        return _n_ctx_from_slots(payload)
    return None


def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ollama rows to the OpenAI chat shape llama-server expects.

    Tool results in Arelis use ``tool_name``. The server reads ``name``.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        row: dict[str, Any] = {"role": msg.get("role") or "user", "content": content}
        if row["role"] == "tool":
            name = msg.get("name") or msg.get("tool_name")
            if name:
                row["name"] = str(name)
            if msg.get("tool_call_id"):
                row["tool_call_id"] = msg["tool_call_id"]
        if msg.get("tool_calls"):
            row["tool_calls"] = msg["tool_calls"]
        out.append(row)
    return out


def _sampling(options: dict[str, Any] | None) -> dict[str, Any]:
    """Forward sampling knobs llama-server understands. Drop ``num_ctx``."""
    if not options:
        return {}
    out: dict[str, Any] = {}
    for src, dst in _SAMPLING.items():
        if src in options and options[src] is not None:
            out[dst] = options[src]
    if options.get("num_predict") is not None:
        predict = _positive_int(options.get("num_predict"))
        # num_predict 0 is a real "no tokens" ask. _positive_int drops it.
        if predict is not None:
            out["max_tokens"] = predict
        else:
            try:
                if int(options["num_predict"]) == 0:
                    out["max_tokens"] = 0
            except (TypeError, ValueError):
                pass
    return out


class LlamaCppProvider:
    """OpenAI-compatible chat against one llama-server process."""

    # The server owns the card. Do not probe the host or try to unload it.
    guard_host_vram = False

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout_s: float = 300,
        *,
        context_caps: dict[str, int] | None = None,
        default_cap: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._context_caps = {
            str(key): int(value)
            for key, value in (context_caps or {}).items()
            if value
        }
        self._default_cap = int(default_cap) if default_cap else None
        self._n_ctx: int | None = None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout_s
        )

    def cap_for(self, model: str) -> int | None:
        """Context cap that fits the card for this model name."""
        name = (model or "").strip()
        if name and name in self._context_caps:
            return self._context_caps[name]
        base = name.split(":", 1)[0]
        if base and base in self._context_caps:
            return self._context_caps[base]
        return self._default_cap

    async def context_tokens(self, model: str) -> int:
        """Tokens the history budget may use: min(server n_ctx, model cap)."""
        server = await self._server_n_ctx()
        cap = self.cap_for(model)
        if server and cap:
            return min(server, cap)
        if server:
            return server
        if cap:
            return cap
        return 0

    async def _server_n_ctx(self) -> int | None:
        if self._n_ctx:
            return self._n_ctx
        for path in ("/props", "/slots"):
            found = await self._read_n_ctx(path)
            if found:
                self._n_ctx = found
                return found
        return None

    async def _read_n_ctx(self, path: str) -> int | None:
        try:
            response = await self._client.get(path)
        except Exception as exc:
            log.info("llama-server %s failed: %s", path, exc)
            return None
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except Exception:
            return None
        return parse_server_n_ctx(payload)

    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        keep_alive: str | int | None = None,
        options: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        think: bool | None = None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """Yield thinking, token, metrics, and tool_calls. Same kinds as Ollama.

        ``keep_alive`` is ignored. llama-server keeps the model until it exits.
        """
        del keep_alive
        payload: dict[str, Any] = {
            "model": model,
            "messages": _wire_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        payload.update(_sampling(options))
        if tools:
            payload["tools"] = tools
        if think is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": bool(think)}

        accumulated: list[dict[str, Any]] = []
        done_metrics: dict[str, Any] | None = None
        async with self._client.stream(
            "POST", "/v1/chat/completions", json=payload
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                detail = response.text.strip()[:400]
                raise RuntimeError(
                    f"llama-server returned HTTP {response.status_code} for model `{model}`"
                    + (f": {detail}" if detail else "")
                )
            async for line in response.aiter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                else:
                    line = line.strip()
                if not line or line == "[DONE]":
                    if line == "[DONE]":
                        break
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                if data.get("error"):
                    err = data["error"]
                    message = err.get("message") if isinstance(err, dict) else err
                    raise RuntimeError(f"llama-server error: {message}")
                usage = data.get("usage") or {}
                if isinstance(usage, dict) and usage.get("prompt_tokens") is not None:
                    done_metrics = {
                        "prompt_eval_count": usage.get("prompt_tokens"),
                        "eval_count": usage.get("completion_tokens"),
                    }
                choices = data.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                delta = choices[0].get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                thinking = delta.get("reasoning_content") or delta.get("reasoning") or ""
                content = delta.get("content") or ""
                tool_calls = delta.get("tool_calls") or []
                if thinking:
                    yield ("thinking", thinking)
                if content:
                    yield ("token", content)
                if tool_calls:
                    _merge_tool_calls(accumulated, tool_calls)

        if done_metrics is not None:
            yield ("metrics", done_metrics)
        finalized = _finalize_tool_calls(accumulated)
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
        on_thinking: Any | None = None,
        think: bool | None = None,
    ) -> str:
        """Pictures are off. The 35B server has no mmproj."""
        del model, prompt, images_b64, keep_alive, options, on_thinking, think
        raise RuntimeError(
            "Pictures are off for the llama.cpp provider. "
            "This server has no vision model."
        )

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embeddings are off. Recall falls back to keywords."""
        del model, texts
        raise RuntimeError(
            "Embeddings are off for the llama.cpp provider. "
            "This server does not load an embed model."
        )

    async def capabilities(self, model: str) -> frozenset[str]:
        if not (model or "").strip():
            return frozenset()
        return frozenset({"completion", "tools", "thinking"})

    async def sees_images(self, model: str) -> bool:
        del model
        return False

    async def list_models(self) -> list[str]:
        response = await self._client.get("/v1/models")
        response.raise_for_status()
        data = response.json().get("data") or []
        if not isinstance(data, list):
            return []
        names: list[str] = []
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"]))
        return names

    async def running_ps(self) -> list[dict[str, Any]]:
        """Empty. The process is one model, and Arelis does not evict it."""
        return []

    async def running_models(self) -> list[str]:
        return []

    async def wait_until_unloaded(
        self,
        models: list[str],
        *,
        timeout_s: float = 15.0,
    ) -> list[str]:
        del models, timeout_s
        return []

    async def unload(self, model: str) -> None:
        """No-op. Stopping llama-server is the operator's job."""
        del model

    async def pin(
        self,
        model: str,
        *,
        keep_alive: str | int = "30m",
        options: dict[str, Any] | None = None,
    ) -> None:
        """Confirm the server is up. The model is already loaded."""
        del model, keep_alive, options
        response = await self._client.get("/health")
        if response.status_code >= 400:
            detail = response.text.strip()[:400]
            raise RuntimeError(
                f"llama-server health check returned HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
            )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
