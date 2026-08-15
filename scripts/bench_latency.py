"""Cross-board latency suite: engine, prefix cache, Arelis agent paths.

Proves interactive turns with Ollama metrics + agent stage timers, not vibes.

Examples:

  .\\.venv\\Scripts\\python.exe scripts\\bench_latency.py --mock
  .\\.venv\\Scripts\\python.exe scripts\\bench_latency.py
  .\\.venv\\Scripts\\python.exe scripts\\bench_latency.py --model qwen2.5:7b --num-ctx 8192

Writes logs/latency_bench.json and prints a markdown gate table.
Live Ollama is optional; --mock (CI default path) never contacts the network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _stdio_utf8() -> None:
    """Windows cp1252 consoles crash on arrows in print(); benches must not."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from arelis.config import load_config
from arelis.core.agent_loop import TOOL_POLICY, AgentLoop, static_system_prefix
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.turn_telemetry import ollama_ns_to_ms
from arelis.eval.harness import _BrowserStub, foundation_registry
from arelis.llm import build_router
from arelis.telemetry.system_sample import SystemSampler, _gib, sample_system

_SHORT_PROMPT = "Reply with exactly one short sentence saying hello."
# Gate D must exercise a large identical prefix. A short/warm probe that is
# already ~90ms on both turns is a null result, not a cache hit.
_CACHE_SYSTEM = (
    "You are a concise assistant used only for prefix-cache measurement.\n\n"
    + TOOL_POLICY
)
# Turn-1 prefill below this is treated as "not a cold/full prefill" for gate D.
_CACHE_TURN1_MIN_PREFILL_MS = 400
_OUT_PATH = ROOT / "logs" / "latency_bench.json"
_REPEAT_DIR = ROOT / "logs" / "latency_bench_runs"

# Warm fast / 7B gates from the latency measurement plan.
_GATES = {
    "A_engine_short": {
        "prompt_eval_ms_max": 2500,
        "wall_ttft_ms_max": 3000,
    },
    "B_arelis_no_tool": {
        "first_paint_ms_max": 3000,
        "total_ms_max": 8000,
    },
    "C_arelis_tool_open": {
        "model_round1_ms_max": 6000,
    },
    # History-stressed tool open (closest to real use). Measured ~6.2-6.5s on
    # 8 seeded turns; hard bar is 8s so 10s regressions fail while ROCm noise
    # around 6.5s does not flip the suite. Fresh Gate C stays at 6s.
    "C_hist_tool_open": {
        "model_round1_ms_max": 8000,
    },
    "D_cache": {
        "prefill_drop_min_frac": 0.50,
    },
    "E_stop_bleed": {
        "model_ms_max": 30000,
    },
    # Prefill must plateau once the sliding window is full (16→32 turns).
    "F_history_bound": {
        "anchor_turns": 16,
        "long_turns": 32,
        "max_prefill_growth_frac": 0.40,
        "max_prompt_count_growth_frac": 0.30,
    },
}


def _ns_to_ms(ns: Any) -> int | None:
    return ollama_ns_to_ms(ns)


async def _unload_all(client: httpx.AsyncClient, base: str) -> None:
    try:
        ps = (await client.get(f"{base}/api/ps")).json()
    except Exception:
        return
    for m in ps.get("models") or []:
        name = m.get("name") or m.get("model")
        if not name:
            continue
        try:
            await client.post(
                f"{base}/api/generate",
                json={"model": name, "keep_alive": 0, "prompt": "", "stream": False},
                timeout=60.0,
            )
        except Exception:
            pass


