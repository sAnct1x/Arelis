"""The context window is sized from the card, not from one developer's card.

The shipped num_ctx spent months being argued down on a guess about warm
prefill. These tests hold the shape of the replacement: bigger cards get more
room, small cards are not handed a window that spills layers onto the CPU, and
an unreadable card falls back rather than gambling.
"""

from __future__ import annotations

from arelis.setup.catalog import CATALOG, by_tag
from arelis.setup.context import (
    _HEADROOM_GIB,
    _MAX_PINNED,
    _MIN_PINNED,
    context_window_for,
    kv_gib_per_k,
    why_window,
)
from arelis.setup.hardware import HardwareSnapshot


def _card(gb: float) -> HardwareSnapshot:
    return HardwareSnapshot(gpu_name="Test GPU", vram_bytes=int(gb * 1024**3))


def test_the_reference_card_gets_the_measured_window() -> None:
    """12 GB with the 9B measured at 7.21 GiB for 65536 — see the script."""
    assert context_window_for(by_tag("qwen3.5:9b"), _card(12.0)) == 65536


def test_a_bigger_card_is_not_capped_by_the_reference() -> None:
    small = context_window_for(by_tag("qwen3.5:9b"), _card(12.0))
    large = context_window_for(by_tag("qwen3.5:9b"), _card(24.0))
    assert large > small


def test_a_window_is_never_larger_than_the_ceiling() -> None:
    for model in CATALOG:
        assert context_window_for(model, _card(96.0)) <= _MAX_PINNED


def test_a_small_card_still_gets_room_for_the_tool_schemas() -> None:
    """The full registry is ~7,900 tokens. A window under the floor was the bug."""
    for model in CATALOG:
        for gb in (4.0, 6.0, 8.0, 12.0):
            assert context_window_for(model, _card(gb)) >= _MIN_PINNED


def test_an_unreadable_card_falls_back_instead_of_gambling() -> None:
    blind = HardwareSnapshot(gpu_name="", vram_bytes=None, ram_bytes=32 * 1024**3)
    assert context_window_for(by_tag("qwen3.5:9b"), blind) == _MIN_PINNED


def test_a_window_leaves_headroom_for_vision_and_the_desktop() -> None:
    """Weights + KV must not consume the whole card."""
    for model in CATALOG:
        for gb in (8.0, 12.0, 16.0, 24.0, 48.0):
            window = context_window_for(model, _card(gb))
            kv = kv_gib_per_k(model) * (window / 1024)
            used = float(model.download_gb) + kv
            if window > _MIN_PINNED:
                # Only the derived answers owe headroom; the floor is a
                # deliberate "too small to spill" fallback.
                assert used <= gb - _HEADROOM_GIB + 0.001, (
                    f"{model.tag} on {gb}GB: {used:.2f} GiB at {window}"
                )


def test_a_heavier_model_pays_more_per_token() -> None:
    assert kv_gib_per_k(by_tag("qwen3.5:27b")) > kv_gib_per_k(by_tag("qwen3.5:4b"))


def test_the_reason_names_the_card_and_the_window() -> None:
    text = why_window(by_tag("qwen3.5:9b"), _card(12.0))
    assert "12" in text
    assert "65,536" in text
