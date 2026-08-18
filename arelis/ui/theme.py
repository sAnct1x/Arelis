from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

from arelis.paths import cache_dir, ensure

log = logging.getLogger(__name__)

# Orbit void — one light source, an incandescent filament at roughly 2300K
# burning in an unlit room, and every colour below is a reading off it.
#
# The rule that keeps it from going bronze: as a surface gets darker it also
# gets *redder*, because that is what a cooling ember does. Hue runs from ~17
# in the deepest fills to ~33 at the accent, and saturation stays high all the
# way down. A dark that is only 20% saturated is not a shadow, it is grey paint
# with a warm tint on it, and a mid-value 30%-saturated orange is not lamplight
# either — it is metal. Both were what the palette used to be made of.
#
# Practical consequence: nothing here is neutral. There is no grey in the app.

COLORS = {
    # --- the void -------------------------------------------------------
    "bg0": "#0c0705",
    "bg1": "#140c08",
    "bg2": "#1e120b",
    "plate": "rgba(12, 7, 5, 255)",  # opaque body of a floating tool window
    "panel_fill": "rgba(24, 14, 10, 255)",  # settings pane, sms thread
    "veil": "rgba(12, 7, 5, 28)",  # barely-there wash over the atmosphere
    "scrim": "rgba(12, 7, 5, 200)",  # drop target over the live chat
    "code_fill": "rgba(10, 6, 4, 170)",  # fenced code inside a transcript bubble
    "glass": "rgba(12, 7, 5, 128)",
    "glass_strong": "rgba(14, 9, 6, 168)",
    "glass_soft": "rgba(22, 13, 9, 96)",
    "glass_fill": "rgba(12, 7, 5, 248)",
    "glass_fill_float": "rgba(12, 7, 5, 248)",
    "glass_fill_docked": "rgba(12, 7, 5, 0)",
    "glass_fill_settings": "rgba(12, 7, 5, 255)",
    "bubble_fill": "rgba(14, 8, 6, 120)",
    "bubble_wash": "rgba(10, 6, 4, 110)",  # transcript bubbles, written as HTML
    "menu_fill": "rgba(18, 11, 8, 238)",

    # --- surfaces the light falls on ------------------------------------
    "inset": "rgba(14, 8, 6, 140)",  # sunken well inside a plate
    "well": "rgba(26, 15, 10, 255)",  # text field at rest
    "well_focus": "rgba(36, 20, 12, 255)",
    "well_soft": "rgba(24, 14, 9, 120)",
    "card_fill": "rgba(24, 14, 9, 150)",
    "raised": "rgba(30, 17, 11, 255)",
    "raised_warm": "rgba(44, 25, 13, 255)",
    "sunk": "rgba(22, 12, 7, 255)",  # pressed
    "sunk_soft": "rgba(22, 12, 7, 180)",
    "tab_selected": "rgba(60, 34, 15, 255)",
    "groove": "rgba(28, 16, 11, 160)",
    "chip": "rgba(28, 16, 11, 96)",
    "chip_solid": "rgba(28, 16, 11, 210)",
    "row_hover": "rgba(50, 28, 14, 72)",
    "row_selected": "rgba(72, 40, 17, 96)",
    "hover_soft": "rgba(50, 28, 14, 96)",
    "hover": "rgba(50, 28, 14, 130)",
    "hover_strong": "rgba(72, 40, 17, 200)",
    "button_fill": "rgba(50, 28, 14, 160)",
    "button_hover": "rgba(84, 46, 18, 200)",
    "button_hover_hot": "rgba(130, 70, 26, 200)",
    "button_hover_soft": "rgba(72, 40, 17, 140)",
    "live_fill": "rgba(106, 60, 20, 130)",  # a latched capture control
    "selection": "rgba(104, 56, 20, 180)",
    "selection_strong": "rgba(104, 56, 20, 200)",

    # --- rims: the filament seen edge-on --------------------------------
    "rim": "rgba(255, 180, 87, 55)",
    "rim_glow": "rgba(255, 180, 87, 22)",
    "rim_pulse_min": "36",
    "rim_pulse_max": "70",
    "hairline_faint": "rgba(255, 180, 87, 16)",
    "hairline": "rgba(255, 180, 87, 26)",
    "hairline_mid": "rgba(255, 180, 87, 34)",
    "edge_soft": "rgba(255, 180, 87, 35)",
    "edge": "rgba(255, 180, 87, 48)",
    "edge_mid": "rgba(255, 180, 87, 70)",
    "edge_strong": "rgba(255, 180, 87, 90)",
    "edge_hot": "rgba(255, 180, 87, 170)",
    "edge_warm": "rgba(255, 217, 168, 55)",
    "edge_bright": "rgba(255, 217, 168, 90)",
    "catch": "rgba(255, 217, 168, 40)",

    # --- type: warm ivory down to the coals -----------------------------
    "text": "#f7e4d2",
    "hint": "#e0b683",  # secondary prose: soft gold, one step under the light
    "thinking": "#b4936f",
    "text_dim": "#9a7c62",
    # Idle ghosts use dim; workbench labels sit a step up so they stay readable.
    "dim": "#5a4030",
    "status_white": "#f7e4d2",
    # Type that sits *in* the bloom rather than on a plate. Kept as alphas of a
    # warm ivory so the void still shows through — an opaque colour here would
    # flatten the orbit face. The base is tinted because ivory over black
    # composites to grey, which is how the idle prompt ended up olive.
    "text_soft": "rgba(255, 224, 186, 158)",
    "text_muted": "rgba(255, 224, 186, 108)",
    "text_faint": "rgba(255, 224, 186, 62)",

    # --- the light itself -----------------------------------------------
    "accent": "#ffb457",
    "accent2": "#ffd9a8",
    "amber": "#ffb457",
    "status_amber": "#ffb457",
    # Attention without leaving the family: hotter and redder than the accent,
    # so a warn chip is not the same pixel value as an ok one.
    "warn": "#ff9d3d",

    # --- alarm: the one thing allowed off the ramp ----------------------
    "danger": "#F0A0A8",
    "danger_edge_soft": "rgba(240, 160, 168, 90)",
    "danger_edge": "rgba(240, 160, 168, 120)",
    "danger_fill_soft": "rgba(120, 40, 50, 120)",
    "danger_fill": "rgba(160, 60, 70, 180)",
    "danger_wash": "rgba(40, 16, 22, 90)",

    "user_bubble": "rgba(28, 22, 16, 0)",
    "assistant_bubble": "rgba(18, 14, 10, 0)",
}

