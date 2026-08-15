"""Load Ollama models and record host/GPU utilization while they run.

Why this exists: looking at Task Manager for a second is not a measurement.
A 7B Q4 on a 12GB AMD card often lands around ~30-45% dedicated VRAM by design
(weights + KV). This script samples Windows GPU counters + Ollama /api/ps
while generating, so you can see peaks, not vibes.

Examples:

  .\\.venv\\Scripts\\python.exe scripts\\bench_utilization.py
  .\\.venv\\Scripts\\python.exe scripts\\bench_utilization.py --models qwen2.5:7b,qwen2.5:14b
  .\\.venv\\Scripts\\python.exe scripts\\bench_utilization.py --models qwen2.5:7b --duration-s 45
  .\\.venv\\Scripts\\python.exe scripts\\bench_utilization.py --models qwen2.5:7b --cold-warm

Writes logs/utilization_bench.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arelis.telemetry.system_sample import SystemSampler, _gib, sample_system

_DEFAULT_PROMPT = (
    "Explain in about 200 words how a Michelson interferometer measures "
    "small path differences. Be concrete about the optics."
)


async def _unload_all(client: httpx.AsyncClient, base: str) -> None:
    """Best-effort: ask Ollama to drop resident models (keep_alive=0)."""
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


async def _generate_with_samples(
    *,
    client: httpx.AsyncClient,
    base: str,
    model: str,
    prompt: str,
    num_ctx: int,
    sampler: SystemSampler,
    interval_s: float,
    max_duration_s: float,
) -> dict[str, Any]:
    """Stream one generate; sample system metrics on a timer until done."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": "10m",
        "options": {"num_ctx": num_ctx, "temperature": 0.2},
    }
    t0 = time.perf_counter()
    first_token_s: float | None = None
    eval_count = 0
    eval_duration_ns = 0
    prompt_eval_count = 0
    text_chars = 0
    done = False
    err: str | None = None

    async def _pump_samples() -> None:
        while not done:
            sampler.tick()
            await asyncio.sleep(interval_s)

    sample_task = asyncio.create_task(_pump_samples())
    try:
        async with client.stream(
            "POST", f"{base}/api/generate", json=payload, timeout=None
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if time.perf_counter() - t0 > max_duration_s:
                    break
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                piece = chunk.get("response") or ""
                if piece and first_token_s is None:
                    first_token_s = time.perf_counter() - t0
                text_chars += len(piece)
                if chunk.get("done"):
                    eval_count = int(chunk.get("eval_count") or 0)
                    eval_duration_ns = int(chunk.get("eval_duration") or 0)
                    prompt_eval_count = int(chunk.get("prompt_eval_count") or 0)
                    break
    except Exception as exc:
        err = str(exc)
    finally:
        done = True
        sample_task.cancel()
        try:
            await sample_task
        except asyncio.CancelledError:
            pass
        # Final sample after generate ends (KV still warm).
        sampler.tick()

    elapsed = time.perf_counter() - t0
    tok_s = None
    if eval_count and eval_duration_ns:
        tok_s = eval_count / (eval_duration_ns / 1e9)
    # Ollama's view of residency right after the run.
    ollama_after = sample_system(ollama_base_url=base).ollama_models
    summary = sampler.series.summary()
    # Prefer Ollama-reported size_vram when present (often more accurate for AMD).
    ollama_vram = None
    for m in ollama_after:
        if (m.get("name") or "").startswith(model.split(":")[0]) or m.get("name") == model:
            ollama_vram = m.get("size_vram") or m.get("size")
            break
    if ollama_vram is None and ollama_after:
        ollama_vram = ollama_after[0].get("size_vram") or ollama_after[0].get("size")

    return {
        "model": model,
        "ok": err is None,
        "error": err,
        "wall_s": round(elapsed, 3),
        "ttft_s": round(first_token_s, 3) if first_token_s is not None else None,
        "eval_count": eval_count,
        "prompt_eval_count": prompt_eval_count,
        "tokens_per_s": round(tok_s, 2) if tok_s else None,
        "response_chars": text_chars,
        "num_ctx": num_ctx,
        "host": summary,
        "ollama_size_vram_bytes": ollama_vram,
        "ollama_size_vram_gib": _gib(ollama_vram),
        "ollama_ps": ollama_after,
        "interpretation": _interpret(summary, ollama_vram),
    }


def _interpret(summary: dict[str, Any], ollama_vram: int | None) -> str:
    ded = summary.get("gpu_dedicated_peak_gib")
    frac = summary.get("vram_fraction_of_12gib")
    bits: list[str] = []
    if ollama_vram:
        bits.append(f"Ollama reports ~{_gib(ollama_vram)} GiB resident for this model.")
    if ded is not None:
        bits.append(f"Windows dedicated GPU memory peaked at ~{ded} GiB.")
    if frac is not None:
        pct = round(float(frac) * 100)
        bits.append(f"That is ~{pct}% of a 12 GiB card.")
        if pct < 55:
            bits.append(
                "Seeing ~30-50% with a 7B Q4 is normal - headroom exists for a "
                "14B Q4 or a larger num_ctx, not evidence the 7B is 'broken'."
            )
        elif pct > 85:
            bits.append(
                "You are near the VRAM ceiling; a larger model or longer context "
                "may spill to system RAM and get much slower."
            )
    if not bits:
        bits.append(
            "GPU counters were empty — check Task Manager's GPU 'Dedicated GPU "
            "memory' during the run, and trust Ollama size_vram if present."
        )
    return " ".join(bits)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        default="qwen2.5:7b",
        help="Comma-separated Ollama tags",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument(
        "--compare-ctx",
        default="",
        help=(
            "Comma-separated num_ctx values to compare (e.g. 8192,16384). "
            "Overrides --num-ctx; writes one report with per-ctx runs."
        ),
    )
    parser.add_argument("--interval-s", type=float, default=0.75)
    parser.add_argument(
        "--duration-s",
        type=float,
        default=120.0,
        help="Max wall time per model generate",
    )
    parser.add_argument("--prompt", default=_DEFAULT_PROMPT)
    parser.add_argument(
        "--skip-unload",
        action="store_true",
        help="Do not unload other models between runs",
    )
    parser.add_argument(
        "--cold-warm",
        action="store_true",
        help=(
            "For each model: unload, measure cold TTFT, then measure warm TTFT "
            "without unloading. Writes both runs plus a delta summary."
        ),
    )
    parser.add_argument(
        "--out",
        default="",
        help="JSON report path (default: logs/utilization_bench.json)",
    )
    args = parser.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    base = args.base_url.rstrip("/")
    ctx_values = [
        int(x.strip())
        for x in (args.compare_ctx or str(args.num_ctx)).split(",")
        if x.strip()
    ]
    if not ctx_values:
        ctx_values = [8192]

    idle = SystemSampler(ollama_base_url=base)
    for _ in range(3):
        idle.tick()
        await asyncio.sleep(0.4)

    report: dict[str, Any] = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": platform_info(),
        "idle": idle.series.summary(),
        "idle_notes": idle.series.samples[-1].notes if idle.series.samples else [],
        "cold_warm": bool(args.cold_warm),
        "num_ctx_values": ctx_values,
        "runs": [],
        "cold_warm_deltas": [],
        "ctx_recommendation": None,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Connectivity check
        try:
            tags = (await client.get(f"{base}/api/tags")).json()
            available = {m.get("name") for m in tags.get("models") or []}
        except Exception as exc:
            print(f"Cannot reach Ollama at {base}: {exc}")
            return 1

        for model in models:
            for num_ctx in ctx_values:
                print(f"\n=== {model}  num_ctx={num_ctx} ===")
                if model not in available and not any(
                    (a or "").startswith(model) for a in available
                ):
                    print(f"  SKIP: not pulled. Run: ollama pull {model}")
                    report["runs"].append(
                        {
                            "model": model,
                            "num_ctx": num_ctx,
                            "ok": False,
                            "error": "model not pulled",
                        }
                    )
                    continue

                phases = ("cold", "warm") if args.cold_warm else ("single",)
                cold_ttft: float | None = None
                warm_ttft: float | None = None
                for phase in phases:
                    if phase in {"cold", "single"} and not args.skip_unload:
                        print("  unloading other models…")
                        await _unload_all(client, base)
                        await asyncio.sleep(1.0)
                    elif phase == "warm":
                        print("  warm pass (model left resident)…")

                    sampler = SystemSampler(ollama_base_url=base)
                    sampler.tick()
                    result = await _generate_with_samples(
                        client=client,
                        base=base,
                        model=model,
                        prompt=args.prompt,
                        num_ctx=num_ctx,
                        sampler=sampler,
                        interval_s=args.interval_s,
                        max_duration_s=args.duration_s,
                    )
                    result["phase"] = phase
                    result["num_ctx"] = num_ctx
                    report["runs"].append(result)
                    print(
                        f"  [{phase}] ok={result['ok']} ttft={result['ttft_s']}s "
                        f"tok/s={result['tokens_per_s']} "
                        f"dedicated_peak_GiB="
                        f"{result['host'].get('gpu_dedicated_peak_gib')} "
                        f"ollama_vram_GiB={result['ollama_size_vram_gib']}"
                    )
                    print(f"  {result['interpretation']}")
                    if phase == "cold" and result.get("ttft_s") is not None:
                        cold_ttft = float(result["ttft_s"])
                    if phase == "warm" and result.get("ttft_s") is not None:
                        warm_ttft = float(result["ttft_s"])

                if args.cold_warm and cold_ttft is not None and warm_ttft is not None:
                    delta = {
                        "model": model,
                        "num_ctx": num_ctx,
                        "cold_ttft_s": cold_ttft,
                        "warm_ttft_s": warm_ttft,
                        "saved_s": round(cold_ttft - warm_ttft, 3),
                    }
                    report["cold_warm_deltas"].append(delta)
                    print(
                        f"  cold->warm TTFT: {cold_ttft}s -> {warm_ttft}s "
                        f"(saved {delta['saved_s']}s)"
                    )

        report["ctx_recommendation"] = _recommend_ctx(report["runs"])

    out = Path(args.out) if args.out else (ROOT / "logs" / "utilization_bench.json")
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    if report.get("ctx_recommendation"):
        try:
            print(f"ctx recommendation: {report['ctx_recommendation']}")
        except UnicodeEncodeError:
            print(
                "ctx recommendation:",
                str(report["ctx_recommendation"]).encode("ascii", "replace").decode(),
            )
    return 0


def platform_info() -> dict[str, Any]:
    import platform

    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }


