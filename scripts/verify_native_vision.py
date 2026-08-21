"""Prove the chat model can see, against a live Ollama.

Draws a shape nobody could describe by luck, sends it through ModelRouter the
way the vision tool does, and reports which tag answered plus how long it took.
Run from a checkout with Ollama up:

    python scripts/verify_native_vision.py
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import time

from PIL import Image, ImageDraw

from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter


def _test_image() -> str:
    """A blue triangle above two orange squares, on white. Base64 PNG."""
    img = Image.new("RGB", (320, 320), "white")
    d = ImageDraw.Draw(img)
    d.polygon([(160, 30), (250, 150), (70, 150)], fill="#1f4fd8")
    d.rectangle([60, 190, 140, 270], fill="#f08a24")
    d.rectangle([180, 190, 260, 270], fill="#f08a24")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    args = ap.parse_args()

    provider = OllamaProvider(base_url=args.base)
    caps = await provider.capabilities(args.model)
    print(f"{args.model} capabilities: {', '.join(sorted(caps)) or '(unknown)'}")
    print(f"sees_images: {await provider.sees_images(args.model)}")

    router = ModelRouter(
        provider,
        {"fast": args.model, "research": args.model, "vision": "qwen2.5vl:3b"},
        options={"num_ctx": 65536},
    )
    router.active_model = args.model
    router.active_role = "fast"

    started = time.perf_counter()
    answer = await router.run_vision(
        "What shapes and colours are in this image? Answer in one sentence.",
        [_test_image()],
        num_ctx=4096,
    )
    elapsed = time.perf_counter() - started
    print(f"\nanswered in {elapsed:.1f}s:\n{answer}\n")

    lowered = answer.lower()
    hits = [w for w in ("triangle", "square", "blue", "orange") if w in lowered]
    print(f"expected features found: {hits}")
    resident = await provider.running_models()
    print(f"resident now: {resident}")
    ok = len(hits) >= 3 and any(args.model.split(":")[0] in r for r in resident)
    print("\nPASS" if ok else "\nCHECK THE ANSWER ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
