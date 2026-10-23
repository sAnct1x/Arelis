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
# Experts left on the CPU. Q4 stays 32. Q3 at 28 was measured at 9.96 GB
# VRAM and 21.8 tok/s.
Q4_N_CPU_MOE = 32
Q3_N_CPU_MOE = 28


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
    n_cpu_moe: int = Q4_N_CPU_MOE


CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3.6-35B-A3B-UD-Q4_K_M",
        "Qwen",
        "Recommended",
        Q4_DOWNLOAD_GB,
        Q4_MIN_VRAM_GB,
        "The usual chat model. About 22.1 GB.",
        HF_REPO,
        Q4_FILENAME,
    ),
    CatalogModel(
        "Qwen3.6-35B-A3B-UD-Q3_K_M",
        "Qwen",
        "Smaller, for less memory",
        Q3_DOWNLOAD_GB,
        Q3_MIN_VRAM_GB,
        "The same chat model in a smaller file. About 16.6 GB.",
        HF_REPO,
        Q3_FILENAME,
        Q3_N_CPU_MOE,
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
    return ram >= model.min_vram_gb + 10.0


def by_tag(tag: str) -> CatalogModel | None:
    """Row for a catalog tag or filename, or None."""
    want = (tag or "").strip()
    if not want:
        return None
    for item in CATALOG:
        if item.tag == want or item.filename == want:
            return item
    return None


def disk_needed_gb(model: CatalogModel) -> float:
    """Chat weights plus the picture file, with a little slack."""
    return model.download_gb + 0.6 + 1.0


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
