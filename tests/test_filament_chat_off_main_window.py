"""In Filament the transcript exists only on the chat tile: a reply streamed with the tile
closed never shows (or repaints) in the main window, and the tile opens on it."""

from __future__ import annotations

from PySide6.QtTest import QTest


def test_a_reply_streamed_with_the_tile_closed_stays_off_the_main_window(
    arelis_window, qt_app
) -> None:
    w = arelis_window(
        {
            "ui": {
                "default_width": 900,
                "default_height": 650,
                "theme": "night",
                "filament_ack": True,
            }
        }
    )
    w.show()
    qt_app.processEvents()
    w._choose_theme("filament", True)
    QTest.qWait(200)
    chat = w.conversation.chat
    chat.add_user("hello")
    chat.begin_assistant()
    for tok in ("Part ", "one ", "streams."):
        chat.append_delta(tok)
        qt_app.processEvents()
    QTest.qWait(300)  # the stream flushes on a timer
    assert not chat.view.isVisible()
    assert "streams." in chat.view.toPlainText()
    w.filament._filament_set_chat_open(True)
    QTest.qWait(300)
    assert chat.view.isVisible() and chat.window() is not w
