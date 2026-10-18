"""Caption chrome fade. One case: an event during construction."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget

from arelis.ui.caption_fade import CaptionButton, CaptionHover


def test_caption_hover_event_during_construction(qt_app, monkeypatch) -> None:
    """Show delivered as soon as the QObject exists must not throw.

    Parenting happens inside QObject.__init__, before CaptionHover.__init__
    continues. Qt can run eventFilter from that call.
    """
    host = QWidget()
    button = CaptionButton()
    orig_init = QObject.__init__

    def init_and_deliver(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        if isinstance(self, CaptionHover):
            self.eventFilter(host, QEvent(QEvent.Type.Show))

    monkeypatch.setattr(QObject, "__init__", init_and_deliver)
    try:
        hover = CaptionHover(host, (button,))
        hover.eventFilter(host, QEvent(QEvent.Type.Hide))
        assert hover._host is host
    finally:
        button.deleteLater()
        host.deleteLater()
        qt_app.processEvents()
