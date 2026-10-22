"""HTTP client for one llama-server.

``pin`` starts the 35B server when the chat port is down. The launch line is
``launch_args_for``: Q8 mmproj, flash attention off, 1024 image tokens, f16
KV, and ``--n-cpu-moe 32``. A picture is sent when ``/props`` reports vision.
Embeddings come from a second CPU llama-server at ``llamacpp.embed_url``
(nomic-embed-text GGUF, ``/v1/embeddings``). ``embeds`` is True only while
that server answers; otherwise recall stays on keywords.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from arelis.llm.errors import is_context_overflow
from arelis.llm.llama_launch import ensure_server
from arelis.llm.wire import _finalize_tool_calls, _merge_tool_calls

log = logging.getLogger(__name__)

# Server down and no per-model cap.
_FALLBACK_CONTEXT_TOKENS = 8192
# /props, /slots, and the embed probe are tiny. Do not wait the 300s chat timeout.
_PROBE_TIMEOUT_S = 5.0
# Failed probe. Retry lazily on the next embed attempt; no background thread.
_EMBED_PROBE_RETRY_S = 60.0
# Chat shimmer while tool arguments stream. One yield per this many new
# characters, not one per token, so the line does not repaint on every slice.
_TOOL_ARG_PROGRESS_CHARS = 64

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


def _json_arguments(raw: Any) -> str:
    """OpenAI wants ``function.arguments`` as a JSON string, not an object."""
    if isinstance(raw, str):
        return raw
    if raw is None:
        raw = {}
    return json.dumps(raw, ensure_ascii=False, default=str)


def _call_id(call: dict[str, Any], ordinal: int) -> str:
    existing = call.get("id")
    if existing:
        return str(existing)
    return f"call_{ordinal}"


def _wire_tool_call(call: Any, ordinal: int) -> tuple[dict[str, Any], str] | None:
    if not isinstance(call, dict):
        return None
    fn = call.get("function")
    if not isinstance(fn, dict):
        fn = {}
    name = fn.get("name") or call.get("name") or ""
    if "arguments" in fn:
        args = fn.get("arguments")
    else:
        args = call.get("arguments")
    call_id = _call_id(call, ordinal)
    wired = {
        "id": call_id,
        "type": str(call.get("type") or "function"),
        "function": {
            "name": str(name),
            "arguments": _json_arguments(args),
        },
    }
    return wired, call_id


def _last_real_user_index(messages: list[dict[str, Any]]) -> int | None:
    """Index of the last user line the Qwen template treats as the query.

    A ``<tool_response>`` wrapper is not that line. ``reasoning_content`` is
    rendered only on assistant rows after this index, which is the tool loop
    still in flight. Older assistant rows do not use the field.
    """
    for index in range(len(messages) - 1, -1, -1):
        msg = messages[index]
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            text = content.strip()
            if text.startswith("<tool_response>") and text.endswith("</tool_response>"):
                continue
        return index
    return None


def _wire_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chat rows to the OpenAI chat shape llama-server expects.

    Arelis stores tool-call arguments as a dict and often omits ``id``.
    Tool rows carry ``tool_name`` and no ``tool_call_id``. The server wants
    a JSON string, an id on each call, and the matching id on the result.
    Results pair with calls in order when the id is missing. A later
    non-tool message drops leftover ids so they cannot pair into a new round.
    """
    out: list[dict[str, Any]] = []
    pending_ids: list[str] = []
    ordinal = 0
    last_user = _last_real_user_index(messages)
    for index, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        content = _message_content(msg.get("content"))
        row: dict[str, Any] = {"role": msg.get("role") or "user", "content": content}
        # Only the tool loop after the last real user line. The template
        # ignores this field on earlier assistant rows, and resending it
        # would carry old thoughts into every later turn.
        if row["role"] == "assistant" and last_user is not None and index > last_user:
            reasoning = msg.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                row["reasoning_content"] = reasoning
        calls = msg.get("tool_calls")
        if row["role"] != "tool" and not (isinstance(calls, list) and calls):
            pending_ids = []
        if isinstance(calls, list) and calls:
            wired_calls: list[dict[str, Any]] = []
            for call in calls:
                ordinal += 1
                wired = _wire_tool_call(call, ordinal)
                if wired is None:
                    continue
                item, _call_id = wired
                wired_calls.append(item)
            if wired_calls:
                row["tool_calls"] = wired_calls
                pending_ids = [str(item["id"]) for item in wired_calls]
        if row["role"] == "tool":
            name = msg.get("name") or msg.get("tool_name")
            if name:
                row["name"] = str(name)
            existing = msg.get("tool_call_id")
            if existing:
                row["tool_call_id"] = str(existing)
                if pending_ids and pending_ids[0] == row["tool_call_id"]:
                    pending_ids.pop(0)
            elif pending_ids:
                row["tool_call_id"] = pending_ids.pop(0)
            else:
                ordinal += 1
                row["tool_call_id"] = f"call_{ordinal}"
        out.append(row)
    return out


