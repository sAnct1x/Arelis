from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

from arelis.paths import cache_dir, ensure
from arelis.ui import theme_tokens as _tokens
from arelis.ui.theme_qss import dock_tab_bar_qss, stylesheet
from arelis.ui.theme_tokens import (
    BLOOM,
    COLORS,
    DEFAULT_THEME,
    FILAMENT,
    FONT_PX,
    FONTS,
    GLASS,
    HAIRLINE,
    METRICS,
    PLATE,
    THEME_CHOICES,
    THEME_IDS,
    TYPE,
    active_theme,
    resolve_theme_id,
    theme_from_config,
)

__all__ = [
    "BLOOM",
    "COLORS",
    "DEFAULT_THEME",
    "FILAMENT",
    "FONTS",
    "FONT_PX",
    "GLASS",
    "HAIRLINE",
    "METRICS",
    "PLATE",
    "THEME_CHOICES",
    "THEME_IDS",
    "TYPE",
    "active_theme",
    "app_font",
    "apply_theme",
    "color",
    "dock_tab_bar_qss",
    "load_fonts",
    "polish_combo_popup",
    "qt_font_directory",
    "resolve_theme_id",
    "stylesheet",
    "theme_from_config",
]

log = logging.getLogger(__name__)


def apply_theme(theme_id: str | None) -> str:
    """Install a palette into the live token dicts. Painters that call
    color() / COLORS / FILAMENT / GLASS / PLATE follow without a rewrite.
    """
    resolved = resolve_theme_id(theme_id)
    _tokens._install_palette(resolved)
    _tokens._ACTIVE_THEME = resolved
    from arelis.tools.policy import set_confirm_mode

    set_confirm_mode("voice" if resolved == "filament" else "card")
    return resolved


_FONT_DIR = Path(__file__).resolve().parent / "fonts"


def qt_font_directory() -> Path:
    """An existing, empty directory to point QT_QPA_FONTDIR at.

    Qt's basic font database -- the one behind the offscreen and minimal platform
    plugins, which is how the test suite runs -- warns when the directory it is
    told to scan does not exist. The typefaces this application uses are
    registered from the package with addApplicationFont in load_fonts() below, so
    nothing needs to be found by scanning: the directory has to exist and it has
    to be empty, and that is the whole requirement.

    It is here rather than inline at the call site because of where it used to
    point. It was ``Path(__file__).resolve().parents[1] / "_qt_fonts"`` -- inside
    the package -- which works in a checkout, is silently created on every launch,
    and once installed is a directory a standard user may not write to and an
    update deletes. The mkdir was unguarded and ran before the QApplication
    existed, so the failure would have been a program that never drew a window.
    """
    return ensure(cache_dir() / "qt-fonts")


def load_fonts() -> dict[str, str]:
    families = {
        "display": "Segoe UI",
        "body": "Segoe UI",
        "mono": "Consolas",
    }
    # Orbit prefers Zen Kaku / Space Mono when vendored; otherwise IBM Plex
    # with the same tracking in the stylesheet.
    preferred = [
        ("ZenKakuGothicNew-Regular.ttf", "body"),
        ("ZenKakuGothicNew-Light.ttf", "display"),
        ("SpaceMono-Regular.ttf", "mono"),
    ]
    fallback = [
        ("IBMPlexSans-Regular.ttf", "body"),
        ("IBMPlexSans-SemiBold.ttf", "display"),
        ("IBMPlexMono-Regular.ttf", "mono"),
    ]
    filled: set[str] = set()
    missing_required: list[str] = []
    for filename, key in preferred + fallback:
        if key in filled:
            continue
        path = _FONT_DIR / filename
        optional = filename.startswith("Zen") or filename.startswith("Space")
        if not path.exists():
            if not optional:
                missing_required.append(filename)
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            if not optional:
                missing_required.append(filename)
            continue
        names = QFontDatabase.applicationFontFamilies(font_id)
        if names:
            families[key] = names[0]
            filled.add(key)
            if key == "body" and "display" not in filled:
                families["display"] = names[0]
    if missing_required and "body" not in filled:
        log.warning(
            "UI fonts missing or unloadable under %s (%s); falling back to system type.",
            _FONT_DIR,
            ", ".join(missing_required),
        )
    FONTS["display"] = f'"{families["display"]}", "Segoe UI Semibold", "Segoe UI", sans-serif'
    FONTS["body"] = f'"{families["body"]}", "Segoe UI", sans-serif'
    FONTS["mono"] = f'"{families["mono"]}", "Cascadia Mono", "Consolas", monospace'
    return families


def app_font(families: dict[str, str] | None = None) -> QFont:
    """The application font, sized in the same unit the stylesheet uses.

    Point size and the stylesheet's pixel size are two different rulers and
    they disagreed: 10pt is 13.33px at the logical DPI Qt normalises to, while
    every rule below says 13px. Widgets that a rule happens to reach were a
    third of a pixel smaller than widgets it does not, which is invisible until
    a fractional scale factor rounds the two apart.
    """
    font = QFont((families or {}).get("body", "Segoe UI"))
    font.setPixelSize(FONT_PX)
    return font


def color(name: str) -> QColor:
    value = COLORS.get(name, "#FFFFFF")
    if value.startswith("rgb"):
        inner = value[value.find("(") + 1 : value.find(")")]
        parts = [int(p.strip()) for p in inner.split(",")]
        return QColor(*parts)
    return QColor(value)


def polish_combo_popup(combo, *, compact: bool = False) -> None:
    """Fill the combo popup plate. Windows leaves a black gutter otherwise.

    The item view is styled; the native container and the reserved scrollbar
    lane are not. Transparent global scrollbars then show the unstyled frame —
    a black strip down the right of *fast* / *research*. Same fill as QMenu.
    Two-item lists do not get a scrollbar.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QFrame

    view = combo.view()
    if view is None:
        return
    view.setObjectName("ComboPopupView")
    view.setFrameShape(QFrame.Shape.NoFrame)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    if compact:
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setAutoFillBackground(True)
    view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    view.setAlternatingRowColors(False)
    fill = QColor(COLORS["menu_fill"])
    pal = view.palette()
    pal.setColor(QPalette.ColorRole.Base, fill)
    pal.setColor(QPalette.ColorRole.Window, fill)
    pal.setColor(QPalette.ColorRole.AlternateBase, fill)
    pal.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["hover_strong"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["text"]))
    view.setPalette(pal)
    parent = view.parentWidget()
    if parent is not None:
        parent.setObjectName("ComboPopup")
        parent.setAutoFillBackground(True)
        parent.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        parent.setPalette(pal)
        if hasattr(parent, "setFrameShape"):
            parent.setFrameShape(QFrame.Shape.NoFrame)
