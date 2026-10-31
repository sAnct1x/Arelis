"""The fixed app sheet still follows a font change, such as a new language."""

from __future__ import annotations

from arelis.ui import theme
from arelis.ui.theme_tokens import FONTS


def test_app_sheet_is_rebuilt_when_the_body_font_changes() -> None:
    saved = FONTS["body"]
    try:
        first = theme.app_sheet()
        FONTS["body"] = '"Noto Sans JP", sans-serif'
        second = theme.app_sheet()
        assert second != first
        assert '"Noto Sans JP", sans-serif' in second
    finally:
        FONTS["body"] = saved
