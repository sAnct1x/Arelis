"""The models a stranger may actually pick.

No toys (0.8B, 1.5B, 2B). No Ollama cloud tags. No 671B. One chat model at a
time: whatever they confirm is both fast and research. Vision stays the existing
one-shot tag and is pulled later, the first time they look at a picture.

Sizes are the ollama.com download (Q4-class, August 2026). min_vram_gb is the
card we will auto-recommend on — download plus a little room for context, not
a guarantee the model is fast.
"""

from __future__ import annotations

from dataclasses import dataclass

from arelis.setup.hardware import HardwareSnapshot

EMBED_TAG = "nomic-embed-text"


@dataclass(frozen=True)
class CatalogModel:
    tag: str
    family: str
    title: str
    download_gb: float
    min_vram_gb: float
    summary: str


CATALOG: tuple[CatalogModel, ...] = (
    CatalogModel(
        "qwen3.5:4b",
        "Qwen",
        "Qwen 3.5 · 4B",
        3.4,
        6.0,
        "Small. Fits a modest laptop. She will be slower, and hard asks will be simpler.",
    ),
    CatalogModel(
        "qwen3.5:9b",
        "Qwen",
        "Qwen 3.5 · 9B",
        6.6,
        8.0,
        "Balanced. The daily driver we actually run on a 12 GB card.",
    ),
    CatalogModel(
        "qwen3.5:27b",
        "Qwen",
        "Qwen 3.5 · 27B",
        17.0,
        20.0,
        "Strong. Needs a 24 GB-class card. Smarter; a longer download.",
    ),
    CatalogModel(
        "qwen3.5:35b",
        "Qwen",
        "Qwen 3.5 · 35B",
        24.0,
        28.0,
        "Very strong. High-end desktop or a 32 GB workstation.",
    ),
    CatalogModel(
        "gemma4:12b",
        "Gemma",
        "Gemma 4 · 12B",
        7.6,
        11.0,
        "Google's mid size. Sees pictures. Can think for a long time on tool-heavy turns.",
    ),
    CatalogModel(
        "gemma4:26b",
        "Gemma",
        "Gemma 4 · 26B",
        18.0,
        22.0,
        "Google, larger. Mixture-of-experts, so it moves better than a dense 26B.",
    ),
    CatalogModel(
        "gemma4:31b",
        "Gemma",
        "Gemma 4 · 31B",
        20.0,
        24.0,
        "The biggest local Gemma. 24 GB-class card or better.",
    ),
    CatalogModel(
        "deepseek-r1:8b",
        "DeepSeek",
        "DeepSeek R1 · 8B",
        5.2,
        8.0,
        "Reasoning. Good at math and careful think. Text only — pictures use a separate look.",
    ),
    CatalogModel(
        "deepseek-r1:14b",
        "DeepSeek",
        "DeepSeek R1 · 14B",
        9.0,
        12.0,
        "Heavier reasoning. Tight on a 12 GB card; comfortable on 16 GB.",
    ),
    CatalogModel(
        "deepseek-r1:32b",
        "DeepSeek",
        "DeepSeek R1 · 32B",
        20.0,
        24.0,
        "Serious reasoner. Needs a 24 GB-class card.",
    ),
    CatalogModel(
        "deepseek-r1:70b",
        "DeepSeek",
        "DeepSeek R1 · 70B",
        43.0,
        48.0,
        "The largest DeepSeek most people can own. Long download. Dual-GPU or 48 GB+.",
    ),
)


def by_tag(tag: str) -> CatalogModel | None:
    want = (tag or "").strip()
    for item in CATALOG:
        if item.tag == want:
            return item
    return None


def family_groups() -> list[tuple[str, tuple[CatalogModel, ...]]]:
    """Picker order: Qwen, Gemma, DeepSeek."""
    order = ("Qwen", "Gemma", "DeepSeek")
    return [(name, tuple(m for m in CATALOG if m.family == name)) for name in order]


def fits(model: CatalogModel, hardware: HardwareSnapshot) -> bool:
    """True when we will recommend this size without a slow-machine warning."""
    vram = hardware.vram_gb
    if vram is not None:
        return vram + 0.05 >= model.min_vram_gb
    ram = hardware.ram_gb
    if ram is None:
        return model.tag == "qwen3.5:4b"
    # No card in sight: system RAM has to hold the weights plus Windows.
    return ram >= model.min_vram_gb + 10.0


def recommend(hardware: HardwareSnapshot) -> CatalogModel:
    """Largest Qwen 3.5 that fits. Qwen is the default family on purpose.

    Gemma 4 12B is in the list but never auto-picked: on a 12 GB card here it
    sat thinking for minutes on a two-tool turn. DeepSeek is opt-in reasoning.
    With no dedicated card, stay on 4B / 9B even if system RAM could hold 27B —
    that machine would crawl.
    """
    qwen = [m for m in CATALOG if m.family == "Qwen"]
    if hardware.vram_gb is None:
        cpu = [
            m
            for m in qwen
            if m.tag in {"qwen3.5:4b", "qwen3.5:9b"} and fits(m, hardware)
        ]
        if cpu:
            return max(cpu, key=lambda m: m.download_gb)
        return qwen[0]
    fitting = [m for m in qwen if fits(m, hardware)]
    if fitting:
        return max(fitting, key=lambda m: m.download_gb)
    return qwen[0]


def why(model: CatalogModel, hardware: HardwareSnapshot) -> str:
    """Two or three sentences. No jargon a friend has to decode."""
    bits: list[str] = []
    card = hardware.plain_card()
    bits.append(card)
    bits.append(model.summary)
    if model.tag == "qwen3.5:9b" and (hardware.vram_gb or 0) >= 8:
        bits.append(
            "This is the size we run every day on a similar 12 GB card. "
            "Tools, search, and files work without crowding the rest of Windows."
        )
    elif not fits(model, hardware):
        bits.append(
            "This is larger than what we saw on this PC. It may still run from "
            "system memory, but it will feel slow, and the machine may hitch."
        )
    elif model.family == "Qwen" and model.tag == recommend(hardware).tag:
        bits.append("That is why this is the recommendation, not a guess from a chart.")
    bits.append(f"About {model.download_gb:.1f} GB to download, once, onto this PC.")
    return " ".join(bits)


def disk_needed_gb(model: CatalogModel) -> float:
    """Chat weights plus the small recall model, with a little slack."""
    return model.download_gb + 0.4 + 1.0
