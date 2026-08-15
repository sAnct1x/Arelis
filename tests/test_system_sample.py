"""System utilization sample helpers (no live GPU required)."""

from __future__ import annotations

from arelis.telemetry.system_sample import SampleSeries, SystemSample, _gib


def test_gib_conversion() -> None:
    assert _gib(None) is None
    assert _gib(1024**3) == 1.0


def test_sample_series_peaks() -> None:
    series = SampleSeries()
    series.add(
        SystemSample(ts=1.0, gpu_dedicated_bytes=2 * 1024**3, gpu_util_percent=10.0)
    )
    series.add(
        SystemSample(ts=2.0, gpu_dedicated_bytes=4 * 1024**3, gpu_util_percent=40.0)
    )
    series.add(SystemSample(ts=3.0, gpu_dedicated_bytes=3 * 1024**3, gpu_util_percent=20.0))
    summary = series.summary()
    assert summary["gpu_dedicated_peak_gib"] == 4.0
    assert summary["gpu_util_peak_percent"] == 40.0
    assert summary["vram_fraction_of_12gib"] == round(4 / 12, 3)
