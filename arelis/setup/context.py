"""How large a context window this card can actually hold.

The shipped ``ollama.num_ctx`` is one number measured on one card. A stranger
with 8 GB should not inherit it, and a stranger with 24 GB should not be capped
by it. Setup already knows the card and the chosen model, so it can pin a window
the same way it pins the tag.

The per-token cost of the KV cache is measured, not guessed. On the reference
card with ``qwen3.5:9b`` (see scripts/measure_context_ceiling.py):

    16384 → 5.62 GiB      65536 → 7.21 GiB
    32768 → 6.15 GiB     131072 → 9.12 GiB

That is ~34 KiB per token of window, on top of ~5.1 GiB of resident weights.
Scaling that cost by download size is a first-order approximation across the
family — the KV cache actually grows with layers and KV heads rather than with
file size — so the result is deliberately rounded down to a power of two and
capped. Anyone who wants the true ceiling for a new tag should run the script.
"""

from __future__ import annotations

from arelis.setup.catalog import CatalogModel
from arelis.setup.hardware import HardwareSnapshot

# Measured on qwen3.5:9b: GiB of KV cache per 1024 tokens of window.
_KV_GIB_PER_K_AT_REFERENCE = 0.033
# The model those numbers came from, as a download size.
_REFERENCE_DOWNLOAD_GB = 6.6

# Left for the desktop compositor, the fallback vision model, and Comfy. Vision
# unloads chat before it runs, but the browser and the OS do not.
_HEADROOM_GIB = 2.5

# Windows we are willing to pin, largest first. Powers of two because that is
# what every other num_ctx in the wild uses, and a round number is easier to
# recognise in a bug report than 58,000.
_LADDER = (131072, 98304, 65536, 49152, 32768, 24576, 16384, 12288, 8192)

# Never pin more than this from a guess, however large the card. The gain past
# here is theoretical for a desktop assistant and the cost is real.
_MAX_PINNED = 131072
# The floor, and not a cautious one — a window under this does not hold the
# prompt plus room to talk. Persona (~905) + telegraph policy (~455) + skinny
# schemas for 39 tools (~4,105) is about 5,500 tokens before conversation.
# 16384 would fit the prefix but starve history; 32768 leaves ~27k for the
# reply. Ollama still drops overflow from the front (the persona).
#
# This is a floor rather than a compromise because a card too small for 32768 is
# too small for the weights: the 9B measures 5.62 GiB at 16384 and 6.15 GiB at
# 32768, so anything that can load the model at all can afford the difference.
# tests/test_prompt_fits_window.py holds the arithmetic.
_MIN_PINNED = 32768


def kv_gib_per_k(model: CatalogModel) -> float:
    """Approximate GiB of KV cache per 1024 tokens for this tag."""
    download = max(0.5, float(model.download_gb))
    return _KV_GIB_PER_K_AT_REFERENCE * (download / _REFERENCE_DOWNLOAD_GB)


def context_window_for(model: CatalogModel, hardware: HardwareSnapshot) -> int:
    """Largest window from the ladder whose KV cache still fits beside weights.

    Falls back to the shipped floor when the card is unreadable, because a
    cautious window that fits is always better than a large one that spills
    layers onto the CPU.
    """
    vram = hardware.vram_gb
    if vram is None:
        # No dedicated card: weights are coming out of system RAM already and
        # the window is not what will make that machine slow.
        return _MIN_PINNED
    spare = float(vram) - float(model.download_gb) - _HEADROOM_GIB
    if spare <= 0:
        return _MIN_PINNED
    per_k = kv_gib_per_k(model)
    if per_k <= 0:
        return _MIN_PINNED
    affordable = int((spare / per_k) * 1024)
    for window in _LADDER:
        if window > _MAX_PINNED:
            continue
        if window <= affordable:
            return max(_MIN_PINNED, window)
    return _MIN_PINNED


def why_window(model: CatalogModel, hardware: HardwareSnapshot) -> str:
    """One sentence for the setup log. No jargon a friend has to decode."""
    window = context_window_for(model, hardware)
    vram = hardware.vram_gb
    if vram is None:
        return (
            f"No dedicated graphics card was read, so her memory for one "
            f"conversation is set to {window:,} tokens."
        )
    return (
        f"About {vram:g} GB of graphics memory holds {model.title} plus "
        f"{window:,} tokens of conversation without falling back to the CPU."
    )
