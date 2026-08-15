"""Host / GPU utilization probes (benchmarking, not the chat turn timer)."""

from arelis.telemetry.system_sample import SystemSample, sample_system

__all__ = ["SystemSample", "sample_system"]
