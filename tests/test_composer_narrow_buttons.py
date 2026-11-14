"""At a narrow chat width, composer text must not cover the clear or attach buttons."""

from __future__ import annotations

from PySide6.QtTest import QTest

from arelis.ui.panels.conversation import ConversationStage


def test_long_composer_text_does_not_cover_buttons_at_380px(qt_app) -> None:
    stage = ConversationStage(default_role="fast")
    try:
        # The row's size hint is wider than 380, but a window can still be
        # squeezed to that width. resize() alone would snap up to the hint.
        stage.setMinimumWidth(0)
        stage.setFixedWidth(380)
        stage.show()
        stage.chat.add_user("hello")
        stage.set_idle_mode(False)
        stage._place_composer(False)
        stage.set_voice_available(True, "")
        for btn in (stage.mic_btn, stage.conversation_btn):
            btn.show()
        stage.input.setText(
            "please make a picture of a red fox in a snowy forest at dusk"
        )
        stage._sync_composer_buttons()
        qt_app.processEvents()
        stage.setFixedWidth(380)
        QTest.qWait(50)
        qt_app.processEvents()

        assert stage.clear_btn.isVisible()
        assert stage.attach_btn.isVisible()
        field = stage.input.geometry()
        host = stage._composer.rect()
        for btn in (stage.clear_btn, stage.attach_btn, stage.send_btn):
            assert btn.isVisible()
            geo = btn.geometry()
            assert field.intersected(geo).isEmpty()
            assert host.contains(geo)
        assert field.right() <= stage.clear_btn.geometry().left()
    finally:
        stage.hide()
        stage.deleteLater()
