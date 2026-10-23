"""The llama.cpp chat models a stranger may actually pick.

Arelis 0.3.3 runs Unsloth Qwen3.6 35B-A3B GGUF through llama.cpp. Two
rows: UD-Q4_K_M (the default, the file the loader already looks for) and
UD-Q3_K_M (low VRAM and low RAM fallback). No Ollama name:tag list. No
Gemma. No DeepSeek. Vision stays on the same 35B weights.
"""

from __future__ import annotations

from dataclasses import dataclass

from arelis.setup.hardware import HardwareSnapshot

EMBED_TAG = "nomic-embed-text"

HF_REPO = "unsloth/Qwen3.6-35B-A3B-GGUF"
Q4_FILENAME = "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
Q3_FILENAME = "Qwen3.6-35B-A3B-UD-Q3_K_M.gguf"
# Hugging Face main, bytes: Q4 22134528992, Q3 16600710112.
Q4_DOWNLOAD_GB = 22.1
Q3_DOWNLOAD_GB = 16.6
# GPU floor is the card we actually run with MoE offload, not the GGUF size.
# Q4 ships on a 12 GB card. Q3 is the smaller-card fallback.
Q4_MIN_VRAM_GB = 12.0
Q3_MIN_VRAM_GB = 8.0
# System RAM has to hold the GGUF plus the OS.
_RAM_HEADROOM_GB = 10.0


@dataclass(frozen=True)
class CatalogModel:
    tag: str
    family: str
    title: str
    download_gb: float
    min_vram_gb: float
    summary: str
    hf_repo: str
    filename: str


CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.6-35B-A3B-UD-Q4_K_M",
        "Qwen",
        "Qwen3.6 35B-A3B Q4_K_M",
        Q4_DOWNLOAD_GB,
        Q4_MIN_VRAM_GB,
        "Default. Unsloth UD-Q4_K_M GGUF. The file llama.cpp already looks for.",
        HF_REPO,
        Q4_FILENAME,
    ),
    CatalogModel(
        "Qwen3.6-35B-A3B-UD-Q3_K_M",
        "Qwen",
        "Qwen3.6 35B-A3B Q3_K_M",
        Q3_DOWNLOAD_GB,
        Q3_MIN_VRAM_GB,
        "Low VRAM and low RAM fallback. Same model, smaller Unsloth GGUF.",
        HF_REPO,
        Q3_FILENAME,
    ),
)


def _row(token: str) -> CatalogModel:
    for item in CATALOG:
        if token in item.tag:
            return item
    raise RuntimeError(f"catalog is missing {token}")


def fits(model: CatalogModel, hardware: HardwareSnapshot) -> bool:
    """True when we will recommend this size without a slow-machine warning."""
    vram = hardware.vram_gb
    if vram is not None:
        return vram + 0.05 >= model.min_vram_gb
    ram = hardware.ram_gb
    if ram is None:
        return False
    # No card in sight: system RAM has to hold the GGUF plus Windows.
    return ram >= model.download_gb + _RAM_HEADROOM_GB


def recommend(hardware: HardwareSnapshot) -> CatalogModel:
    """Q4_K_M when the machine fits it, otherwise the Q3_K_M fallback."""
    q4 = _row("Q4_K_M")
    q3 = _row("Q3_K_M")
    if fits(q4, hardware):
        return q4
    return q3


def why(model: CatalogModel, hardware: HardwareSnapshot) -> str:
    """Two or three sentences. No jargon a friend has to decode."""
    bits: list[str] = []
    bits.append(hardware.plain_card())
    bits.append(model.summary)
    if "Q4_K_M" in model.tag and (hardware.vram_gb or 0) >= Q4_MIN_VRAM_GB:
        bits.append(
            "This is the size we run every day on a similar 12 GB card. "
            "Tools, search, and files work without crowding the rest of Windows."
        )
    elif not fits(model, hardware):
        bits.append(
            "This is larger than what we saw on this PC. It may still run from "
            "system memory, but it will feel slow, and the machine may hitch."
        )
    elif model.tag == recommend(hardware).tag:
        bits.append("That is why this is the recommendation, not a guess from a chart.")
    bits.append(f"About {model.download_gb:.1f} GB to download, once, onto this PC.")
    return " ".join(bits)