# The orbit core is the filament seen directly rather than the glow it throws,
# so it runs hotter and whiter than the accent. Same ramp for the travelling
# tick, one step cooler, so the tick reads as a bead of the same light.
FILAMENT = {
    "core": (255, 233, 202),
    "core_halo": (255, 222, 180),
    "tick": (255, 214, 160),
    "tick_halo": (255, 200, 128),
}

# The atmosphere behind everything: the lamp itself, blooming through the room.
# Stops are (r, g, b, a) at a gradient position.
BLOOM = {
    "inner": ((0.0, (255, 170, 88, 40)), (0.22, (232, 110, 40, 24)), (0.55, (96, 40, 14, 12))),
    "outer": ((0.0, (180, 80, 28, 16)), (0.45, (48, 20, 10, 9))),
    "grain": (255, 180, 87),
    "vignette": (10, 5, 3, 80),
}

# Floating must stay opaque: WA_TranslucentBackground on a separate HWND
# otherwise composites the real chat through the plate (the "ghost chat" bug).
# Docked/stage can stay lighter — they share the main window surface.
GLASS = {
    "fill_docked": 0,  # docked instruments are type in the void, not amber TVs
    "fill_float": 255,  # opaque plate; void is a color, not a transparent HWND
    "fill_stage": 0,
    "fill_settings": 255,
    "radius": 12.0,
    "radius_stage": 12.0,
    "rim_pulse_seconds": 6.0,
    "rim_pulse_lo": 36,
    "rim_pulse_hi": 70,
}

