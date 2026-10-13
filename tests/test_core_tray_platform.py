"""Core tray must not force the Windows Qt plugin on Linux or Mac."""

from __future__ import annotations

import os
import sys

import pytest

from arelis.presence.tray import apply_core_tray_platform_default


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_non_windows_does_not_default_qt_platform_to_windows(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    apply_core_tray_platform_default()
    assert os.environ.get("QT_QPA_PLATFORM") != "windows"


def test_windows_still_defaults_qt_platform_to_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    apply_core_tray_platform_default()
    assert os.environ.get("QT_QPA_PLATFORM") == "windows"
