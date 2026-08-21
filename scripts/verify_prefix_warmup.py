"""Does seeding the prefix cache at startup make the first turn fast?

Shipping the whole policy and the whole tool surface makes the front of the
prompt large and constant. Constant is what the prefix cache wants, but the
first turn still has to prefill it once, and on a 12 GB AMD card that is tens of
seconds — which a user would experience as a hang on their first message.

seed_prefix_cache moves that work to startup. This measures both halves:
cold first turn without seeding, then with.

    python scripts/verify_prefix_warmup.py
"""

from __future__ import annotations

import asyncio
import time

from arelis.config import load_config
from arelis.core.bus import EventBus
from arelis.llm import build_router, prefix_warmup_for, seed_prefix_cache
from arelis.tools import build_tool_registry


async def _first_turn(router, prefix, question: str) -> float:
    """Time to a finished short reply, the way a real turn would ask."""
    messages = [*prefix.messages, {"role": "user", "content": question}]
    started = time.perf_counter()
    stream = router.provider.stream_chat(
        router.model_for(router.default_role),
        messages,
        tools=prefix.tools,
        keep_alive=router.default_keep_alive,
        options={"num_ctx": prefix.num_ctx, "num_predict": 16, "temperature": 0},
    )
    async for _kind, _payload in stream:
        pass
    return time.perf_counter() - started


async def main() -> int:
    # No flags: the point is to measure the model and window the app will really
    # use, so both come from config the same way the app reads them.
    config = load_config()
    router = build_router(config)
    tools = build_tool_registry(config)
    prefix = prefix_warmup_for(config, tools)
    assert prefix is not None, "prefix_warmup_for returned None"

    prompt_chars = sum(len(m["content"]) for m in prefix.messages)
    print(f"model={router.model_for(router.default_role)}")
    print(f"num_ctx={prefix.num_ctx:,}  tools={len(prefix.tools)}  "
          f"prefix~{prompt_chars // 4:,} tokens\n")

    # Drop the model so the first measurement is genuinely cold.
    await router.provider.unload(router.model_for(router.default_role))
    await asyncio.sleep(2.0)

    cold = await _first_turn(router, prefix, "Say ok.")
    print(f"first turn, nothing warmed:      {cold:6.1f}s")

    await router.provider.unload(router.model_for(router.default_role))
    await asyncio.sleep(2.0)

    bus = EventBus()
    warm_started = time.perf_counter()
    await router.warm_default()
    await seed_prefix_cache(bus, router, prefix)
    seeding = time.perf_counter() - warm_started
    print(f"startup warm + seed:             {seeding:6.1f}s  (user is not waiting)")

    seeded = await _first_turn(router, prefix, "Say ok.")
    print(f"first turn, prefix seeded:       {seeded:6.1f}s")

    await router.provider.close()
    print()
    if seeded < cold:
        print(f"PASS — first reply {cold - seeded:.1f}s faster ({cold:.1f}s -> {seeded:.1f}s)")
        return 0
    print("NO GAIN — check whether Ollama kept the cache slot")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