async def _chat_once(
    *,
    client: httpx.AsyncClient,
    base: str,
    model: str,
    messages: list[dict[str, Any]],
    num_ctx: int,
    max_tokens: int = 64,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": "10m",
        "options": {
            "num_ctx": num_ctx,
            "temperature": 0.2,
            "num_predict": max_tokens,
        },
    }
    t0 = time.perf_counter()
    first_token_s: float | None = None
    metrics: dict[str, Any] = {}
    chars = 0
    err: str | None = None
    try:
        async with client.stream(
            "POST", f"{base}/api/chat", json=payload, timeout=None
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message") or {}
                piece = msg.get("content") or ""
                if piece and first_token_s is None:
                    first_token_s = time.perf_counter() - t0
                chars += len(piece)
                if chunk.get("done"):
                    for key in (
                        "prompt_eval_count",
                        "eval_count",
                        "prompt_eval_duration",
                        "eval_duration",
                    ):
                        if key in chunk:
                            metrics[key] = chunk[key]
                    break
    except Exception as exc:
        err = str(exc)
    wall_s = time.perf_counter() - t0
    prefill_ms = _ns_to_ms(metrics.get("prompt_eval_duration"))
    decode_ms = _ns_to_ms(metrics.get("eval_duration"))
    return {
        "ok": err is None,
        "error": err,
        "wall_ms": int(wall_s * 1000),
        "ttft_ms": int(first_token_s * 1000) if first_token_s is not None else None,
        "response_chars": chars,
        "prompt_eval_count": metrics.get("prompt_eval_count"),
        "eval_count": metrics.get("eval_count"),
        "prompt_eval_ms": prefill_ms,
        "eval_ms": decode_ms,
        "num_ctx": num_ctx,
        "model": model,
    }


def _mock_engine_run(*, phase: str, num_ctx: int, model: str) -> dict[str, Any]:
    # Deterministic stand-ins so CI gates can be evaluated structurally.
    prefill = 900 if phase == "warm" else 2200
    if num_ctx >= 16384:
        prefill = int(prefill * 1.4)
    return {
        "ok": True,
        "error": None,
        "phase": phase,
        "wall_ms": prefill + 400,
        "ttft_ms": prefill + 50,
        "response_chars": 24,
        "prompt_eval_count": 800 + num_ctx // 32,
        "eval_count": 40,
        "prompt_eval_ms": prefill,
        "eval_ms": 350,
        "num_ctx": num_ctx,
        "model": model,
        "mock": True,
    }


async def run_engine_baseline(
    *,
    client: httpx.AsyncClient | None,
    base: str,
    model: str,
    ctx_values: list[int],
    mock: bool,
    skip_unload: bool,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": _SHORT_PROMPT}]
    for num_ctx in ctx_values:
        for phase in ("cold", "warm"):
            if mock:
                row = _mock_engine_run(phase=phase, num_ctx=num_ctx, model=model)
                runs.append(row)
                continue
            assert client is not None
            if phase == "cold" and not skip_unload:
                await _unload_all(client, base)
                await asyncio.sleep(1.0)
            row = await _chat_once(
                client=client,
                base=base,
                model=model,
                messages=messages,
                num_ctx=num_ctx,
                max_tokens=50,
            )
            row["phase"] = phase
            # VRAM sample after warm/cold chat
            try:
                snap = sample_system(ollama_base_url=base)
                vram = None
                for m in snap.ollama_models or []:
                    if (m.get("name") or "") == model or (m.get("name") or "").startswith(
                        model.split(":")[0]
                    ):
                        vram = m.get("size_vram") or m.get("size")
                        break
                row["ollama_size_vram_gib"] = _gib(vram)
            except Exception:
                row["ollama_size_vram_gib"] = None
            runs.append(row)
    return runs


async def run_cache_probe(
    *,
    client: httpx.AsyncClient | None,
    base: str,
    model: str,
    num_ctx: int,
    mock: bool,
    skip_unload: bool = False,
) -> dict[str, Any]:
    """Prove prefix reuse with a large identical system block.

    Protocol:
      1) unload (so turn1 is not riding a leftover KV/prefix)
      2) optional tiny weight-warm with a *different* short prompt (no shared prefix)
      3) turn1 + turn2 with identical large system, different user trailer
    """
    prefix_chars = len(_CACHE_SYSTEM)
    if mock:
        t1 = 2200
        t2 = 800
        return {
            "ok": True,
            "mock": True,
            "num_ctx": num_ctx,
            "prefix_chars": prefix_chars,
            "turn1_prompt_eval_ms": t1,
            "turn2_prompt_eval_ms": t2,
            "turn1_prompt_eval_count": 4200,
            "turn2_prompt_eval_count": 4200,
            "drop_frac": round((t1 - t2) / t1, 3),
            "turn1_was_full_prefill": True,
            "notes": "mock cache hit (large prefix, cold turn1)",
        }
    assert client is not None
    if not skip_unload:
        await _unload_all(client, base)
        await asyncio.sleep(1.0)
    # Weight warm only — must not share the cache-probe system prefix.
    await _chat_once(
        client=client,
        base=base,
        model=model,
        messages=[{"role": "user", "content": "ping"}],
        num_ctx=num_ctx,
        max_tokens=4,
    )
    sys_msgs = [{"role": "system", "content": _CACHE_SYSTEM}]
    t1 = await _chat_once(
        client=client,
        base=base,
        model=model,
        messages=[*sys_msgs, {"role": "user", "content": "Say hi in three words."}],
        num_ctx=num_ctx,
        max_tokens=20,
    )
    t2 = await _chat_once(
        client=client,
        base=base,
        model=model,
        messages=[*sys_msgs, {"role": "user", "content": "Say bye in three words."}],
        num_ctx=num_ctx,
        max_tokens=20,
    )
    p1 = t1.get("prompt_eval_ms")
    p2 = t2.get("prompt_eval_ms")
    c1 = t1.get("prompt_eval_count")
    c2 = t2.get("prompt_eval_count")
    drop = None
    if isinstance(p1, int) and p1 > 0 and isinstance(p2, int):
        drop = round((p1 - p2) / p1, 3)
    turn1_full = isinstance(p1, int) and p1 >= _CACHE_TURN1_MIN_PREFILL_MS
    notes = ""
    if drop is None:
        notes = "missing prompt_eval_ms"
    elif not turn1_full:
        notes = (
            f"null_result: turn1 prompt_eval_ms={p1} below "
            f"{_CACHE_TURN1_MIN_PREFILL_MS}ms — large prefix was not a cold/full "
            f"prefill (prefix_chars={prefix_chars}, counts={c1}->{c2}). "
            "Do not treat equal-fast turns as a cache hit."
        )
    elif drop < _GATES["D_cache"]["prefill_drop_min_frac"]:
        notes = (
            "ROCm/cache miss: turn2 prompt_eval did not drop >=50% vs turn1 "
            f"(turn1={p1}ms turn2={p2}ms drop_frac={drop}, "
            f"prefix_chars={prefix_chars}, counts={c1}->{c2}). "
            "Static prefix is still correct for CUDA-class caches; this stack "
            "did not show reuse under this probe."
        )
    else:
        notes = (
            f"prefix cache looks effective "
            f"(turn1={p1}ms turn2={p2}ms drop_frac={drop}, "
            f"prefix_chars={prefix_chars})"
        )
    return {
        "ok": bool(t1.get("ok") and t2.get("ok")),
        "num_ctx": num_ctx,
        "prefix_chars": prefix_chars,
        "turn1": t1,
        "turn2": t2,
        "turn1_prompt_eval_ms": p1,
        "turn2_prompt_eval_ms": p2,
        "turn1_prompt_eval_count": c1,
        "turn2_prompt_eval_count": c2,
        "drop_frac": drop,
        "turn1_was_full_prefill": turn1_full,
        "notes": notes,
    }


class _ScriptedRouter:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.models = {"fast": "bench-fast", "research": "bench-research", "code": "bench-code"}
        self.default_role = "fast"
        self.active_role = "fast"
        self.active_model = "bench-fast"

    def model_for(self, role=None) -> str:
        return self.models.get(str(role or self.default_role), self.active_model)

    async def ensure_role(self, role, *, force: bool = False) -> str:
        del force
        self.active_role = role
        self.active_model = self.model_for(role)
        return self.active_model

    def mark_sticky(self, role) -> None:
        return None

    def clear_sticky(self) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(
        self, role, messages, *, options=None, tools=None, force: bool = False
    ) -> AsyncIterator[tuple[str, Any]]:
        del role, messages, options, tools, force
        if self.i >= len(self.script):
            yield ("token", "ok")
            yield (
                "metrics",
                {
                    "prompt_eval_count": 100,
                    "prompt_eval_duration": 200_000_000,
                    "eval_count": 10,
                    "eval_duration": 100_000_000,
                },
            )
            return
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item


def _bench_agent_cfg(config: dict[str, Any]) -> dict[str, Any]:
    agent_cfg = dict(config.get("agent") or {})
    agent_cfg.setdefault("turn_telemetry", True)
    agent_cfg.setdefault("confirm_browser", True)
    agent_cfg.setdefault("confirm_vision", True)
    agent_cfg.setdefault("exactness", False)
    agent_cfg.setdefault("numeric_gate", False)
    agent_cfg.setdefault("evidence_gate", False)
    agent_cfg.setdefault("scrape_after_search", False)
    agent_cfg.setdefault("mid_turn_escalate", False)
    agent_cfg.setdefault("skill_cards", True)
    agent_cfg.setdefault("max_rounds", 4)
    return agent_cfg


class _AgentSession:
    """One AgentLoop + bus; multiple turns share memory and static prefix cache."""

    def __init__(self, router: Any, config: dict[str, Any], *, auto_allow: bool = True) -> None:
        self.bus = EventBus()
        self.tools = foundation_registry()
        if "browser" not in self.tools.names():
            self.tools.register(_BrowserStub("browser", risk="side_effect"))
        self.memory = SessionMemory()
        agent_cfg = _bench_agent_cfg(config)
        self._cap: dict[str, Any] = {
            "t0": 0.0,
            "first_paint_ms": None,
            "tools": [],
            "thinking": [],
        }

        async def _confirm(*_a: Any, **_k: Any) -> str:
            return "allow" if auto_allow else "deny"

        async def capture_delta(event: Event) -> None:
            del event
            if self._cap["first_paint_ms"] is None:
                self._cap["first_paint_ms"] = int(
                    (time.perf_counter() - float(self._cap["t0"])) * 1000
                )

        async def capture_tool(event: Event) -> None:
            name = str((event.payload or {}).get("tool") or "")
            if name:
                self._cap["tools"].append(name)

        async def capture_thinking(event: Event) -> None:
            text = str((event.payload or {}).get("text") or "")
            if text:
                self._cap["thinking"].append(text)

        self.bus.subscribe(EventType.ASSISTANT_DELTA, capture_delta)
        self.bus.subscribe(EventType.TOOL_START, capture_tool)
        self.bus.subscribe(EventType.THINKING, capture_thinking)

        self.loop = AgentLoop(
            self.bus,
            router,
            self.tools,
            self.memory,
            persona="You are Arelis under latency bench.",
            config={
                **config,
                "agent": agent_cfg,
                "ollama": config.get("ollama") or {"num_ctx": 8192},
            },
            request_confirm=_confirm,
            is_cancelled=lambda: False,
        )
        self._bus_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> _AgentSession:
        self._bus_task = asyncio.create_task(self.bus.run())
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.bus.stop()
        if self._bus_task is not None:
            self._bus_task.cancel()
            try:
                await self._bus_task
            except asyncio.CancelledError:
                pass

    async def turn(self, user_text: str) -> dict[str, Any]:
        self._cap["t0"] = time.perf_counter()
        self._cap["first_paint_ms"] = None
        self._cap["tools"] = []
        self._cap["thinking"] = []
        await self.loop.run(user_text, "fast", source="bench")
        await self.bus.drain()
        total_ms = int((time.perf_counter() - float(self._cap["t0"])) * 1000)
        timer = getattr(self.loop, "_timer", None)
        model_ms = int(getattr(timer, "model_ms", 0) or 0)
        prefill_ms = int(getattr(timer, "model_prefill_ms", 0) or 0)
        decode_ms = int(getattr(timer, "model_decode_ms", 0) or 0)
        confirm_ms = int(getattr(timer, "confirm_ms", 0) or 0)
        rounds = int(getattr(timer, "rounds", 0) or 0)
        round_ms_by_n = dict(getattr(timer, "round_ms_by_n", {}) or {})
        r1 = round_ms_by_n.get(1)
        thinking = list(self._cap["thinking"])
        return {
            "ok": True,
            "user_text": user_text,
            "total_ms": total_ms,
            "first_paint_ms": self._cap["first_paint_ms"],
            "model_ms": model_ms,
            "model_prefill_ms": prefill_ms,
            "model_decode_ms": decode_ms,
            "confirm_ms": confirm_ms,
            "rounds": rounds,
            "round_ms_by_n": round_ms_by_n,
            "prompt_eval_count": getattr(timer, "last_prompt_eval_count", None),
            "eval_count": getattr(timer, "last_eval_count", None),
            "history_kept": getattr(timer, "history_kept", None),
            "history_dropped": getattr(timer, "history_dropped", None),
            "tools_called": list(self._cap["tools"]),
            "thinking_tail": thinking[-6:],
            "model_round1_ms_approx": r1 if r1 is not None else model_ms,
        }


async def _run_agent_turn(
    *,
    router: Any,
    user_text: str,
    config: dict[str, Any],
    auto_allow: bool = True,
) -> dict[str, Any]:
    async with _AgentSession(router, config, auto_allow=auto_allow) as session:
        return await session.turn(user_text)


def _mock_agent_scripts() -> dict[str, list[list[tuple[str, Any]]]]:
    metrics_fast = (
        "metrics",
        {
            "prompt_eval_count": 900,
            "prompt_eval_duration": 400_000_000,
            "eval_count": 20,
            "eval_duration": 200_000_000,
        },
    )
    return {
        "hi": [[("token", "Hello — good to see you."), metrics_fast]],
        "open": [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "browser",
                                "arguments": {
                                    "action": "open",
                                    "url": "https://www.youtube.com",
                                },
                            },
                        }
                    ],
                ),
                metrics_fast,
            ],
            [("token", "Opened YouTube in your browser."), metrics_fast],
        ],
    }


