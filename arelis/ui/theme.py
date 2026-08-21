from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

from arelis.paths import cache_dir, ensure

log = logging.getLogger(__name__)

# Orbit void — sodium lamp in a dark room. Exposure is locked: do not chase
# brightness here. The last pass was gold (#ffb457, hue ~33) and read as yellow.
# This lock is hue. The filament pinprick can be cream; everything it throws
# (rims, type, bloom, chrome) stays orange-amber (~22-26), like high-pressure
# sodium at night. Darker is still orange, not chocolate-red. Floating HWNDs
# stay opaque.

COLORS = {
    # --- the void -------------------------------------------------------
    "bg0": "#160d07",
    "bg1": "#221408",
    "bg2": "#321c0e",
    "plate": "rgba(22, 13, 7, 255)",  # opaque body of a floating tool window
    "panel_fill": "rgba(32, 20, 10, 255)",  # settings pane, sms thread
    "veil": "rgba(22, 13, 7, 36)",  # barely-there wash over the atmosphere
    "scrim": "rgba(22, 13, 7, 200)",  # drop target over the live chat
    "code_fill": "rgba(16, 10, 6, 180)",  # fenced code inside a transcript bubble
    "glass": "rgba(22, 13, 7, 140)",
    "glass_strong": "rgba(26, 16, 8, 176)",
    "glass_soft": "rgba(40, 24, 12, 110)",
    "glass_fill": "rgba(22, 13, 7, 248)",
    "glass_fill_float": "rgba(22, 13, 7, 248)",
    "glass_fill_docked": "rgba(22, 13, 7, 0)",
    "glass_fill_settings": "rgba(22, 13, 7, 255)",
    "bubble_fill": "rgba(28, 16, 8, 130)",
    "bubble_wash": "rgba(24, 14, 8, 120)",  # transcript bubbles, written as HTML
    "menu_fill": "rgba(30, 18, 10, 242)",

    # --- surfaces the light falls on ------------------------------------
    "inset": "rgba(26, 16, 8, 150)",  # sunken well inside a plate
    "well": "rgba(38, 22, 12, 255)",  # text field at rest
    "well_focus": "rgba(52, 30, 14, 255)",
    "well_soft": "rgba(40, 24, 12, 130)",
    "card_fill": "rgba(42, 24, 12, 160)",
    "raised": "rgba(46, 26, 12, 255)",
    "raised_warm": "rgba(64, 36, 16, 255)",
    "sunk": "rgba(28, 16, 8, 255)",  # pressed
    "sunk_soft": "rgba(28, 16, 8, 190)",
    "tab_selected": "rgba(88, 50, 18, 255)",
    "groove": "rgba(42, 24, 12, 170)",
    "chip": "rgba(48, 28, 12, 110)",
    "chip_solid": "rgba(48, 28, 12, 220)",
    "row_hover": "rgba(90, 50, 18, 80)",
    "row_selected": "rgba(110, 60, 20, 110)",
    "hover_soft": "rgba(90, 50, 18, 110)",
    "hover": "rgba(90, 50, 18, 150)",
    "hover_strong": "rgba(120, 66, 22, 210)",
    "button_fill": "rgba(80, 44, 16, 170)",
    "button_hover": "rgba(120, 66, 22, 210)",
    "button_hover_hot": "rgba(160, 86, 28, 220)",
    "button_hover_soft": "rgba(100, 56, 20, 150)",
    "live_fill": "rgba(140, 76, 24, 150)",  # a latched capture control
    "selection": "rgba(140, 76, 24, 190)",
    "selection_strong": "rgba(150, 82, 26, 210)",

    # --- rims: the filament seen edge-on --------------------------------
    "rim": "rgba(255, 122, 34, 110)",
    "rim_glow": "rgba(255, 122, 34, 56)",
    "rim_pulse_min": "68",
    "rim_pulse_max": "128",
    "hairline_faint": "rgba(255, 122, 34, 44)",
    "hairline": "rgba(255, 122, 34, 68)",
    "hairline_mid": "rgba(255, 122, 34, 88)",
    "edge_soft": "rgba(255, 122, 34, 70)",
    "edge": "rgba(255, 122, 34, 96)",
    "edge_mid": "rgba(255, 122, 34, 130)",
    "edge_strong": "rgba(255, 122, 34, 165)",
    "edge_hot": "rgba(255, 122, 34, 210)",
    "edge_warm": "rgba(255, 192, 138, 96)",
    "edge_bright": "rgba(255, 192, 138, 140)",
    "catch": "rgba(255, 192, 138, 80)",

    # --- type: sodium-lit, still bright — hue shift, not a dimmer --------
    "text": "#fae8dc",
    "hint": "#f0c7a8",
    "thinking": "#e4b596",
    "text_dim": "#d8a482",
    "dim": "#c4906e",
    "status_white": "#fae8dc",
    # Type that sits *in* the bloom rather than on a plate. Orange cream,
    # not lemon — cream over the void is how the idle line went yellow.
    "text_soft": "rgba(255, 210, 160, 200)",
    "text_muted": "rgba(255, 210, 160, 150)",
    "text_faint": "rgba(255, 210, 160, 96)",

    # --- the light itself: sodium orange, not harvest gold --------------
    "accent": "#ff7a22",
    "accent2": "#ffc08a",
    "amber": "#ff7a22",
    "status_amber": "#ff7a22",
    # Attention without leaving the family: hotter and redder than the accent,
    # so a warn chip is not the same pixel value as an ok one.
    "warn": "#ff5e12",

    # --- alarm: the one thing allowed off the ramp ----------------------
    "danger": "#F0A0A8",
    "danger_edge_soft": "rgba(240, 160, 168, 90)",
    "danger_edge": "rgba(240, 160, 168, 120)",
    "danger_fill_soft": "rgba(120, 40, 50, 120)",
    "danger_fill": "rgba(160, 60, 70, 180)",
    "danger_wash": "rgba(40, 16, 22, 90)",

    "user_bubble": "rgba(36, 24, 14, 0)",
    "assistant_bubble": "rgba(28, 18, 10, 0)",
}

