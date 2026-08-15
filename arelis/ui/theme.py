from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

log = logging.getLogger(__name__)

# Orbit void — warm black, amber hairline, ivory type. Painted in glass.py.

COLORS = {
    "bg0": "#0a0806",
    "bg1": "#120e0a",
    "bg2": "#1a1510",
    "glass": "rgba(10, 8, 6, 128)",
    "glass_strong": "rgba(12, 10, 8, 168)",
    "glass_soft": "rgba(18, 14, 10, 96)",
    "glass_fill": "rgba(10, 8, 6, 248)",
    "glass_fill_float": "rgba(10, 8, 6, 248)",
    "glass_fill_docked": "rgba(10, 8, 6, 0)",
    "glass_fill_settings": "rgba(10, 8, 6, 200)",
    "rim": "rgba(255, 180, 87, 55)",
    "rim_glow": "rgba(255, 180, 87, 22)",
    "rim_pulse_min": "36",
    "rim_pulse_max": "70",
    "edge": "rgba(255, 180, 87, 48)",
    "edge_bright": "rgba(255, 217, 168, 90)",
    "catch": "rgba(255, 217, 168, 40)",
    "text": "#f3ece0",
    # Idle ghosts use dim; workbench labels sit a step up so they stay readable.
    "dim": "#4a4238",
    "text_dim": "#8a7e70",
    "status_white": "#f3ece0",
    "accent": "#ffb457",
    "accent2": "#ffd9a8",
    "amber": "#ffb457",
    "status_amber": "#ffb457",
    "danger": "#F0A0A8",
    "user_bubble": "rgba(28, 22, 16, 0)",
    "assistant_bubble": "rgba(18, 14, 10, 0)",
    "thinking": "#a89880",
    "chip": "rgba(22, 16, 12, 90)",
}

# Floating must stay opaque: WA_TranslucentBackground on a separate HWND
# otherwise composites the real chat through the plate (the "ghost chat" bug).
# Docked/stage can stay lighter — they share the main window surface.
GLASS = {
    "fill_docked": 0,  # docked instruments are type in the void, not amber TVs
    "fill_float": 255,  # opaque plate; void is a color, not a transparent HWND
    "fill_stage": 0,
    "fill_settings": 200,
    "radius": 12.0,
    "radius_stage": 14.0,
    "rim_pulse_seconds": 6.0,
    "rim_pulse_lo": 36,
    "rim_pulse_hi": 70,
}

FONTS = {
    "display": '"IBM Plex Sans", "Segoe UI Semibold", "Segoe UI", sans-serif',
    "body": '"IBM Plex Sans", "Segoe UI", sans-serif',
    "mono": '"IBM Plex Mono", "Cascadia Mono", "Consolas", monospace',
}

_FONT_DIR = Path(__file__).resolve().parent / "fonts"


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
    fam = (families or {}).get("body", "Segoe UI")
    return QFont(fam, 10)