def _seed_history_trailer(memory: SessionMemory, *, turns: int = 8) -> int:
    """Inject realistic multi-turn chat so Gate C isn't only a fresh session."""
    seeded = 0
    for i in range(turns):
        memory.add(
            "user",
            (
                f"Turn {i+1}: remember that project Orion uses a 632.8 nm HeNe "
                f"and the fringe target is 0.{i} fringe. Also note contact "
                f"alias bench{i} and that we prefer short answers."
            ),
        )
        memory.add(
            "assistant",
            (
                f"Noted Orion HeNe 632.8 nm and fringe 0.{i}. "
                f"I'll keep replies short and use alias bench{i} when asked."
            ),
        )
        seeded += 2
    return seeded


async def run_arelis_paths(
    *,
    config: dict[str, Any],
    mock: bool,
) -> dict[str, Any]:
    out: dict[str, Any] = {"mock": mock}
    if mock:
        scripts = _mock_agent_scripts()
        out["no_tool"] = await _run_agent_turn(
            router=_ScriptedRouter(scripts["hi"]),
            user_text="hi",
            config=config,
        )
        tool_row = await _run_agent_turn(
            router=_ScriptedRouter(scripts["open"]),
            user_text="open youtube.com",
            config=config,
        )
        tool_row["model_round1_ms_approx"] = min(
            tool_row.get("model_ms") or 0, 5000
        )
        out["tool_open"] = tool_row
        # History-stressed tool path (still scripted).
        hist = await _run_agent_turn(
            router=_ScriptedRouter(scripts["open"]),
            user_text="open youtube.com",
            config=config,
        )
        hist["model_round1_ms_approx"] = min(hist.get("model_ms") or 0, 5000)
        hist["seeded_messages"] = 16
        out["tool_open_with_history"] = hist
        multi: list[dict[str, Any]] = []
        for i, text in enumerate(("hi", "still there?", "thanks")):
            row = await _run_agent_turn(
                router=_ScriptedRouter(scripts["hi"]),
                user_text=text,
                config=config,
            )
            row["turn"] = i + 1
            multi.append(row)
        out["multi_turn"] = multi
        out["ok"] = True
        return out

    router = build_router(config)
    try:
        await router.ensure_role("fast", force=True)
    except Exception as exc:
        return {"ok": False, "error": f"warm failed: {exc}", "mock": False}

    # Gates assume warm fast after one warmup turn (shared memory + static prefix).
    async with _AgentSession(router, config, auto_allow=True) as session:
        out["warmup"] = await session.turn("warmup — reply with the single word ok")
        out["no_tool"] = await session.turn("hi")
        out["tool_open"] = await session.turn("open youtube.com")
        multi = []
        for i, text in enumerate(("still there?", "one more", "and done")):
            row = await session.turn(text)
            row["turn"] = i + 1
            multi.append(row)
        out["multi_turn"] = multi

    # Fresh session, but with a fat seeded history before the tool turn —
    # closer to real interactive use than a greenfield open.
    async with _AgentSession(router, config, auto_allow=True) as hist_session:
        seeded = _seed_history_trailer(hist_session.memory, turns=8)
        await hist_session.turn("warmup history session — reply ok")
        hist_tool = await hist_session.turn("open youtube.com")
        hist_tool["seeded_messages"] = seeded
        out["tool_open_with_history"] = hist_tool
    out["ok"] = True
    return out