def _message_content(raw: Any) -> str | list[Any]:
    """Keep a list of content parts. Image turns are a list, not a string."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        return raw
    if raw is None:
        return ""
    return str(raw)


def _image_part(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("data:"):
        url = text
    else:
        url = f"data:image/jpeg;base64,{text}"
    return {"type": "image_url", "image_url": {"url": url}}


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


def _arg_chars(fn: dict[str, Any]) -> int:
    """Characters of argument text accumulated on one tool call.

    Streamed slices live in ``_args_raw`` and are not parsed. A complete
    object that arrived in one chunk is measured with ``json.dumps``.
    """
    raw = fn.get("_args_raw")
    if isinstance(raw, str):
        return len(raw)
    args = fn.get("arguments")
    if isinstance(args, dict) and args:
        try:
            return len(json.dumps(args, separators=(",", ":")))
        except (TypeError, ValueError):
            return 0
    return 0


def _tool_arg_progress(calls: list[dict[str, Any]]) -> tuple[str, int] | None:
    """Tool name and argument characters so far. Does not parse the JSON."""
    name = ""
    chars = 0
    for call in calls:
        fn = call.get("function")
        if not isinstance(fn, dict):
            continue
        n = _arg_chars(fn)
        if n < chars:
            continue
        chars = n
        slot_name = fn.get("name")
        if slot_name:
            name = str(slot_name)
    if not name or chars <= 0:
        return None
    return name, chars


def _openai_vectors(payload: Any, count: int, model: str) -> list[list[float]]:
    """Read OpenAI ``/v1/embeddings`` ``data[].embedding``, ordered by index."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(
            f"llama.cpp embed response missing data for `{model}`"
        )
    by_index: dict[int, list[float]] = {}
    for offset, item in enumerate(rows):
        if not isinstance(item, dict):
            raise RuntimeError(
                f"llama.cpp embed returned a malformed row for `{model}`"
            )
        raw = item.get("embedding")
        if not isinstance(raw, list):
            raise RuntimeError(
                f"llama.cpp embed returned a malformed vector for `{model}`"
            )
        try:
            idx = int(item["index"]) if "index" in item else offset
        except (TypeError, ValueError):
            idx = offset
        by_index[idx] = [float(x) for x in raw]
    try:
        out = [by_index[i] for i in range(count)]
    except KeyError as exc:
        raise RuntimeError(
            f"llama.cpp embed returned {len(by_index)} vectors for {count} inputs"
        ) from exc
    return out


