"""Free the 12GB card before a research/code load.

14B needs ~9.6 GiB. A leftover 7B, ComfyUI, or a second 14B JSON-fallback
load spills into shared GPU memory and locks the machine. Neighbors we own
are stopped here; Ollama eviction lives on the router.
"""

from __future__ import annotations

import logging
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType

log = logging.getLogger(__name__)

# After /api/ps is empty, AMD/Windows can still hold the old allocation.
# One Get-Counter sample: if dedicated is still this high with no Ollama
# model resident, something else is on the card (Comfy, Chrome, a game).
_HEAVY_BLOCK_DEDICATED_BYTES = 5 * 1024**3


async def free_gpu_neighbors(config: dict[str, Any], bus: EventBus | None) -> None:
    """Stop Arelis-owned GPU neighbors (Comfy) before loading 14B."""
    try:
        from arelis.tools.comfy_lifecycle import comfy_is_healthy, stop_comfy
    except Exception:
        return
    image = (config.get("tools") or {}).get("image") or {}
    url = str(image.get("comfy_url") or "http://127.0.0.1:8188")
    stopped = False
    try:
        stopped = bool(stop_comfy())
    except Exception:
        log.warning("Could not stop ComfyUI before a heavy model load", exc_info=True)
    if bus is not None and stopped:
        await bus.publish(
            Event(
                EventType.STATUS,
                {"message": "Stopped ComfyUI so the research model can use the GPU."},
            )
        )
        return
    try:
        still = bool(comfy_is_healthy(url, timeout_s=1.0))
    except Exception:
        still = False
    if still and bus is not None:
        await bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        "ComfyUI is still using the GPU. Close it if the "
                        "research model fails to load."
                    )
                },
            )
        )


def host_dedicated_bytes() -> int | None:
    """Best-effort Windows dedicated VRAM. None when counters are unavailable."""
    try:
        from arelis.telemetry.system_sample import _sample_gpu_windows
    except Exception:
        return None
    try:
        dedicated, _shared, _util, _name, _notes = _sample_gpu_windows()
    except Exception:
        return None
    return dedicated


def host_vram_blocks_heavy(dedicated_bytes: int | None) -> str | None:
    """Return a refusal reason when the card is too full to start 14B."""
    if dedicated_bytes is None:
        return None
    if dedicated_bytes <= _HEAVY_BLOCK_DEDICATED_BYTES:
        return None
    gib = dedicated_bytes / (1024**3)
    return (
        f"GPU still has {gib:.1f} GB dedicated in use after unloading Ollama. "
        "Close ComfyUI, games, or extra Chrome, then try again."
    )