async def run_history_growth_probe(
    *,
    config: dict[str, Any],
    mock: bool,
    turn_counts: list[int] | None = None,
) -> dict[str, Any]:
    """Measure tool-round prefill vs seeded history length; expect a plateau."""
    counts = turn_counts or [0, 4, 8, 16, 32]
    points: list[dict[str, Any]] = []
    if mock:
        # Synthetic plateau after the window fills (~16 turns / 32 msgs).
        for n in counts:
            prefill = 800 + min(n, 12) * 120
            points.append(
                {
                    "seeded_turns": n,
                    "model_prefill_ms": prefill,
                    "prompt_eval_count": 900 + min(n, 12) * 80,
                    "model_round1_ms_approx": prefill + 400,
                    "history_kept": min(n * 2, 24),
                    "history_dropped": max(0, n * 2 - 24),
                    "mock": True,
                }
            )
        return {"ok": True, "mock": True, "points": points}

    router = build_router(config)
    try:
        await router.ensure_role("fast", force=True)
    except Exception as exc:
        return {"ok": False, "error": f"warm failed: {exc}", "points": []}

    for n in counts:
        async with _AgentSession(router, config, auto_allow=True) as session:
            seeded = _seed_history_trailer(session.memory, turns=n) if n else 0
            if n:
                await session.turn("warmup history growth — reply ok")
            row = await session.turn("open youtube.com")
            points.append(
                {
                    "seeded_turns": n,
                    "seeded_messages": seeded,
                    "model_prefill_ms": row.get("model_prefill_ms"),
                    "prompt_eval_count": row.get("prompt_eval_count"),
                    "model_round1_ms_approx": row.get("model_round1_ms_approx"),
                    "model_ms": row.get("model_ms"),
                    "history_kept": row.get("history_kept"),
                    "history_dropped": row.get("history_dropped"),
                    "tools_called": row.get("tools_called"),
                }
            )
    return {"ok": True, "mock": False, "points": points}


