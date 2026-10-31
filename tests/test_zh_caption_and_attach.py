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


def test_night_top_bar_server_and_house_follow_chinese(arelis_window) -> None:
    """'server' and 'house · 2' are set after the walk, so they translate themselves."""
    from arelis.presence.readiness import ChipLevel, ReadinessChip, ReadinessSnapshot

    window = arelis_window()
    strip = window.readiness_strip
    strip.apply(
        ReadinessSnapshot(
            chips=(
                ReadinessChip("server", "Server", ChipLevel.OK, "up"),
                ReadinessChip("models", "Models", ChipLevel.WARN, "x"),
                ReadinessChip("role", "Role", ChipLevel.WARN, "y"),
            )
        )
    )
    try:
        i18n.apply_language(window, "zh")
        assert strip._chips["server"].text() == "服务器"
        assert strip.systems_btn.text() == "家 · 2 ▾"
    finally:
        i18n.apply_language(window, "en")
    assert strip.systems_btn.text() == "house · 2 ▾"