def _recommend_ctx(runs: list[dict[str, Any]]) -> str | None:
    """Heuristic: bump interactive chat only if warm 7B stays comfortable."""
    by_ctx: dict[int, list[dict[str, Any]]] = {}
    for run in runs:
        if not run.get("ok"):
            continue
        ctx = int(run.get("num_ctx") or 0)
        if not ctx:
            continue
        by_ctx.setdefault(ctx, []).append(run)
    if len(by_ctx) < 2:
        return None
    # Prefer warm/single phase for peak VRAM.
    def _peak(run: dict[str, Any]) -> float:
        host = run.get("host") or {}
        dedicated = host.get("gpu_dedicated_peak_gib")
        ollama = run.get("ollama_size_vram_gib")
        vals = [float(x) for x in (dedicated, ollama) if x is not None]
        return max(vals) if vals else 0.0

    lines: list[str] = []
    for ctx in sorted(by_ctx):
        peaks = [_peak(r) for r in by_ctx[ctx] if "7b" in str(r.get("model") or "")]
        if not peaks:
            peaks = [_peak(r) for r in by_ctx[ctx]]
        if peaks:
            lines.append(f"num_ctx={ctx} peak~{max(peaks):.1f}GiB")
    # Comfortable on 12GiB: leave headroom for UI/Comfy; ~9.5GiB dedicated ceiling.
    high = max(by_ctx)
    seven = [
        _peak(r)
        for r in by_ctx[high]
        if "7b" in str(r.get("model") or "").lower()
    ]
    high_peaks = seven or [_peak(r) for r in by_ctx[high]]
    high_peak = max(high_peaks) if high_peaks else 0.0
    fourteen = [
        _peak(r)
        for r in by_ctx[high]
        if "14b" in str(r.get("model") or "").lower()
    ]
    fourteen_peak = max(fourteen) if fourteen else 0.0
    if fourteen_peak and fourteen_peak > 10.2:
        decision = (
            f"KEEP global 8192 for research headroom "
            f"(14b@{high} peak~{fourteen_peak:.1f}GiB); "
            f"7b@{high} peak~{high_peak:.1f}GiB is fine alone"
        )
    elif high_peak and high_peak <= 9.5:
        decision = (
            f"OK to set interactive num_ctx={high} "
            f"(7b peak~{high_peak:.1f}GiB <= 9.5)"
        )
    elif high_peak:
        decision = (
            f"KEEP 8192 — num_ctx={high} peak~{high_peak:.1f}GiB exceeds "
            "comfortable 9.5GiB headroom on 12GiB"
        )
    else:
        decision = "inconclusive (no VRAM peaks); keep 8192"
    return "; ".join([*lines, decision])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
