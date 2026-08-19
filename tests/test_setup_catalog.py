"""Model catalog: no toys, one recommended Qwen that fits the card."""

from __future__ import annotations

from arelis.setup.catalog import CATALOG, by_tag, recommend, why
from arelis.setup.engine import already_pulled, parse_pull_status
from arelis.setup.hardware import HardwareSnapshot


def _hw(*, vram_gb: float | None, ram_gb: float | None = 32.0, name: str = "AMD Radeon") -> HardwareSnapshot:
    vram = int(vram_gb * 1024**3) if vram_gb is not None else None
    ram = int(ram_gb * 1024**3) if ram_gb is not None else None
    return HardwareSnapshot(gpu_name=name, vram_bytes=vram, ram_bytes=ram)


def test_no_toys_in_the_catalog() -> None:
    tags = {m.tag for m in CATALOG}
    for banned in (
        "qwen3.5:0.8b",
        "qwen3.5:2b",
        "deepseek-r1:1.5b",
        "deepseek-r1:671b",
        "llama3.2:1b",
    ):
        assert banned not in tags
    assert all("cloud" not in m.tag for m in CATALOG)


def test_only_known_families() -> None:
    assert {m.family for m in CATALOG} == {"Qwen", "Gemma", "DeepSeek"}


def test_twelve_gb_gets_the_measured_daily_driver() -> None:
    picked = recommend(_hw(vram_gb=12.0))
    assert picked.tag == "qwen3.5:9b"


def test_eight_gb_still_gets_nine_b() -> None:
    assert recommend(_hw(vram_gb=8.0)).tag == "qwen3.5:9b"


def test_no_card_does_not_get_a_27b() -> None:
    """RAM-fit would otherwise pick 27B on a 32 GB CPU-only box."""
    assert recommend(_hw(vram_gb=None, ram_gb=32.0)).tag == "qwen3.5:9b"


def test_modest_ram_no_card_gets_four_b() -> None:
    assert recommend(_hw(vram_gb=None, ram_gb=16.0)).tag == "qwen3.5:4b"


def test_modest_laptop_gets_four_b() -> None:
    assert recommend(_hw(vram_gb=7.0)).tag == "qwen3.5:4b"


def test_twenty_four_gb_gets_twenty_seven_b() -> None:
    assert recommend(_hw(vram_gb=24.0)).tag == "qwen3.5:27b"


def test_high_end_gets_thirty_five_b() -> None:
    assert recommend(_hw(vram_gb=32.0)).tag == "qwen3.5:35b"


def test_gemma_is_never_the_auto_pick() -> None:
    for gb in (8, 12, 16, 24, 32, 48):
        assert recommend(_hw(vram_gb=float(gb))).family == "Qwen"


def test_why_names_the_card_and_the_download() -> None:
    hw = _hw(vram_gb=12.0, name="AMD Radeon RX 7600")
    model = by_tag("qwen3.5:9b")
    assert model is not None
    text = why(model, hw)
    assert "12" in text
    assert "6.6" in text
    assert "daily" in text.lower() or "12 GB" in text


def test_too_big_a_pick_is_called_slow() -> None:
    hw = _hw(vram_gb=8.0)
    model = by_tag("qwen3.5:27b")
    assert model is not None
    text = why(model, hw)
    assert "slow" in text.lower()


def test_plain_card_is_a_sentence() -> None:
    hw = _hw(vram_gb=12.0, name="AMD Radeon RX 7600")
    text = hw.plain_card()
    assert "12" in text
    assert "7600" in text


def test_already_pulled_reads_ollama_tags(monkeypatch) -> None:
    import httpx

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"models": [{"name": "qwen3.5:9b"}]}

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args) -> bool:
            return False

        def get(self, url: str) -> _Resp:
            assert "/api/tags" in url
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    assert already_pulled("qwen3.5:9b")
    assert not already_pulled("qwen3.5:27b")


def test_pull_status_reads_ollama_bytes() -> None:
    status, done, total = parse_pull_status(
        {"status": "downloading", "completed": 50, "total": 100}
    )
    assert status == "downloading"
    assert done == 50
    assert total == 100


def test_pull_status_survives_missing_counts() -> None:
    status, done, total = parse_pull_status({"status": "success"})
    assert status == "success"
    assert done == 0
    assert total == 0