# The orbit core is the filament seen directly rather than the glow it throws.
# Cream only here — a pinprick of hot metal. The halo and tick are the sodium
# orange the rest of the room is made of.
FILAMENT = {
    "core": (255, 220, 175),
    "core_halo": (255, 170, 100),
    "tick": (255, 140, 50),
    "tick_halo": (255, 122, 34),
}

# Same exposure as the last pass (alphas stay). Hue is what changed: gold
# bloom was the yellow wash across the stage.
BLOOM = {
    "inner": (
        (0.0, (255, 150, 72, 92)),
        (0.16, (255, 120, 40, 62)),
        (0.42, (200, 80, 24, 32)),
        (0.72, (96, 36, 10, 12)),
    ),
    "outer": (
        (0.0, (255, 118, 36, 40)),
        (0.38, (140, 50, 14, 18)),
    ),
    "grain": (255, 148, 64),
    "vignette": (16, 8, 3, 48),
}

# Floating must stay opaque: WA_TranslucentBackground on a separate HWND
# otherwise composites the real chat through the plate (the "ghost chat" bug).
# Docked/stage can stay lighter — they share the main window surface.
GLASS = {
    "fill_docked": 0,  # docked instruments are type in the void, not amber TVs
    "fill_float": 255,  # opaque plate; void is a color, not a transparent HWND
    "fill_stage": 0,
    "fill_settings": 255,
    "fill_strip": 120,  # room / chrome-drive banners over the void
    "radius": 12.0,
    "radius_stage": 12.0,
    "rim_pulse_seconds": 6.0,
    "rim_pulse_lo": 68,
    "rim_pulse_hi": 128,
}

# Opaque float plates (calendar, contacts, notify, settings). Same lamp as
# COLORS; kept here so GlassFrame is not a second palette.
PLATE = {
    "seal": (22, 13, 7, 255),
    "body": (34, 20, 10, 255),
    "opaque": ((0.0, (86, 40, 12)), (0.36, (40, 22, 10)), (1.0, (22, 13, 7))),
    "smoked": (
        (0.0, (56, 32, 14), 20),
        (0.42, (28, 16, 9), 4),
        (1.0, (18, 11, 7), -6),
    ),
}

