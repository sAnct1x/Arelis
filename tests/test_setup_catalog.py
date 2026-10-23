"""Setup catalog is two Unsloth Qwen3.6 GGUF rows, not Ollama tags."""

from __future__ import annotations

import re

from arelis.setup.catalog import CATALOG, recommend
from arelis.setup.hardware import HardwareSnapshot

# Same shape the retired engine used: name:tag. Catalog rows must not match.
_OLLAMA_TAG = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._+-]*:[A-Za-z0-9][A-Za-z0-9._+-]*"
)


def _machine(*, vram_gb: float) -> HardwareSnapshot:
    return HardwareSnapshot(vram_bytes=int(vram_gb * (1024**3)))


def test_recommend_q4_on_big_machine_q3_on_small_and_no_ollama_tags() -> None:
    big = recommend(_machine(vram_gb=24.0))
    small = recommend(_machine(vram_gb=8.0))
    assert "Q4_K_M" in big.tag
    assert "Q3_K_M" in small.tag
    for item in CATALOG:
        blob = " ".join(
            (
                item.tag,
                item.family,
                item.title,
                item.summary,
                item.hf_repo,
                item.filename,
            )
        )
        assert _OLLAMA_TAG.search(blob) is None
