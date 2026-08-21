"""Measure the largest num_ctx that still keeps a chat model wholly in VRAM.

The shipped num_ctx used to be a number somebody was afraid of. This asks the
card instead: load the model at a candidate window, then read /api/ps and
compare size_vram against size. A model that does not fit entirely in VRAM has
spilled layers to the CPU, which costs far more than the window buys.

Run from a checkout with Ollama up:

    python scripts/measure_context_ceiling.py --model qwen3.5:9b
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

GIB = 1024**3


def _post(base: str, path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}{path}", timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _unload(base: str, model: str) -> None:
    try:
        _post(base, "/api/generate", {"model": model, "keep_alive": 0})
    except urllib.error.URLError:
        pass
    time.sleep(2.0)


def probe(base: str, model: str, num_ctx: int) -> dict:
    """Load at num_ctx, then report what the card actually holds."""
    _unload(base, model)
    started = time.perf_counter()
    _post(
        base,
        "/api/generate",
        {
            "model": model,
            "prompt": "Reply with the single word: ok",
            "stream": False,
            "keep_alive": "60s",
            "options": {"num_ctx": num_ctx, "num_predict": 4},
        },
    )
    first = time.perf_counter() - started
    ps = _get(base, "/api/ps")
    row = next(
        (m for m in ps.get("models", []) if m.get("model", "").startswith(model)),
        None,
    )
    if row is None:
        return {"num_ctx": num_ctx, "loaded": False}
    size = int(row.get("size") or 0)
    vram = int(row.get("size_vram") or 0)
    return {
        "num_ctx": num_ctx,
        "loaded": True,
        "total_gib": size / GIB,
        "vram_gib": vram / GIB,
        "fully_on_gpu": size > 0 and vram >= size,
        "cold_reply_s": first,
        "context_len": row.get("context_length"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    ap.add_argument(
        "--windows",
        default="16384,32768,65536,131072",
        help="Comma-separated num_ctx candidates, ascending.",
    )
    args = ap.parse_args()
    windows = [int(w) for w in args.windows.split(",") if w.strip()]

    print(f"model={args.model}")
    print(f"{'num_ctx':>9}  {'total GiB':>9}  {'in VRAM':>9}  {'all GPU':>7}  {'cold s':>7}")
    best = 0
    for w in windows:
        try:
            r = probe(args.base, args.model, w)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"{w:>9}  probe failed: {exc}")
            continue
        if not r.get("loaded"):
            print(f"{w:>9}  not resident after load")
            continue
        print(
            f"{w:>9}  {r['total_gib']:>9.2f}  {r['vram_gib']:>9.2f}  "
            f"{r['fully_on_gpu']!s:>7}  {r['cold_reply_s']:>7.1f}"
        )
        if r["fully_on_gpu"]:
            best = w
    _unload(args.base, args.model)
    print()
    print(f"Largest window wholly in VRAM: {best or 'none measured'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