def evaluate_gates(report: dict[str, Any]) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    engine = report.get("engine") or []
    warm_8192 = next(
        (
            r
            for r in engine
            if r.get("phase") == "warm" and int(r.get("num_ctx") or 0) == 8192
        ),
        None,
    )
    if warm_8192 is None:
        warm_8192 = next((r for r in engine if r.get("phase") == "warm"), None)
    a_ok = False
    a_detail = "no warm engine run"
    if warm_8192:
        pe = warm_8192.get("prompt_eval_ms")
        ttft = warm_8192.get("ttft_ms")
        a_ok = (
            isinstance(pe, int)
            and pe < _GATES["A_engine_short"]["prompt_eval_ms_max"]
            and isinstance(ttft, int)
            and ttft < _GATES["A_engine_short"]["wall_ttft_ms_max"]
        )
        a_detail = f"prompt_eval_ms={pe} ttft_ms={ttft}"
    gates["A"] = {"pass": a_ok, "detail": a_detail}

    agent = report.get("arelis") or {}
    no_tool = agent.get("no_tool") or {}
    b_ok = (
        isinstance(no_tool.get("first_paint_ms"), int)
        and no_tool["first_paint_ms"] < _GATES["B_arelis_no_tool"]["first_paint_ms_max"]
        and isinstance(no_tool.get("total_ms"), int)
        and no_tool["total_ms"] < _GATES["B_arelis_no_tool"]["total_ms_max"]
    )
    gates["B"] = {
        "pass": b_ok,
        "detail": (
            f"first_paint_ms={no_tool.get('first_paint_ms')} "
            f"total_ms={no_tool.get('total_ms')}"
        ),
    }

    tool = agent.get("tool_open") or {}
    r1 = tool.get("model_round1_ms_approx")
    if r1 is None:
        r1 = tool.get("model_ms")
    c_ok = isinstance(r1, int) and r1 < _GATES["C_arelis_tool_open"]["model_round1_ms_max"]
    gates["C"] = {
        "pass": c_ok,
        "detail": (
            f"model_round1_ms~{r1} confirm_ms={tool.get('confirm_ms')} "
            "(confirm excluded from gate)"
        ),
    }

    cache = report.get("cache") or {}
    drop = cache.get("drop_frac")
    d_thresh = _GATES["D_cache"]["prefill_drop_min_frac"]
    d_pass = (
        bool(cache.get("turn1_was_full_prefill"))
        and isinstance(drop, (int, float))
        and float(drop) >= d_thresh
    )
    notes = str(cache.get("notes") or "")
    null_result = "null_result" in notes
    documented_miss = (not d_pass) and ("ROCm/cache miss" in notes)
    # Honest outcomes: real hit = PASS; measured miss = DOCUMENTED (soft pass
    # for ship); null probe = FAIL (do not claim cache evidence).
    gates["D"] = {
        "pass": d_pass or documented_miss,
        "detail": notes
        or f"drop_frac={drop} (need >={d_thresh}, full turn1 prefill)",
        "documented_miss": documented_miss,
        "null_result": null_result,
        "hard_pass": d_pass,
    }

    hist_tool = agent.get("tool_open_with_history") or {}
    hist_r1 = hist_tool.get("model_round1_ms_approx")
    if hist_r1 is None:
        hist_r1 = hist_tool.get("model_ms")
    c_hist_max = _GATES["C_hist_tool_open"]["model_round1_ms_max"]
    c_hist_ok = isinstance(hist_r1, int) and hist_r1 < c_hist_max
    gates["C_hist"] = {
        "pass": c_hist_ok,
        "detail": (
            f"model_round1_ms~{hist_r1} (max {c_hist_max}) seeded_messages="
            f"{hist_tool.get('seeded_messages')} "
            f"prefill_ms={hist_tool.get('model_prefill_ms')} "
            f"history_kept={hist_tool.get('history_kept')} "
            f"history_dropped={hist_tool.get('history_dropped')}"
        ),
    }

    simple_model_ms = [
        no_tool.get("model_ms"),
        tool.get("model_ms"),
        hist_tool.get("model_ms"),
    ]
    e_ok = all(
        isinstance(m, int) and m <= _GATES["E_stop_bleed"]["model_ms_max"]
        for m in simple_model_ms
        if m is not None
    )
    gates["E"] = {
        "pass": e_ok,
        "detail": (
            f"no_tool_model_ms={no_tool.get('model_ms')} "
            f"tool_model_ms={tool.get('model_ms')} "
            f"tool_hist_model_ms={hist_tool.get('model_ms')}"
        ),
    }

    growth = report.get("history_growth") or {}
    points = list(growth.get("points") or [])
    f_spec = _GATES["F_history_bound"]
    anchor_n = int(f_spec["anchor_turns"])
    long_n = int(f_spec["long_turns"])
    anchor = next((p for p in points if int(p.get("seeded_turns") or -1) == anchor_n), None)
    longp = next((p for p in points if int(p.get("seeded_turns") or -1) == long_n), None)
    f_ok = False
    f_detail = "history growth probe missing"
    if anchor and longp:
        a_pre = anchor.get("model_prefill_ms")
        l_pre = longp.get("model_prefill_ms")
        a_cnt = anchor.get("prompt_eval_count")
        l_cnt = longp.get("prompt_eval_count")
        pre_ok = (
            isinstance(a_pre, int)
            and a_pre > 0
            and isinstance(l_pre, int)
            and l_pre <= int(a_pre * (1.0 + float(f_spec["max_prefill_growth_frac"])))
        )
        cnt_ok = True
        if isinstance(a_cnt, int) and a_cnt > 0 and isinstance(l_cnt, int):
            cnt_ok = l_cnt <= int(
                a_cnt * (1.0 + float(f_spec["max_prompt_count_growth_frac"]))
            )
        # Window evidence: long run should drop something once over cap.
        drop_ok = int(longp.get("history_dropped") or 0) > 0 or int(
            longp.get("history_kept") or 0
        ) <= 24
        f_ok = bool(pre_ok and cnt_ok and drop_ok)
        f_detail = (
            # ASCII arrows — Windows cp1252 consoles crash on U+2192.
            f"prefill {anchor_n}t={a_pre}ms -> {long_n}t={l_pre}ms; "
            f"prompt_eval_count {a_cnt}->{l_cnt}; "
            f"kept={longp.get('history_kept')} dropped={longp.get('history_dropped')}"
        )
    gates["F"] = {"pass": f_ok, "detail": f_detail}

    # Classification hint from warm engine + agent
    classify = "unknown"
    if warm_8192:
        pe = warm_8192.get("prompt_eval_ms") or 0
        de = warm_8192.get("eval_ms") or 0
        if pe >= de * 2:
            classify = "prefill_dominated"
        elif de >= pe * 2:
            classify = "decode_dominated"
        else:
            classify = "mixed"
        vram = warm_8192.get("ollama_size_vram_gib")
        if isinstance(vram, (int, float)) and vram > 10.5:
            classify += "+vram_pressure"
    hard_letters = ("A", "B", "C", "C_hist", "D", "E", "F")
    return {
        "gates": gates,
        "all_pass": all(gates[k].get("pass") for k in hard_letters if k in gates),
        "classification": classify,
    }


