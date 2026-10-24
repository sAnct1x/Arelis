"""Global pytest fixtures isolating all Sentinel disk writes to temporary test directories."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from sentinel.paths import set_runtime_root


@pytest.fixture(autouse=True)
def _isolate_sentinel_runtime_dirs(tmp_path: Path) -> Iterator[None]:
    """Ensure pytest never writes test logs, harvests, quarantines, or preferences into live data/."""
    set_runtime_root(tmp_path)
    try:
        yield
    finally:
        set_runtime_root(None)