HAIRLINE = {"rest": 68, "live": 200}

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
    #SettingsGlass, #NotifyInboxGlass, #CalendarWindowGlass, #NotifyCard,
    #DriveStrip, #RoomStrip, #ChatEmpty, #VoidPromptHost,
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
    #GlassDialog, #CalendarWindow {{
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
    #SettingsPairQr {{
        background: {c['text']};
        border-radius: 12px;
    }}
    #SettingsSection {{
        color: {c['accent2']};
        font-size: 13px;
        font-weight: 600;
        background: transparent;
        padding-top: 6px;
    }}
    #SettingsFieldLabel {{
        color: {c['text']};
        font-size: 13px;
        background: transparent;
        padding-right: 8px;
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
    #CalendarTabs {{
        background: transparent;
        border: none;
    }}
    #CalendarTabs::pane {{
        border: none;
        background: transparent;
        top: 6px;
        padding: 0;
    }}
    #CalendarTabBody, #CalendarTasksPage, #CalendarJobsPage, #CalendarEventSheet {{
        background: transparent;
        border: none;
    }}
    #CalendarTabs QTabBar {{
        background: transparent;
    }}
    #CalendarTabs QTabBar::tab {{
        background-color: {c['raised']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text_dim']};
        padding: 6px 14px;
        margin-right: 6px;
        min-width: 52px;
    }}
    #CalendarTabs QTabBar::tab:hover {{
        color: {c['accent']};
        border-color: {c['edge_strong']};
        background: {c['hover']};
    }}
    #CalendarTabs QTabBar::tab:selected {{
        color: {c['accent2']};
        border-color: {c['edge_hot']};
        background: {c['tab_selected']};
    }}
    #CalendarMonthTitle {{
        color: {c['accent2']};
        font-size: 15px;
        font-family: {f['display']};
        letter-spacing: 0.04em;
        background: transparent;
        padding: 0 8px;
    }}
    #CalendarDate, #CalendarTime {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        padding: 2px 8px;
        font-size: 12px;
        font-family: {f['body']};
        min-height: {m['row'] - 8}px;
    }}
    #CalendarDate:focus, #CalendarTime:focus {{
        border: 1px solid {c['accent']};
        background-color: {c['well_focus']};
    }}
    #CalendarAgendaList, #CalendarTaskList, #CalendarJobList {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        outline: none;
        padding: 4px;
    }}
    #CalendarAgendaList::item, #CalendarTaskList::item, #CalendarJobList::item {{
        color: {c['text']};
        padding: 6px 8px;
        border-radius: 6px;
    }}
    #CalendarAgendaList::item:selected, #CalendarTaskList::item:selected, #CalendarJobList::item:selected {{
        background-color: {c['tab_selected']};
        color: {c['accent2']};
    }}
    #CalendarAgendaList::item:hover, #CalendarTaskList::item:hover, #CalendarJobList::item:hover {{
        background-color: {c['hover_strong']};
        color: {c['accent']};
    }}
    #CalendarTaskTitle {{
        color: {c['text']};
        background: transparent;
        font-size: {FONT_PX}px;
        font-family: {f['body']};
    }}
    #CalendarJobPrompt {{
        background-color: {c['well']};
        border: 1px solid {c['edge']};
        border-radius: 8px;
        color: {c['text']};
        padding: 6px 8px;
        font-size: {FONT_PX}px;
        font-family: {f['body']};
    }}
    #CalendarDelete {{
        background-color: {c['danger_fill_soft']};
        border: 1px solid {c['danger_edge_soft']};
        color: {c['danger']};
    }}
    #CalendarDelete:hover {{
        background-color: {c['danger_fill']};
        border-color: {c['danger_edge']};
        color: {c['danger']};
    }}
    #CalendarEventSheet QLabel, #CalendarJobsPage QLabel {{
        color: {c['text_dim']};
        background: transparent;
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
    /* The row is 28px including the 1px border. min/max here are the
       content box — padding used to steal another 8px and land on 26. */
    #InstrumentAction {{
        background-color: {c['button_fill']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 0px 10px;
        color: {c['accent2']};
        font-size: 11px;
        font-family: {f['mono']};
        font-weight: 400;
        min-height: {m['row'] - 2}px;
        max-height: {m['row'] - 2}px;
    }}
    #InstrumentAction:hover {{
        background-color: {c['button_hover']};
        border-color: {c['accent']};
        color: {c['accent']};
    }}
    #InstrumentAction:pressed {{
        background-color: {c['sunk']};
    }}
    /* Square siblings of #InstrumentAction. Padding 0 so the glyph sits
       in the same 28px row without the word-button's horizontal inset. */
    QToolButton#InstrumentIcon {{
        background-color: {c['button_fill']};
        border: 1px solid {c['edge_mid']};
        border-radius: 8px;
        padding: 0px;
        color: {c['accent2']};
        min-width: {m['row'] - 2}px;
        max-width: {m['row'] - 2}px;
        min-height: {m['row'] - 2}px;
        max-height: {m['row'] - 2}px;
    }}
    QToolButton#InstrumentIcon:hover {{
        background-color: {c['button_hover']};
        border-color: {c['accent']};
    }}
    QToolButton#InstrumentIcon:pressed {{
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
    #Editor {{
        font-family: {f['mono']};
        font-size: 12px;
        background-color: transparent;
        border: none;
        border-radius: 0;
        color: {c['text']};
        padding: 8px 2px;
    }}
    #OutputView {{
        font-family: {f['mono']};
        font-size: 12px;
        background-color: transparent;
        border: none;
        border-top: 1px solid {c['hairline_faint']};
        border-radius: 0;
        color: {c['text_dim']};
        padding: 6px 2px;
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
        text-decoration: none;
    }}
    #ChatProgress:hover {{
        color: {c['accent2']};
        text-decoration: none;
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
    #SetupChoice {{
        color: {c['text']};
        font-size: {FONT_PX}px;
        spacing: 10px;
        padding: 4px 0;
        background: transparent;
    }}
    #SetupChoice::indicator {{
        width: 14px;
        height: 14px;
        border-radius: 7px;
        border: 1px solid {c['edge_mid']};
        background: {c['inset']};
    }}
    #SetupChoice::indicator:checked {{
        background: {c['accent']};
        border-color: {c['edge_hot']};
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