def color(name: str) -> QColor:
    value = COLORS.get(name, "#FFFFFF")
    if value.startswith("rgba"):
        inner = value[value.find("(") + 1 : value.find(")")]
        parts = [p.strip() for p in inner.split(",")]
        return QColor(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    return QColor(value)


def stylesheet() -> str:
    c = COLORS
    f = FONTS
    return f"""
    QMainWindow {{
        background: transparent;
        color: {c['text']};
        font-family: {f['body']};
        font-size: 13px;
    }}
    #StageRoot {{
        background: transparent;
        color: {c['text']};
        font-family: {f['body']};
        font-size: 13px;
    }}
    QWidget {{
        color: {c['text']};
        font-family: {f['body']};
        font-size: 13px;
        font-weight: 300;
    }}
    /* Glass panels: painted in code — keep stylesheets transparent */
    #GlassPanel, #GlassDockContent, #ChatStage, #ChatPanelInner, #ComposerInner,
    #SettingsGlass, #SettingsTabBody {{
        background: transparent;
        border: none;
    }}
    #TitleBar {{
        background-color: rgba(10, 8, 6, 28);
        border-bottom: 1px solid rgba(255, 180, 87, 18);
    }}
    #FloatingTitleBar {{
        background: transparent;
        border: none;
    }}
    #FloatingDockTitle {{
        color: {c['text_dim']};
        font-family: {f['display']};
        font-size: 11px;
        font-weight: 400;
        letter-spacing: 0.12em;
        background: transparent;
        border: none;
        padding: 0;
        margin: 0;
    }}
    #ChromeTitle {{
        color: {c['dim']};
        font-family: {f['mono']};
        font-size: 11px;
        font-weight: 400;
        letter-spacing: 0.14em;
        background: transparent;
        border: none;
        padding: 0 2px 0 0;
    }}
    #ChromeViewBtn, #ChromeSettingsBtn {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 4px 10px;
        color: {c['text_dim']};
        font-size: 12px;
    }}
    #ChromeViewBtn:hover, #ChromeSettingsBtn:hover {{
        color: {c['accent']};
        background: rgba(40, 28, 16, 120);
    }}
    #SettingsDialog {{
        background: transparent;
        color: {c['text']};
    }}
    #SettingsHeading {{
        color: {c['text_dim']};
        font-family: {f['display']};
        font-size: 14px;
        font-weight: 400;
        letter-spacing: 0.08em;
        background: transparent;
        padding: 2px 0;
    }}
    #SettingsClose {{
        background: transparent;
        border: 1px solid rgba(255, 180, 87, 35);
        border-radius: 8px;
        color: {c['text_dim']};
        font-size: 12px;
    }}
    #SettingsClose:hover {{
        background: rgba(160, 60, 70, 180);
        border-color: rgba(240, 160, 168, 120);
        color: #fff;
    }}
    #SettingsHint, #SettingsNotifyUrl {{
        color: {c['text_dim']};
        font-size: 12px;
        background: transparent;
    }}
    #SettingsNotifyUrl {{
        color: {c['text']};
        font-family: {f['mono']};
        padding: 10px 12px;
        background: rgba(18, 14, 10, 110);
        border: 1px solid rgba(255, 217, 168, 55);
        border-radius: 10px;
    }}
    #SettingsTabs {{
        background: transparent;
        border: none;
    }}
    #SettingsTabs::pane {{
        border: 1px solid rgba(255, 180, 87, 55);
        border-radius: 14px;
        background: rgba(12, 10, 8, 72);
        top: 8px;
        padding: 2px;
    }}
    #SettingsTabs QTabBar {{
        background: transparent;
    }}
    #SettingsTabs QTabBar::tab {{
        background-color: {c['chip']};
        border: 1px solid rgba(255, 180, 87, 40);
        border-radius: 8px;
        color: {c['text_dim']};
        padding: 6px 14px;
        margin-right: 6px;
        min-width: 52px;
    }}
    #SettingsTabs QTabBar::tab:hover {{
        color: {c['accent']};
        border-color: rgba(255, 180, 87, 80);
        background: rgba(40, 28, 16, 150);
    }}
    #SettingsTabs QTabBar::tab:selected {{
        color: {c['accent']};
        border-color: rgba(255, 180, 87, 130);
        background: rgba(60, 40, 18, 170);
    }}
    #SettingsField {{
        min-width: 180px;
    }}
    #SettingsSlider::groove:horizontal {{
        height: 6px;
        border-radius: 3px;
        background: rgba(22, 16, 12, 160);
        border: 1px solid rgba(255, 180, 87, 40);
    }}
    #SettingsSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        background: {c['accent']};
        border: 1px solid rgba(255, 217, 168, 90);
    }}
    #SettingsButtons QPushButton {{
        min-width: 72px;
        padding: 6px 16px;
    }}
    QCheckBox {{
        color: {c['text']};
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 4px;
        border: 1px solid rgba(255, 180, 87, 70);
        background: rgba(12, 10, 8, 140);
    }}
    QCheckBox::indicator:checked {{
        background: {c['accent']};
        border-color: {c['accent']};
    }}
    #ChromeMin, #ChromeMax, #ChromeClose {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        color: {c['text_dim']};
        font-size: 11px;
        padding: 0;
    }}
    #ChromeMin:hover, #ChromeMax:hover {{
        background: rgba(40, 28, 16, 120);
        border-color: rgba(255, 180, 87, 55);
    }}
    #ChromeClose:hover {{
        background: rgba(160, 60, 70, 150);
        border-color: rgba(240, 160, 168, 100);
    }}
    #ChromeMin:pressed, #ChromeMax:pressed {{
        background: rgba(32, 22, 14, 160);
    }}
    QToolBar#ChromeToolBar {{
        background: transparent;
        border: none;
        spacing: 0;
        padding: 0;
        margin: 0;
    }}
    #ChromeStack {{
        background: transparent;
        border: none;
    }}
    #ReadinessStrip {{
        background-color: transparent;
        border-bottom: 1px solid rgba(255, 180, 87, 14);
    }}
    #ReadinessChip {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 1px 8px;
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: 0.12em;
    }}
    #ReadinessChip[status="ok"] {{
        color: {c['accent']};
        border-color: rgba(255, 180, 87, 90);
    }}
    #ReadinessChip[status="warn"] {{
        color: {c['status_amber']};
        border-color: rgba(245, 193, 108, 90);
    }}
    #ReadinessChip[status="off"] {{
        color: {c['text_dim']};
        border-color: rgba(255, 180, 87, 28);
    }}
    #ReadinessChip[status="wait"] {{
        color: {c['danger']};
        border-color: rgba(240, 160, 168, 160);
        background-color: rgba(80, 28, 36, 120);
    }}
    #ReadinessChip[status="wait_dim"] {{
        color: {c['danger']};
        border-color: rgba(240, 160, 168, 70);
        background-color: rgba(40, 16, 22, 90);
    }}
    #NotifyPill {{
        background-color: rgba(22, 16, 12, 210);
        border: 1px solid rgba(255, 180, 87, 70);
        border-radius: 10px;
        padding: 4px 12px;
        color: {c['accent']};
        font-size: 11px;
        font-family: {f['mono']};
        letter-spacing: 0.04em;
        min-height: 26px;
    }}
    #NotifyPill:hover {{
        border-color: {c['accent']};
        color: {c['status_white']};
    }}
    #NotifyCardTitle {{
        color: {c['text']};
        font-size: 13px;
        font-family: {f['display']};
        font-weight: 600;
    }}
    #NotifyCardBody {{
        color: {c['text_dim']};
        font-size: 12px;
        font-family: {f['body']};
    }}
    #ChatEmptyTitle {{
        color: rgba(243, 236, 224, 102);
        font-family: {f['body']};
        font-size: 15px;
        font-weight: 300;
        letter-spacing: 0.01em;
        background: transparent;
        border: none;
    }}
    #ChatEmptyHint, #VoidListenWord {{
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: 0.32em;
        background: transparent;
        border: none;
    }}
    /* Talk / dictate latched on the empty orbit: amber, not dim grey. */
    #VoidListenWord[live="true"] {{
        color: {c['accent']};
    }}
    #VoidGhostKey {{
        color: {c['dim']};
        font-size: 9px;
        font-family: {f['mono']};
        letter-spacing: 0.14em;
        background: transparent;
        border: none;
    }}
    #VoidGhostValue {{
        color: rgba(243, 236, 224, 153);
        font-size: 13px;
        font-family: {f['body']};
        background: transparent;
        border: none;
    }}
    #VoidReadoutKey {{
        color: rgba(243, 236, 224, 56);
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: 0.05em;
        background: transparent;
        border: none;
    }}
    #VoidReadoutValue {{
        color: {c['accent2']};
        font-size: 10px;
        font-family: {f['mono']};
        font-weight: 400;
        letter-spacing: 0.05em;
        background: transparent;
        border: none;
    }}
    #VoidHairline {{
        background: rgba(255, 180, 87, 26);
    }}
    #ShortcutsSheet {{
        background-color: {c['bg1']};
    }}
    #ShortcutsTitle {{
        color: {c['text']};
        font-size: 18px;
        font-family: {f['body']};
        letter-spacing: 0.04em;
        background: transparent;
    }}
    #ShortcutsGroup {{
        color: {c['dim']};
        font-size: 9px;
        font-family: {f['mono']};
        letter-spacing: 0.14em;
        background: transparent;
        padding-bottom: 4px;
    }}
    #ShortcutsChord {{
        color: {c['accent2']};
        font-size: 11px;
        font-family: {f['mono']};
        background: transparent;
    }}
    #ShortcutsWhat {{
        color: rgba(243, 236, 224, 153);
        font-size: 12px;
        font-family: {f['body']};
        background: transparent;
    }}
    #ShortcutsAbout {{
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        background: transparent;
        padding-top: 10px;
    }}
    #NotifyMarkRead {{
        color: {c['text_dim']};
        font-size: 11px;
        background: transparent;
        border: 1px solid rgba(255, 180, 87, 35);
    }}
    #NotifyMarkRead:hover {{
        color: {c['accent']};
        border-color: {c['accent']};
    }}
    #ReadinessSystems {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 1px 8px;
        color: {c['dim']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: 0.12em;
    }}
    #ReadinessSystems:hover {{
        color: {c['accent']};
        border-color: rgba(255, 180, 87, 90);
    }}
    #ReadinessSystems[status="ok"] {{
        color: {c['accent']};
        border-color: rgba(255, 180, 87, 90);
    }}
    #ReadinessSystems[status="warn"] {{
        color: {c['status_amber']};
        border-color: rgba(245, 193, 108, 90);
    }}
    #ReadinessSystems[status="off"] {{
        color: {c['text_dim']};
        border-color: rgba(255, 180, 87, 28);
    }}
    #ReadinessSystems[status="wait"] {{
        color: {c['danger']};
        border-color: rgba(240, 160, 168, 160);
        background-color: rgba(80, 28, 36, 140);
    }}
    #ReadinessSystems[status="wait_dim"] {{
        color: {c['danger']};
        border-color: rgba(240, 160, 168, 70);
        background-color: rgba(40, 16, 22, 100);
    }}
    #ReadinessSystemsMenu {{
        background-color: rgba(14, 10, 8, 240);
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px;
        color: {c['text']};
        font-size: 12px;
    }}
    #ReadinessSystemsMenu::item {{
        padding: 4px 10px;
        border-radius: 6px;
        color: {c['text_dim']};
    }}
    #ReadinessSystemsMenu::item:disabled {{
        color: {c['text']};
    }}
    /* Glass lists — no native inset wells; no H-scroll gutters. */
    #HistoryList, #FactsList, #ActiveFactsList, #NotificationsList {{
        background: transparent;
        border: none;
        outline: none;
        padding: 2px 0;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
    }}
    #HistoryList::item, #FactsList::item, #ActiveFactsList::item,
    #NotificationsList::item {{
        background: transparent;
        border: none;
        outline: none;
        border-radius: 10px;
        padding: 8px 10px;
        margin: 1px 0;
        color: {c['text']};
    }}
    #FactsList::item, #ActiveFactsList::item {{
        /* Long facts wrap inside the dock instead of clipping mid-word. */
        padding: 8px 10px;
    }}
    #HistoryList::item:hover, #FactsList::item:hover, #ActiveFactsList::item:hover,
    #NotificationsList::item:hover {{
        background: rgba(40, 28, 16, 70);
        border-color: transparent;
    }}
    #HistoryList::item:selected, #FactsList::item:selected,
    #ActiveFactsList::item:selected, #NotificationsList::item:selected {{
        background: rgba(60, 40, 18, 90);
        border-color: transparent;
        color: {c['text']};
    }}
    #InstrumentTitle {{
        color: {c['dim']};
        font-size: 11px;
        font-weight: 400;
        letter-spacing: 0.12em;
        background: transparent;
        padding: 0 0 2px 2px;
    }}
    #InstrumentHint, #WorkspaceRootLabel {{
        color: {c['text_dim']};
        font-size: 11px;
        font-family: {f['body']};
        background: transparent;
        padding: 0 0 2px 2px;
        border: none;
    }}
    #NotificationDetail {{
        color: {c['text']};
        font-size: 13px;
        font-family: {f['body']};
        background: rgba(18, 14, 10, 90);
        border: 1px solid rgba(255, 180, 87, 40);
        border-radius: 8px;
        padding: 10px 12px;
    }}
    #InstrumentSearch {{
        background-color: transparent;
        border: none;
        border-bottom: 1px solid rgba(255, 180, 87, 22);
        border-radius: 0;
        padding: 5px 4px;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
        selection-background-color: rgba(90, 58, 24, 180);
    }}
    #InstrumentSearch:focus {{
        border: 1px solid {c['accent']};
    }}
    #InstrumentAction {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 4px 8px;
        color: {c['dim']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 400;
    }}
    #InstrumentAction:hover {{
        background-color: transparent;
        border: none;
        color: {c['accent']};
    }}
    #InstrumentAction:pressed {{
        background-color: transparent;
    }}
    QDockWidget {{
        color: {c['text_dim']};
        background: transparent;
        border: none;
        titlebar-close-icon: none;
    }}
    QDockWidget::title {{
        background: transparent;
        border: none;
        padding: 0px;
        margin: 0px;
        height: 0px;
    }}
    QDockWidget > QWidget {{
        background: transparent;
        border: none;
    }}
    QMainWindow::separator {{
        background: rgba(255, 180, 87, 28);
        width: 1px;
        height: 1px;
    }}
    QDockWidget QTabBar, #DockTabBar {{
        background: transparent;
    }}
    QDockWidget QTabBar::tab, #DockTabBar::tab {{
        background: transparent;
        color: {c['text_dim']};
        border: none;
        padding: 5px 14px;
        font-size: 11px;
        letter-spacing: 0.06em;
    }}
    QDockWidget QTabBar::tab:selected, #DockTabBar::tab:selected {{
        color: {c['accent']};
        background: rgba(40, 28, 16, 90);
    }}
    QDockWidget QTabBar::tab:hover, #DockTabBar::tab:hover {{
        color: {c['accent']};
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: transparent;
        border: none;
        border-radius: 10px;
        padding: 10px;
        selection-background-color: rgba(90, 58, 24, 180);
        font-family: {f['body']};
    }}
    #ChatView {{
        background-color: transparent;
        border: none;
        padding: 12px 28px 16px 18px;
        font-size: 15px;
        font-weight: 300;
        color: {c['text']};
    }}
    #ThinkingView {{
        color: {c['thinking']};
        font-family: {f['mono']};
        font-size: 11px;
        background-color: transparent;
        border: none;
        padding: 4px 2px;
    }}
    #Editor, #OutputView {{
        font-family: {f['mono']};
        font-size: 12px;
        background-color: transparent;
        border: none;
        border-radius: 0;
        color: {c['text']};
        padding: 8px 2px;
    }}
    #WorkspaceImageWell {{
        border: none;
        border-radius: 0;
        color: {c['text_dim']};
        background: transparent;
    }}
    #ComposerInput {{
        background-color: transparent;
        border: none;
        padding: 6px 4px;
        border-radius: 0;
        color: {c['text']};
        font-size: 16px;
        font-weight: 300;
        letter-spacing: 0.01em;
        selection-background-color: rgba(90, 58, 24, 180);
    }}
    #ComposerInput:focus {{
        border: none;
    }}
    #ComposerInput::placeholder {{
        color: rgba(243, 236, 224, 102);
    }}
    #VoidIdlePlaceholder {{
        color: rgba(243, 236, 224, 102);
        font-size: 16px;
        font-family: {f['body']};
        font-weight: 300;
        letter-spacing: 0.01em;
        background: transparent;
        border: none;
    }}
    QLineEdit {{
        background-color: rgba(10, 8, 6, 70);
        border: 1px solid rgba(255, 180, 87, 45);
        border-radius: 8px;
        padding: 5px 10px;
        color: {c['text']};
        selection-background-color: rgba(90, 58, 24, 180);
    }}
    QLineEdit:focus {{
        border: 1px solid {c['accent']};
    }}
    QPushButton {{
        background-color: rgba(22, 16, 12, 90);
        border: 1px solid rgba(255, 180, 87, 55);
        border-radius: 8px;
        padding: 4px 12px;
        color: {c['text_dim']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: rgba(60, 40, 18, 140);
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    QPushButton:pressed {{
        background-color: rgba(18, 12, 8, 180);
    }}
    #SendButton, #AttachButton, #MicButton, #ConversationButton {{
        background: transparent;
        border: none;
        border-radius: 0;
        padding: 3px;
    }}
    #SendButton:hover, #AttachButton:hover,
    #MicButton:hover, #ConversationButton:hover {{
        background: transparent;
        border: none;
        color: {c['accent']};
    }}
    #AttachButton:disabled, #MicButton:disabled, #ConversationButton:disabled {{
        border: none;
        background: transparent;
    }}
    /* Live capture is the one state that leaves the accent palette, because it
       is the one state where the user has to notice without looking for it. */
    #MicButton:checked, #ConversationButton:checked {{
        background: rgba(90, 62, 24, 130);
        border: 1px solid {c['status_amber']};
    }}
    #StopButton {{
        background: transparent;
        border: 1px solid rgba(240, 160, 168, 90);
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['danger']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #StopButton:hover {{
        background: rgba(120, 40, 50, 120);
        border-color: {c['danger']};
    }}
    #DriveBrand {{
        color: {c['accent']};
        font-family: {f['mono']};
        font-size: 11px;
        background: transparent;
    }}
    #DriveStatus {{
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        background: transparent;
    }}
    #PauseButton {{
        background: transparent;
        border: 1px solid rgba(90, 212, 255, 80);
        border-radius: 8px;
        padding: 2px 10px;
        color: #8ad8ef;
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #PauseButton:hover {{
        background: rgba(30, 70, 90, 120);
        border-color: #5ad4ff;
    }}
    #GoButton {{
        background: transparent;
        border: 1px solid rgba(255, 180, 87, 90);
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['accent']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #GoButton:hover {{
        background: rgba(90, 62, 24, 120);
        border-color: {c['accent']};
    }}
    #ConfirmCard {{
        background-color: rgba(18, 14, 10, 140);
        border: 1px solid rgba(255, 180, 87, 55);
        border-radius: 10px;
    }}
    #ConfirmSummary {{
        color: {c['text']};
        font-family: {f['mono']};
        font-size: 12px;
        background: transparent;
    }}
    #ConfirmDetail {{
        color: {c['text']};
        font-family: {f['mono']};
        font-size: 12px;
        background-color: rgba(12, 10, 8, 120);
        border: 1px solid rgba(255, 180, 87, 45);
        border-radius: 8px;
        padding: 6px;
    }}
    #ConfirmNote {{
        color: {c['danger']};
        font-size: 11px;
        background: transparent;
    }}
    #ConfirmAllowTurn {{
        color: {c['text_dim']};
        font-size: 11px;
        spacing: 6px;
    }}
    #ConfirmAllow, #FactApprove {{
        min-width: 72px;
        background-color: rgba(90, 58, 24, 180);
        border: 1px solid {c['accent']};
        color: {c['text']};
        font-family: {f['body']};
        font-size: 12px;
        font-weight: 600;
    }}
    #ConfirmAllow:hover, #FactApprove:hover {{
        background-color: rgba(110, 70, 28, 200);
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #ConfirmSkip, #FactReject, #FactRejectAll, #FactForget {{
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        font-weight: 500;
        background-color: transparent;
        border: 1px solid rgba(255, 180, 87, 40);
    }}
    #ConfirmSkip:hover, #FactReject:hover, #FactRejectAll:hover, #FactForget:hover {{
        color: {c['text']};
        border-color: rgba(255, 180, 87, 80);
        background-color: rgba(40, 28, 16, 100);
    }}
    QMenu::item {{
        padding: 6px 14px;
        border-radius: 6px;
        min-height: 22px;
    }}
    QMenu::separator {{
        height: 1px;
        background: rgba(255, 180, 87, 40);
        margin: 6px 8px;
    }}
    QComboBox {{
        background-color: transparent;
        border: none;
        border-radius: 0;
        padding: 0px 18px 0px 8px;
        color: {c['dim']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #RoleSelect {{
        min-width: 78px;
        max-width: 96px;
        padding: 0px 14px 0px 8px;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 14px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    QComboBox::down-arrow {{
        width: 8px;
        height: 8px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['bg2']};
        selection-background-color: rgba(90, 58, 24, 200);
        color: {c['text']};
        border: 1px solid {c['edge']};
        outline: none;
        padding: 2px;
    }}
    #RoleSelect QAbstractItemView {{
        min-width: 88px;
        max-width: 96px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255, 180, 87, 70);
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 0px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
        height: 0;
    }}
    QMenu {{
        background-color: rgba(14, 10, 8, 230);
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px;
        color: {c['text']};
    }}
    QMenu::item:selected {{
        background: rgba(60, 40, 18, 200);
        border-radius: 6px;
    }}
    QSplitter::handle {{
        background-color: transparent;
        width: 1px;
        height: 1px;
    }}
    QToolTip {{
        background-color: {c['bg2']};
        color: {c['text']};
        border: 1px solid {c['edge']};
        padding: 6px 8px;
    }}
    """
