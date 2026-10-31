"""In zh the caption buttons and Attach are translated, like Close and Send."""

from arelis import i18n


def test_zh_translates_caption_buttons_and_attach(qapp):
    from arelis.ui.chrome import TitleBar
    from arelis.ui.panels.conversation import ConversationStage

    bar = TitleBar()
    stage = ConversationStage(default_role="fast")
    try:
        i18n.set_ui_language("zh")
        i18n.localize(bar)
        i18n.localize(stage)
        assert bar.min_btn.accessibleName() == "最小化"
        assert bar.max_btn.accessibleName() == "最大化"
        assert stage.attach_btn.accessibleName() == "附件"
    finally:
        i18n.set_ui_language("en")
        i18n.localize(bar)
        i18n.localize(stage)
        bar.deleteLater()
        stage.deleteLater()