class LlamaCppProvider:
    """OpenAI-compatible chat against one llama-server process."""

    # The server owns the card. Do not probe the host or try to unload it.
    guard_host_vram = False
    # Instance sets this True only after the CPU embed server answers.
    embeds = False

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout_s: float = 300,
        *,
        context_caps: dict[str, int] | None = None,
        default_cap: int | None = None,
        client: httpx.AsyncClient | None = None,
        embed_url: str | None = None,
        embed_client: httpx.AsyncClient | None = None,
        launch_args: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._launch_args = list(launch_args) if launch_args else None
        raw_embed = (embed_url or "").strip().rstrip("/")
        self.embed_url = raw_embed or None
        self.embeds = False
        self._embed_ok: bool | None = None
        self._embed_probed_at: float | None = None
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
        self._owns_embed_client = False
        self._embed_client: httpx.AsyncClient | None = None
        if self.embed_url:
            self._owns_embed_client = embed_client is None
            self._embed_client = embed_client or httpx.AsyncClient(
                base_url=self.embed_url, timeout=timeout_s
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
        return _FALLBACK_CONTEXT_TOKENS

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
            response = await self._client.get(path, timeout=_PROBE_TIMEOUT_S)
        except httpx.HTTPError as exc:
            log.warning("llama-server %s failed: %s", path, exc)
            return None
        if response.status_code >= 400:
            return None
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            log.warning("llama-server %s returned a body that is not JSON", path)
            return None
        return parse_server_n_ctx(payload)

    async def _drop_cached_window_after_overflow(self, detail: object) -> None:
        """A restarted server can have a new ``-c``. The next budget must see it."""
        if not is_context_overflow(detail):
            return
        self._n_ctx = None
        await self._server_n_ctx()

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
        """Yield thinking, token, metrics, tool progress, and tool_calls.

        ``keep_alive`` is ignored. llama-server keeps the model until it exits.
        Argument deltas are merged as they arrive. A throttled
        ``tool_progress`` yield carries the tool name and how many argument
        characters have landed. That yield is not a call. ``tool_calls`` is
        still yielded once, after the stream ends, and only then are the
        arguments parsed. A finish reason of length yields ``cut_short``
        before ``tool_calls``.
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
        progress_at = 0
        stopped_on_length = False
        async with self._client.stream(
            "POST", "/v1/chat/completions", json=payload
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                detail = response.text.strip()[:400]
                await self._drop_cached_window_after_overflow(detail)
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
                    await self._drop_cached_window_after_overflow(message)
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
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    stopped_on_length = True
                delta = choice.get("delta") or {}
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
                    snap = _tool_arg_progress(accumulated)
                    if snap is not None:
                        tool_name, tool_chars = snap
                        if tool_chars - progress_at >= _TOOL_ARG_PROGRESS_CHARS:
                            progress_at = tool_chars
                            yield (
                                "tool_progress",
                                {"name": tool_name, "chars": tool_chars},
                            )

        if done_metrics is not None:
            yield ("metrics", done_metrics)
        if stopped_on_length:
            yield ("cut_short", "length")
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
        """Send one picture when the server loaded the Q8 mmproj.

        ``/props`` has to report vision. Until then the 35B was started
        without the picture file, and a restart is what loads it.
        """
        del keep_alive
        if not images_b64:
            raise ValueError("chat_with_images needs at least one image")
        if not await self.sees_images(model):
            raise RuntimeError(
                "Pictures are off for the llama.cpp provider. "
                "This server has no vision model. "
                "Restart it once so it loads the picture file."
            )
        content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt or "Describe this image."}
        ]
        for raw in images_b64:
            content.append(_image_part(str(raw)))
        parts: list[str] = []
        async for kind, payload in self.stream_chat(
            model,
            [{"role": "user", "content": content}],
            options=options,
            think=think,
        ):
            if kind == "thinking":
                chunk = str(payload or "")
                if chunk and on_thinking is not None:
                    maybe = on_thinking(chunk)
                    if inspect.isawaitable(maybe):
                        await maybe
            elif kind == "token":
                parts.append(str(payload or ""))
        return "".join(parts).strip()

    async def refresh_embeds(self) -> bool:
        """True only when the CPU embed server answers ``/v1/embeddings``.

        A failed probe is retried after ``_EMBED_PROBE_RETRY_S`` on the next
        call (monotonic clock). A server started after Arelis is picked up
        without a restart. No background thread.
        """
        if self._embed_ok is True:
            return True
        if self._embed_client is None:
            self.embeds = False
            self._embed_ok = False
            return False
        now = time.monotonic()
        if (
            self._embed_ok is False
            and self._embed_probed_at is not None
            and (now - self._embed_probed_at) < _EMBED_PROBE_RETRY_S
        ):
            return False
        try:
            response = await self._embed_client.post(
                "/v1/embeddings",
                json={"model": "nomic-embed-text", "input": ["ok"]},
                timeout=_PROBE_TIMEOUT_S,
            )
            ok = response.status_code < 400
        except httpx.HTTPError:
            ok = False
        self._embed_ok = ok
        self._embed_probed_at = now
        self.embeds = ok
        return ok

    async def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed on the CPU llama-server at ``embed_url``, never the 35B card."""
        if not self.embed_url or self._embed_client is None:
            raise RuntimeError(
                "Embeddings are off for the llama.cpp provider. "
                "This server does not load an embed model."
            )
        if not await self.refresh_embeds():
            raise RuntimeError(
                "Embeddings are off for the llama.cpp provider. "
                "The CPU embed server is not answering."
            )
        if not texts:
            return []
        try:
            response = await self._embed_client.post(
                "/v1/embeddings",
                json={"model": model, "input": texts},
            )
        except httpx.HTTPError as exc:
            self.embeds = False
            self._embed_ok = False
            self._embed_probed_at = time.monotonic()
            raise RuntimeError(
                f"llama.cpp embed failed for model `{model}`: {exc}"
            ) from exc
        if response.status_code >= 400:
            self.embeds = False
            self._embed_ok = False
            self._embed_probed_at = time.monotonic()
            detail = response.text.strip()[:400]
            raise RuntimeError(
                f"llama.cpp embed returned HTTP {response.status_code} for model `{model}`"
                + (f": {detail}" if detail else "")
            )
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"llama.cpp embed returned a body that is not JSON for `{model}`"
            ) from exc
        return _openai_vectors(payload, len(texts), model)

    async def capabilities(self, model: str) -> frozenset[str]:
        if not (model or "").strip():
            return frozenset()
        return frozenset({"completion", "tools", "thinking"})

    async def sees_images(self, model: str) -> bool:
        """True when this server was started with an mmproj (``/props``)."""
        del model
        try:
            response = await self._client.get("/props", timeout=_PROBE_TIMEOUT_S)
        except httpx.HTTPError:
            return False
        if response.status_code >= 400:
            return False
        try:
            payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return False
        modalities = payload.get("modalities") if isinstance(payload, dict) else None
        if not isinstance(modalities, dict):
            return False
        return bool(modalities.get("vision"))

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
        """Confirm the server is up. Start the 35B launch line if the port is down."""
        del model, keep_alive, options
        if self._launch_args:
            await asyncio.to_thread(ensure_server, self.base_url, self._launch_args)
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
        if self._owns_embed_client and self._embed_client is not None:
            await self._embed_client.aclose()