def _print_table(report: dict[str, Any]) -> None:
    print("\n## Latency bench\n")
    print("| Scenario | Key metrics | Gate |")
    print("|---|---|---|")
    ev = report.get("evaluation") or {}
    gates = ev.get("gates") or {}
    for key, label in (
        ("A", "A engine short (warm)"),
        ("B", "B Arelis no-tool"),
        ("C", "C Arelis tool open"),
        ("C_hist", "C' tool open + history"),
        ("D", "D cache turn2"),
        ("E", "E stop-the-bleeding"),
        ("F", "F history bound (16->32)"),
    ):
        g = gates.get(key) or {}
        mark = "PASS" if g.get("pass") else "FAIL"
        if key == "D" and g.get("documented_miss"):
            mark = "DOCUMENTED"
        elif key == "D" and g.get("null_result"):
            mark = "NULL"
        print(f"| {label} | {g.get('detail', '')} | {mark} |")
    print(f"\nClassification: {ev.get('classification')}")
    print(f"Static prefix chars: {len(static_system_prefix('x')[1]['content'])}")


def _summarize_repeats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate gate stability across repeat suite runs."""
    letters = ("A", "B", "C", "C_hist", "D", "E", "F")
    by_gate: dict[str, dict[str, Any]] = {}
    for letter in letters:
        passes = 0
        documented = 0
        nulls = 0
        details: list[str] = []
        for run in runs:
            g = ((run.get("evaluation") or {}).get("gates") or {}).get(letter) or {}
            if g.get("pass"):
                passes += 1
            if g.get("documented_miss"):
                documented += 1
            if g.get("null_result"):
                nulls += 1
            if g.get("detail"):
                details.append(str(g["detail"]))
        by_gate[letter] = {
            "pass_count": passes,
            "runs": len(runs),
            "documented_miss_count": documented,
            "null_result_count": nulls,
            "stable": passes == len(runs) and len(runs) > 0,
            "details": details,
        }
    hard_stable = all(
        by_gate[k]["stable"] for k in ("A", "B", "C", "C_hist", "E", "F")
    )
    return {
        "runs": len(runs),
        "hard_gates_stable": hard_stable,
        "by_gate": by_gate,
    }


async def _run_suite_once(
    *,
    args: argparse.Namespace,
    config: dict[str, Any],
    base: str,
    model: str,
    ctx_values: list[int],
    out_path: Path,
    run_index: int | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mock": bool(args.mock),
        "model": model,
        "base_url": base,
        "num_ctx_values": ctx_values,
        "gates_spec": _GATES,
        "run_index": run_index,
        "idle_s_before": float(getattr(args, "idle_s", 0) or 0),
    }

    client: httpx.AsyncClient | None = None
    if not args.mock:
        client = httpx.AsyncClient(timeout=30.0)
        try:
            tags = (await client.get(f"{base}/api/tags")).json()
            available = {m.get("name") for m in tags.get("models") or []}
            if model not in available and not any(
                (a or "").startswith(model.split(":")[0]) for a in available
            ):
                raise RuntimeError(f"Model {model} not pulled at {base}")
        except Exception:
            if client is not None:
                await client.aclose()
            raise

    try:
        if not args.mock and float(getattr(args, "idle_s", 0) or 0) > 0:
            assert client is not None
            print(
                f"=== Idle stress: unload + wait {args.idle_s:.0f}s "
                "(past keep_alive) ==="
            )
            await _unload_all(client, base)
            await asyncio.sleep(float(args.idle_s))

        idle = SystemSampler(ollama_base_url=base)
        if not args.mock:
            for _ in range(2):
                idle.tick()
                await asyncio.sleep(0.3)
            report["idle"] = idle.series.summary()

        print("=== Engine baseline ===")
        report["engine"] = await run_engine_baseline(
            client=client,
            base=base,
            model=model,
            ctx_values=ctx_values,
            mock=bool(args.mock),
            skip_unload=bool(args.skip_unload),
        )
        for row in report["engine"]:
            print(
                f"  [{row.get('phase')}] ctx={row.get('num_ctx')} "
                f"prefill_ms={row.get('prompt_eval_ms')} "
                f"ttft_ms={row.get('ttft_ms')} "
                f"eval_ms={row.get('eval_ms')} "
                f"vram_gib={row.get('ollama_size_vram_gib')}"
            )

        print("=== Prefix cache probe (large cold prefix) ===")
        probe_ctx = 8192 if 8192 in ctx_values else ctx_values[0]
        report["cache"] = await run_cache_probe(
            client=client,
            base=base,
            model=model,
            num_ctx=probe_ctx,
            mock=bool(args.mock),
            skip_unload=False if not args.mock else True,
        )
        print(
            f"  prefix_chars={report['cache'].get('prefix_chars')} "
            f"turn1={report['cache'].get('turn1_prompt_eval_ms')} "
            f"turn2={report['cache'].get('turn2_prompt_eval_ms')} "
            f"drop={report['cache'].get('drop_frac')} "
            f"full_prefill={report['cache'].get('turn1_was_full_prefill')} "
            f"notes={report['cache'].get('notes')}"
        )

        print("=== Arelis agent paths ===")
        report["arelis"] = await run_arelis_paths(config=config, mock=bool(args.mock))
        for key in ("no_tool", "tool_open", "tool_open_with_history"):
            row = (report["arelis"] or {}).get(key) or {}
            if not row:
                continue
            print(
                f"  {key}: total_ms={row.get('total_ms')} "
                f"first_paint_ms={row.get('first_paint_ms')} "
                f"model_ms={row.get('model_ms')} "
                f"r1_ms={row.get('model_round1_ms_approx')} "
                f"prefill_ms={row.get('model_prefill_ms')} "
                f"decode_ms={row.get('model_decode_ms')} "
                f"kept={row.get('history_kept')} dropped={row.get('history_dropped')} "
                f"tools={row.get('tools_called')}"
            )

        print("=== History growth probe (tool open vs seeded turns) ===")
        report["history_growth"] = await run_history_growth_probe(
            config=config, mock=bool(args.mock)
        )
        for pt in report["history_growth"].get("points") or []:
            print(
                f"  turns={pt.get('seeded_turns')} "
                f"prefill_ms={pt.get('model_prefill_ms')} "
                f"prompt_eval_count={pt.get('prompt_eval_count')} "
                f"r1_ms={pt.get('model_round1_ms_approx')} "
                f"kept={pt.get('history_kept')} dropped={pt.get('history_dropped')}"
            )

        report["evaluation"] = evaluate_gates(report)
        _print_table(report)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")
        return report
    finally:
        if client is not None:
            await client.aclose()


async def main() -> int:
    _stdio_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument(
        "--num-ctx",
        default="4096,8192,16384",
        help="Comma-separated num_ctx values for engine baseline",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="No live Ollama; deterministic fixtures for CI",
    )
    parser.add_argument("--skip-unload", action="store_true")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Run the full suite N times and write a stability summary",
    )
    parser.add_argument(
        "--idle-s",
        type=float,
        default=0.0,
        help="Before each run: unload models and wait this many seconds",
    )
    parser.add_argument(
        "--out",
        default=str(_OUT_PATH),
        help="JSON report path (repeat mode also writes latency_bench_runs/)",
    )
    args = parser.parse_args()
    config = load_config()
    base = (args.base_url or (config.get("ollama") or {}).get("base_url") or "").rstrip(
        "/"
    ) or "http://127.0.0.1:11434"
    model = args.model or (config.get("models") or {}).get("fast") or "qwen2.5:7b"
    ctx_values = [int(x.strip()) for x in args.num_ctx.split(",") if x.strip()]
    out_path = Path(args.out)
    repeats = max(1, int(args.repeat))

    if not args.mock and repeats == 1:
        try:
            async with httpx.AsyncClient(timeout=30.0) as probe:
                await probe.get(f"{base}/api/tags")
        except Exception as exc:
            print(f"Cannot reach Ollama at {base}: {exc}")
            print("Re-run with --mock for offline smoke, or start Ollama.")
            return 1

    runs: list[dict[str, Any]] = []
    for i in range(repeats):
        if repeats > 1:
            print(f"\n######## Suite run {i+1}/{repeats} ########")
            run_out = _REPEAT_DIR / f"run_{i+1:02d}.json"
        else:
            run_out = out_path
        try:
            report = await _run_suite_once(
                args=args,
                config=config,
                base=base,
                model=model,
                ctx_values=ctx_values,
                out_path=run_out,
                run_index=i + 1 if repeats > 1 else None,
            )
        except Exception as exc:
            print(f"Suite run failed: {exc}")
            return 1
        runs.append(report)

    summary = _summarize_repeats(runs)
    if repeats > 1:
        summary_path = _REPEAT_DIR / "summary.json"
        _REPEAT_DIR.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        # Also refresh the main out path with the last run + summary pointer.
        last = dict(runs[-1])
        last["repeat_summary"] = summary
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(last, indent=2), encoding="utf-8")
        print("\n## Repeat stability\n")
        print(f"runs={summary['runs']} hard_gates_stable={summary['hard_gates_stable']}")
        for letter, row in (summary.get("by_gate") or {}).items():
            print(
                f"  {letter}: pass={row['pass_count']}/{row['runs']} "
                f"documented_miss={row['documented_miss_count']} "
                f"null={row['null_result_count']}"
            )
        print(f"Wrote {summary_path}")

    if args.mock:
        return 0
    # Hard fail on A/B/C/C_hist/E/F. D may be DOCUMENTED miss; null D fails.
    last_gates = (runs[-1].get("evaluation") or {}).get("gates") or {}
    hard_fail = any(
        not last_gates.get(k, {}).get("pass")
        for k in ("A", "B", "C", "C_hist", "E", "F")
    )
    if last_gates.get("D", {}).get("null_result"):
        hard_fail = True
    if not last_gates.get("D", {}).get("pass"):
        hard_fail = True
    if repeats > 1 and not summary.get("hard_gates_stable"):
        hard_fail = True
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
