"""#263: a window and its caption hover collected together must not raise."""

from __future__ import annotations

import gc
import sys

from PySide6.QtWidgets import QWidget

from arelis.ui.caption_fade import CaptionButton, watch_caption


def test_a_collected_window_does_not_reach_a_cleared_hover(qt_app, monkeypatch) -> None:
    raised: list[BaseException] = []
    monkeypatch.setattr(sys, "excepthook", lambda _t, err, _tb: raised.append(err))
    gc.disable()
    try:
        for _ in range(3):
            host = QWidget()
            # The window keeps its hover and the hover keeps the window: a cycle.
            host.hover = watch_caption(host, CaptionButton(host))
            host.show()
            qt_app.processEvents()
            del host
        gc.collect()
        qt_app.processEvents()
    finally:
        gc.enable()
    assert raised == []
