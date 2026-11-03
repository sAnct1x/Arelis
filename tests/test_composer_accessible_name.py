"""UIA finds the composer by a fixed name, not its voice-state placeholder (v11c)."""

from __future__ import annotations

from arelis.ui.panels.conversation import ConversationStage


def test_composer_keeps_its_name_while_listening(qt_app) -> None:
    stage = ConversationStage()
    stage.conversation_btn.setChecked(True)
    stage._sync_composer_buttons()
    assert stage.input.placeholderText() != "message Arelis…"
    assert stage.input.accessibleName() == "Message Arelis"