# Control heights. Two tiers on purpose, and only two: dock furniture, and the
# composer, which is the one row that is not furniture. A third tier is how the
# workspace dock ended up with 24px buttons beside 28px ones.
METRICS = {
    "row": 28,  # search fields, dock actions, inbox buttons
    "control": 34,  # composer: role picker, attach, mic, send
    "chrome": 28,  # close / minimize on a floating plate
    "icon": 24,
}

# One number for body type, shared by the QFont the application is given and by
# the stylesheet, which used to say 13px while app_font() said 10pt.
FONT_PX = 13

FONTS = {
    "display": '"IBM Plex Sans", "Segoe UI Semibold", "Segoe UI", sans-serif',
    "body": '"IBM Plex Sans", "Segoe UI", sans-serif',
    "mono": '"IBM Plex Mono", "Cascadia Mono", "Consolas", monospace',
}

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


def dock_tab_bar_qss() -> str:
    """Opaque ember tabs. Translucent QSS on a Windows QTabBar shows grey through."""
    c = COLORS
    return f"""
    QTabBar {{
        background: transparent;
    }}
    QTabBar::tab {{
        background-color: {c['raised']};
        color: {c['text_dim']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 6px 16px;
        margin-right: 4px;
        min-width: 52px;
        font-size: 12px;
        letter-spacing: 0.06em;
    }}
    QTabBar::tab:selected {{
        color: {c['accent2']};
        background-color: {c['tab_selected']};
        border-color: {c['edge_hot']};
    }}
    QTabBar::tab:hover {{
        color: {c['accent']};
        background-color: {c['hover_strong']};
        border-color: {c['edge_strong']};
    }}
    """


