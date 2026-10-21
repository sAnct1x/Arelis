"""Ask llama-server once per candidate and print the slot window.

The process -c is the window. This does not resize it per request, and it
does not read graphics memory. A model that spills to the CPU is a launch
flag problem, not something this script can change mid-run.

Run from a checkout with llama-server up:

    python scripts/measure_context_ceiling.py --model qwen3.5:9b
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


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
    del base, model


def probe(base: str, model: str, num_ctx: int) -> dict:
    """Ask llama-server once and read the slot window.

    The process -c is the window. This does not resize it per request.
    """
    started = time.perf_counter()
    _post(
        base,
        "/v1/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "user", "content": "Reply with the single word: ok"}
            ],
            "stream": False,
            "max_tokens": 4,
        },
    )
    first = time.perf_counter() - started
    slots = _get(base, "/slots")
    rows = slots if isinstance(slots, list) else []
    n_ctx = rows[0].get("n_ctx") if rows else None
    return {
        "num_ctx": num_ctx,
        "loaded": True,
        "total_gib": 0.0,
        "vram_gib": 0.0,
        "fully_on_gpu": bool(n_ctx),
        "cold_reply_s": first,
        "context_len": n_ctx,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--base", default="http://127.0.0.1:8080")
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