def stylesheet() -> str:
    c = COLORS
    f = FONTS
    m = METRICS
    return f"""
    QMainWindow {{
        background: transparent;
        color: {c['text']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
    }}
    #StageRoot {{
        background: transparent;
        color: {c['text']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
    }}
    QWidget {{
        color: {c['text']};
        font-family: {f['body']};
        font-size: {FONT_PX}px;
        font-weight: 300;
    }}
    /* Glass panels: painted in code — keep stylesheets transparent */
    #GlassPanel, #GlassDockContent, #ChatStage, #ChatPanelInner, #ComposerInner,
    #SettingsGlass, #NotifyInboxGlass, #ChatEmpty, #VoidPromptHost,
    #VoidVoiceHost, #GlassDialogGlass {{
        background: transparent;
        border: none;
    }}
    #TitleBar {{
        background-color: {c['veil']};
        border-bottom: 1px solid {c['hairline_faint']};
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
        background: {c['hover']};
    }}
    #SettingsDialog, #ContactsInbox, #NotificationsInbox, #SmsChat,
    #GlassDialog {{
        background: {c['plate']};
        border: none;
        color: {c['text']};
    }}
    #SettingsHeading {{
        color: {c['accent2']};
        font-family: {f['display']};
        font-size: 15px;
        font-weight: 400;
        letter-spacing: 0.08em;
        background: transparent;
        padding: 2px 0;
    }}
    #SettingsClose, #SettingsMinimize {{
        background: transparent;
        border: 1px solid {c['edge_soft']};
        border-radius: 8px;
        color: {c['text_dim']};
        font-size: 12px;
    }}
    /* Close is the only chrome button that turns red. Minimize puts the window
       away and is undone by clicking the tray; it does not deserve the same
       alarm, and wearing #SettingsClose is how the SMS tile came to have one. */
    #SettingsClose:hover {{
        background: {c['danger_fill']};
        border-color: {c['danger_edge']};
        color: {c['status_white']};
    }}
    #SettingsMinimize:hover {{
        background: {c['hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #SettingsHint, #SettingsNotifyUrl {{
        color: {c['accent2']};
        font-size: 12px;
        background: transparent;
    }}
    #SettingsHint {{
        color: {c['hint']};
    }}
    #SettingsNotifyUrl {{
        color: {c['text']};
        font-family: {f['mono']};
        padding: 10px 12px;
        background: {c['well_soft']};
        border: 1px solid {c['edge_warm']};
        border-radius: 10px;
    }}
    #SettingsTabs {{
        background: transparent;
        border: none;
    }}
    #SettingsTabs::pane {{
        border: 1px solid {c['edge_strong']};
        border-radius: {int(GLASS['radius'])}px;
        background: {c['panel_fill']};
        top: 8px;
        padding: 8px;
    }}
    #SettingsTabBody {{
        background: {c['panel_fill']};
        border: none;
    }}
    #SettingsTabs QTabBar {{
        background: transparent;
    }}
    #SettingsTabs QTabBar::tab {{
        background-color: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text_dim']};
        padding: 6px 14px;
        margin-right: 6px;
        min-width: 52px;
    }}
    #SettingsTabs QTabBar::tab:hover {{
        color: {c['accent']};
        border-color: {c['edge_strong']};
        background: {c['hover']};
    }}
    #SettingsTabs QTabBar::tab:selected {{
        color: {c['accent2']};
        border-color: {c['edge_hot']};
        background: {c['tab_selected']};
    }}
    #SettingsField {{
        min-width: 180px;
    }}
    #SettingsList {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        outline: none;
        padding: 4px;
    }}
    #SettingsList::item {{
        color: {c['text']};
        padding: 6px 8px;
        border-radius: 6px;
    }}
    #SettingsList::item:selected {{
        background-color: {c['tab_selected']};
        color: {c['accent2']};
    }}
    #SettingsList::item:hover {{
        background-color: {c['hover_strong']};
        color: {c['accent']};
    }}
    #SettingsSlider::groove:horizontal {{
        height: 6px;
        border-radius: 3px;
        background: {c['groove']};
        border: 1px solid {c['edge']};
    }}
    #SettingsSlider::handle:horizontal {{
        width: 14px;
        height: 14px;
        margin: -5px 0;
        border-radius: 7px;
        background: {c['accent']};
        border: 1px solid {c['edge_bright']};
    }}
    #SettingsButtons QPushButton {{
        min-width: 72px;
        padding: 6px 16px;
        background-color: {c['raised']};
        color: {c['text']};
        border: 1px solid {c['edge_strong']};
    }}
    #SettingsTabBody QPushButton {{
        background-color: {c['raised']};
        color: {c['text']};
        border: 1px solid {c['edge']};
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
        border: 1px solid {c['edge_mid']};
        background: {c['inset']};
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
        background: {c['hover']};
        border-color: {c['rim']};
    }}
    #ChromeClose:hover {{
        background: {c['danger_fill']};
        border-color: {c['danger_edge']};
    }}
    #ChromeMin:pressed, #ChromeMax:pressed {{
        background: {c['sunk_soft']};
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
        border-bottom: 1px solid {c['hairline_faint']};
    }}
    /* Borderless by design, so these carry colour and nothing else. The
       status rules used to set border-color as well, on a rule that has
       declared `border: none` two lines above. */
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
    }}
    #ReadinessChip[status="warn"] {{
        color: {c['warn']};
    }}
    #ReadinessChip[status="off"] {{
        color: {c['text_dim']};
    }}
    #ReadinessChip[status="wait"] {{
        color: {c['danger']};
        background-color: {c['danger_fill_soft']};
    }}
    #ReadinessChip[status="wait_dim"] {{
        color: {c['danger']};
        background-color: {c['danger_wash']};
    }}
    /* The notification count on the strip is a button, not a label: it opens
       the mailbox. It wore #ReadinessChip, a rule written for QLabels, so it
       had no pressed or hover state and no edge to aim at. */
    #ReadinessNotifyChip {{
        background-color: {c['chip']};
        border: 1px solid {c['edge_soft']};
        border-radius: 9px;
        padding: 1px 10px;
        min-height: 18px;
        color: {c['warn']};
        font-size: 10px;
        font-family: {f['mono']};
        letter-spacing: 0.12em;
    }}
    #ReadinessNotifyChip:hover {{
        background-color: {c['hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #ReadinessNotifyChip:pressed {{
        background-color: {c['sunk_soft']};
    }}
    #NotifyPill {{
        background-color: {c['chip_solid']};
        border: 1px solid {c['edge_mid']};
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
    /* The tracking on the idle words lives here and only here. void_idle.py
       also set it through setFont, which is a second author for one property
       and left the label's measured width disagreeing with its painted one. */
    #VoidListenWord {{
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
        color: {c['text_soft']};
        font-size: {FONT_PX}px;
        font-family: {f['body']};
        background: transparent;
        border: none;
    }}
    #VoidReadoutKey {{
        color: {c['text_faint']};
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
        background: {c['hairline']};
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
        color: {c['text_soft']};
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
    }}
    #ReadinessSystems[status="ok"] {{
        color: {c['accent']};
    }}
    #ReadinessSystems[status="warn"] {{
        color: {c['warn']};
    }}
    #ReadinessSystems[status="off"] {{
        color: {c['text_dim']};
    }}
    #ReadinessSystems[status="wait"] {{
        color: {c['danger']};
        background-color: {c['danger_fill_soft']};
    }}
    #ReadinessSystems[status="wait_dim"] {{
        color: {c['danger']};
        background-color: {c['danger_wash']};
    }}
    /* A readout that drops down, not a menu. Every row is a fact about a
       subsystem and none of them is a command, so nothing here highlights on
       hover and nothing pretends to be pressable. The previous
       `::item:disabled {{ color: text }}` un-greyed the whole menu, which is
       exactly what made it read as nine dead buttons. */
    #ReadinessSystemsMenu {{
        background-color: {c['menu_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px;
        color: {c['text']};
        font-size: 12px;
    }}
    #ReadinessSystemsMenu::item {{
        padding: 4px 10px;
        border-radius: 0;
        background: transparent;
        color: {c['text_dim']};
    }}
    #ReadinessSystemsMenu::item:selected {{
        background: transparent;
        color: {c['text_dim']};
    }}
    #ReadinessSystemsMenu::item:disabled {{
        color: {c['text_dim']};
    }}
    #ReadinessSystemsCaption {{
        color: {c['dim']};
        font-size: 9px;
        font-family: {f['mono']};
        letter-spacing: 0.16em;
        background: transparent;
        padding: 4px 10px 2px 10px;
    }}
    /* Contacts is a hole in the glass on both pages — the people list and the
       card read as one layer of the plate, same as the notifications inbox.
       These containers must stay plain: a background here is only ever drawn
       because none of them sets WA_OpaquePaintEvent (see panels/contacts.py). */
    #ContactsPanel, #ContactsStack, #ContactsListPage, #ContactsCardPage,
    #ContactsCardScroll, #ContactsCardViewport, #ContactsFormHost {{
        background: transparent;
        border: none;
    }}
    /* Glass lists — no native inset wells; no H-scroll gutters.
       BrowseList is here rather than on #OutputView, which is the code editor
       rule: filenames were being set in the mono face because the workspace
       dock borrowed the editor's object name to get a transparent background. */
    #HistoryList, #FactsList, #ActiveFactsList, #NotificationsList,
    #ContactsList, #BrowseList {{
        background: transparent;
        border: none;
        outline: none;
        padding: 2px 0;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
    }}
    #BrowseList::item, #HistoryList::item, #FactsList::item,
    #ActiveFactsList::item,
    #NotificationsList::item, #ContactsList::item {{
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
    #BrowseList::item:hover, #HistoryList::item:hover, #FactsList::item:hover,
    #ActiveFactsList::item:hover,
    #NotificationsList::item:hover, #ContactsList::item:hover {{
        background: {c['row_hover']};
        border-color: transparent;
    }}
    #BrowseList::item:selected, #HistoryList::item:selected,
    #FactsList::item:selected,
    #ActiveFactsList::item:selected, #NotificationsList::item:selected,
    #ContactsList::item:selected {{
        background: {c['row_selected']};
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
    #InstrumentHint {{
        color: {c['hint']};
        font-size: 12px;
        font-family: {f['body']};
        background: transparent;
        padding: 0 0 2px 2px;
        border: none;
    }}
    #SmsChatScroll, #SmsChatThread {{
        background: {c['panel_fill']};
        border: none;
    }}
    #SmsBubbleIn {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        background: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 8px 10px;
    }}
    #SmsBubbleOut {{
        color: {c['accent2']};
        font-size: {FONT_PX}px;
        background: {c['raised_warm']};
        border: 1px solid {c['edge_mid']};
        border-radius: 10px;
        padding: 8px 10px;
    }}
    #SmsBubbleSys {{
        color: {c['text_dim']};
        font-size: 12px;
        background: transparent;
        border: none;
        padding: 4px 2px;
    }}
    #NotificationDetail {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        font-family: {f['body']};
        background: {c['raised']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 10px 12px;
    }}
    #InstrumentSearch {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 5px 8px;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
        selection-background-color: {c['selection']};
    }}
    #InstrumentSearch:focus {{
        border: 1px solid {c['accent']};
        background-color: {c['well_focus']};
    }}
    /* A picker beside a filled field has to be a filled field too, or it reads
       as an unstyled hole in the row — which is what the workspace project
       combo and the camera device combo were. Same well as #InstrumentSearch
       plus the drop-down chrome a QLineEdit rule cannot give a QComboBox. */
    #InstrumentCombo {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 2px 22px 2px 8px;
        color: {c['text']};
        font-size: 12px;
        font-family: {f['body']};
        min-height: {m['row'] - 8}px;
    }}
    #InstrumentCombo:hover {{
        border-color: {c['edge_mid']};
        background-color: {c['well_focus']};
    }}
    #InstrumentCombo:focus, #InstrumentCombo:on {{
        border: 1px solid {c['accent']};
        background-color: {c['well_focus']};
    }}
    #InstrumentCombo:disabled {{
        color: {c['text_dim']};
        border-color: {c['edge_soft']};
    }}
    #InstrumentCombo::drop-down {{
        border: none;
        width: 18px;
        subcontrol-origin: padding;
        subcontrol-position: center right;
    }}
    /* min-height rather than a fixed one: the tier belongs to the row, and a
       widget that forgets to ask for it should still land on it. */
    #InstrumentAction {{
        background-color: {c['button_fill']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 4px 10px;
        color: {c['accent2']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 400;
        min-height: {m['row'] - 12}px;
    }}
    #InstrumentAction:hover {{
        background-color: {c['button_hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #InstrumentAction:pressed {{
        background-color: {c['sunk']};
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
        background: {c['hairline_mid']};
        width: 1px;
        height: 1px;
    }}
    QDockWidget QTabBar, #DockTabBar {{
        background: transparent;
    }}
    QDockWidget QTabBar::tab, #DockTabBar::tab {{
        background-color: {c['raised']};
        color: {c['text_dim']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 5px 14px;
        font-size: 11px;
        letter-spacing: 0.06em;
        margin-right: 4px;
    }}
    QDockWidget QTabBar::tab:selected, #DockTabBar::tab:selected {{
        color: {c['accent2']};
        background-color: {c['tab_selected']};
        border-color: {c['edge_hot']};
    }}
    QDockWidget QTabBar::tab:hover, #DockTabBar::tab:hover {{
        color: {c['accent']};
        background-color: {c['hover_strong']};
        border-color: {c['edge_strong']};
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: transparent;
        border: none;
        border-radius: 10px;
        padding: 10px;
        selection-background-color: {c['selection']};
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
        selection-background-color: {c['selection']};
    }}
    #ComposerInput:focus {{
        border: none;
    }}
    #ComposerInput::placeholder {{
        color: {c['text_muted']};
    }}
    #VoidIdlePlaceholder {{
        color: {c['text_muted']};
        font-size: 16px;
        font-family: {f['body']};
        font-weight: 300;
        letter-spacing: 0.01em;
        background: transparent;
        border: none;
    }}
    QLineEdit {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 5px 10px;
        color: {c['text']};
        selection-background-color: {c['selection']};
    }}
    QLineEdit:focus {{
        border: 1px solid {c['accent']};
    }}
    QPushButton {{
        background-color: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 4px 12px;
        color: {c['text']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {c['button_hover_soft']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    QPushButton:pressed {{
        background-color: {c['sunk_soft']};
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
        background: {c['live_fill']};
        border: 1px solid {c['status_amber']};
    }}
    #StopButton {{
        background: transparent;
        border: 1px solid {c['danger_edge_soft']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['danger']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #StopButton:hover {{
        background: {c['danger_fill_soft']};
        border-color: {c['danger']};
    }}
    #RoomName {{
        color: {c['accent']};
        font-family: {f['mono']};
        font-size: 11px;
        background: transparent;
    }}
    #RoomDetail {{
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        background: transparent;
    }}
    #RoomLeaveButton {{
        background: transparent;
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #RoomLeaveButton:hover {{
        background: {c['button_hover_soft']};
        color: {c['accent']};
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
    /* Pause was the one cyan control in an amber application. It is the quiet
       half of a pair with #GoButton, so it is the same amber a step down in
       weight rather than a different colour entirely. */
    #PauseButton {{
        background: transparent;
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['hint']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #PauseButton:hover {{
        background: {c['live_fill']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #GoButton {{
        background: transparent;
        border: 1px solid {c['edge_strong']};
        border-radius: 8px;
        padding: 2px 10px;
        color: {c['accent']};
        font-family: {f['mono']};
        font-size: 11px;
    }}
    #GoButton:hover {{
        background: {c['live_fill']};
        border-color: {c['accent']};
    }}
    #ConfirmCard {{
        background-color: {c['card_fill']};
        border: 1px solid {c['rim']};
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
        background-color: {c['inset']};
        border: 1px solid {c['edge']};
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
    #ConfirmAllow, #FactApprove, #DialogConfirm {{
        min-width: 72px;
        background-color: {c['selection']};
        border: 1px solid {c['accent']};
        color: {c['text']};
        font-family: {f['body']};
        font-size: 12px;
        font-weight: 600;
    }}
    #ConfirmAllow:hover, #FactApprove:hover, #DialogConfirm:hover {{
        background-color: {c['button_hover_hot']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    /* A destructive confirm is still an amber button — the app does not have a
       red one and inventing it here would make Delete louder than Stop. The
       note above it carries the warning, in {c['danger']}. */
    #DialogConfirm[destructive="true"] {{
        background-color: {c['danger_fill_soft']};
        border-color: {c['danger_edge']};
        color: {c['text']};
    }}
    #DialogConfirm[destructive="true"]:hover {{
        background-color: {c['danger_fill']};
        border-color: {c['danger']};
        color: {c['status_white']};
    }}
    #ConfirmSkip, #FactReject, #FactRejectAll, #FactForget, #DialogCancel {{
        color: {c['text_dim']};
        font-family: {f['mono']};
        font-size: 11px;
        font-weight: 500;
        background-color: transparent;
        border: 1px solid {c['edge']};
    }}
    #ConfirmSkip:hover, #FactReject:hover, #FactRejectAll:hover,
    #FactForget:hover, #DialogCancel:hover {{
        color: {c['text']};
        border-color: {c['edge_strong']};
        background-color: {c['hover_soft']};
    }}
    #DialogCancel:focus {{
        border-color: {c['accent']};
        color: {c['text']};
    }}
    QMenu::item {{
        padding: 6px 14px;
        border-radius: 6px;
        min-height: 22px;
    }}
    QMenu::separator {{
        height: 1px;
        background: {c['edge']};
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
        selection-background-color: {c['selection_strong']};
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
        background: {c['edge_mid']};
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
        background-color: {c['menu_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
        padding: 4px;
        color: {c['text']};
    }}
    QMenu::item:selected {{
        background: {c['hover_strong']};
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
    /* Composer furniture. These three carried their colours inline, so the
       palette could be retuned without them and nobody would notice until the
       chips were on screen next to something that had moved. */
    AttachmentChip {{
        background: {c['card_fill']};
        border: 1px solid {c['edge']};
        border-radius: 10px;
    }}
    #AttachmentChipName {{
        color: {c['text']};
        font-size: 11px;
        background: transparent;
    }}
    #AttachmentChipRemove {{
        color: {c['text_dim']};
        font-size: 14px;
        border: none;
        background: transparent;
        padding: 0 2px;
    }}
    #AttachmentChipRemove:hover {{
        color: {c['accent']};
    }}
    #AttachBarScroll {{
        background: transparent;
        border: none;
    }}
    #DropOverlay {{
        background: {c['scrim']};
        border-radius: {int(GLASS['radius'])}px;
    }}
    #DropOverlayTitle {{
        color: {c['accent']};
        background: transparent;
        font-size: 18px;
    }}
    #DropOverlayHint {{
        color: {c['text_dim']};
        background: transparent;
        font-size: 12px;
    }}
    #ChatProgress {{
        color: {c['status_amber']};
        background: transparent;
        border: none;
        font-size: {FONT_PX}px;
        padding: 10px 8px;
        letter-spacing: 0.04em;
    }}
    /* Frameless in-app dialogs: first run, confirms, the update prompt. */
    #DialogHeading, #GlassDialogHeading {{
        color: {c['accent2']};
        font-family: {f['display']};
        font-size: 15px;
        font-weight: 400;
        letter-spacing: 0.08em;
        background: transparent;
        padding: 2px 0;
    }}
    #DialogBody {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        background: transparent;
    }}
    #DialogNote {{
        color: {c['text_dim']};
        font-size: 11px;
        background: transparent;
    }}
    #DialogWarning {{
        color: {c['danger']};
        font-size: 11px;
        background: transparent;
    }}
    #DialogPath {{
        color: {c['accent2']};
        font-family: {f['mono']};
        font-size: 12px;
        background: {c['well_soft']};
        border: 1px solid {c['edge_warm']};
        border-radius: 8px;
        padding: 10px 12px;
    }}
    #DialogProgress {{
        background: {c['inset']};
        border: 1px solid {c['edge']};
        border-radius: 6px;
        height: 10px;
        text-align: center;
        color: transparent;
    }}
    #DialogProgress::chunk {{
        background: {c['accent']};
        border-radius: 5px;
    }}
    #DialogButton, #DialogPrimary {{
        background: {c['button_fill']};
        color: {c['text']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        padding: 6px 18px;
        font-size: {FONT_PX}px;
    }}
    #DialogButton:hover, #DialogPrimary:hover {{
        background: {c['button_hover']};
        border-color: {c['edge_mid']};
    }}
    #DialogPrimary {{
        background: {c['raised_warm']};
        color: {c['accent2']};
        border-color: {c['edge_strong']};
    }}
    #DialogPrimary:hover {{
        background: {c['button_hover_hot']};
        border-color: {c['edge_hot']};
    }}
    /* The destroying answer is the one that has to look like it. Colour is the
       only warning left once the safe answer holds focus. */
    #DialogButton[tone="danger"] {{
        background: {c['danger_fill_soft']};
        color: {c['danger']};
        border-color: {c['danger_edge_soft']};
    }}
    #DialogButton[tone="danger"]:hover {{
        background: {c['danger_fill']};
        border-color: {c['danger_edge']};
    }}
    #DialogButton:focus, #DialogPrimary:focus {{
        border-color: {c['edge_hot']};
    }}
    """
