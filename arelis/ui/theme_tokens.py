from __future__ import annotations

# Evening room under a sodium lamp. Bright enough to read, quiet enough to sit in.
# The room shares the lamp's hue (~24-28) at low chroma: bg0 is #100d0b, a spread
# of 5 between red and blue. A wider split (the old #160d07, red 22 / blue 7)
# reads as chocolate. The lamp is #ff7a22. Body type is warm paper #f8f1ea.
# Hint and dim stay amber so secondary type belongs to the light. Filament core
# is the only cream pinprick. Harvest gold #ffb457 stays retired. Floating
# HWNDs stay opaque.

COLORS = {
    # --- the room: same hue as the lamp, low chroma ----------------------
    "bg0": "#100d0b",
    "bg1": "#2a221c",
    "bg2": "#40342b",
    "plate": "rgba(16, 13, 11, 255)",  # opaque body of a floating tool window
    "panel_fill": "rgba(22, 18, 15, 255)",  # settings pane, sms thread
    "veil": "rgba(16, 13, 11, 36)",  # barely-there wash over the atmosphere
    "scrim": "rgba(16, 13, 11, 200)",  # drop target over the live chat
    "code_fill": "rgba(10, 8, 7, 180)",  # fenced code inside a transcript bubble
    "glass": "rgba(16, 13, 11, 140)",
    "glass_strong": "rgba(18, 15, 12, 176)",
    "glass_soft": "rgba(40, 33, 27, 110)",
    "glass_fill": "rgba(16, 13, 11, 248)",
    "glass_fill_float": "rgba(16, 13, 11, 248)",
    "glass_fill_docked": "rgba(16, 13, 11, 0)",
    "glass_fill_settings": "rgba(16, 13, 11, 255)",
    "bubble_fill": "rgba(24, 20, 16, 130)",
    "bubble_wash": "rgba(20, 16, 13, 190)",  # transcript scrim behind each message
    "menu_fill": "rgba(22, 18, 15, 242)",

    # --- surfaces the light falls on ------------------------------------
    "inset": "rgba(18, 15, 12, 150)",  # sunken well inside a plate
    "well": "rgba(74, 60, 50, 255)",  # text field at rest
    "well_focus": "rgba(92, 74, 62, 255)",
    "well_soft": "rgba(74, 60, 50, 130)",
    "card_fill": "rgba(42, 34, 28, 170)",
    "raised": "rgba(58, 48, 40, 255)",
    "raised_warm": "rgba(84, 62, 46, 255)",
    "sunk": "rgba(12, 10, 8, 255)",  # pressed
    "sunk_soft": "rgba(12, 10, 8, 190)",
    "tab_selected": "rgba(132, 74, 34, 255)",
    "groove": "rgba(42, 34, 28, 180)",
    "chip": "rgba(44, 36, 30, 120)",
    "chip_solid": "rgba(44, 36, 30, 230)",
    "row_hover": "rgba(255, 122, 34, 56)",
    "row_selected": "rgba(255, 122, 34, 96)",
    "hover_soft": "rgba(255, 122, 34, 72)",
    "hover": "rgba(255, 122, 34, 110)",
    "hover_strong": "rgba(255, 122, 34, 160)",
    "button_fill": "rgba(72, 52, 38, 200)",
    "button_hover": "rgba(255, 122, 34, 190)",
    "button_hover_hot": "rgba(255, 140, 48, 220)",
    "button_hover_soft": "rgba(255, 122, 34, 130)",
    "live_fill": "rgba(255, 122, 34, 140)",  # a latched capture control
    "selection": "rgba(255, 122, 34, 170)",
    "selection_strong": "rgba(255, 122, 34, 210)",

    # --- rims: the lamp seen edge-on, visible and still soft ------------
    "rim": "rgba(255, 122, 34, 150)",
    "rim_glow": "rgba(255, 122, 34, 80)",
    "rim_pulse_min": "100",
    "rim_pulse_max": "168",
    "hairline_faint": "rgba(255, 122, 34, 64)",
    "hairline": "rgba(255, 122, 34, 100)",
    "hairline_mid": "rgba(255, 122, 34, 130)",
    "edge_soft": "rgba(255, 122, 34, 100)",
    "edge": "rgba(255, 122, 34, 140)",
    "edge_mid": "rgba(255, 122, 34, 175)",
    "edge_strong": "rgba(255, 122, 34, 205)",
    "edge_hot": "rgba(255, 122, 34, 235)",
    "edge_warm": "rgba(255, 192, 138, 140)",
    "edge_bright": "rgba(255, 192, 138, 185)",
    "catch": "rgba(255, 192, 138, 110)",

    # --- type: paper in the lamplight, amber once it steps back ---------
    "text": "#f8f1ea",
    "hint": "#e6b892",
    "thinking": "#dcb492",
    "text_dim": "#d4a484",
    "dim": "#c4906e",
    "status_white": "#f8f1ea",
    # Type that sits in the bloom. Same paper as body text, falling alpha.
    # Orange cream here is how the idle line went brown.
    "text_soft": "rgba(248, 241, 234, 220)",
    "text_muted": "rgba(248, 241, 234, 165)",
    "text_faint": "rgba(248, 241, 234, 110)",

    # --- the lamp. Gold #ffb457 stays retired. --------------------------
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

    "user_bubble": "rgba(28, 23, 19, 0)",
    "assistant_bubble": "rgba(20, 16, 13, 0)",
}

# The orbit core is the filament seen directly. Cream only here, a pinprick
# of hot metal. Halo and tick stay the sodium orange that lights the room.
FILAMENT = {
    "core": (255, 228, 204),
    "core_halo": (255, 176, 108),
    "tick": (255, 148, 56),
    "tick_halo": (255, 122, 34),
}

# Soft pool of lamp light. Alphas stay low so the evening is a room, not a
# spotlight. The falloff ends in the room color.
BLOOM = {
    "inner": (
        (0.0, (255, 150, 72, 100)),
        (0.16, (255, 122, 40, 72)),
        (0.42, (180, 78, 28, 36)),
        (0.72, (40, 24, 12, 16)),
    ),
    "outer": (
        (0.0, (255, 122, 36, 44)),
        (0.45, (90, 40, 16, 14)),
    ),
    "grain": (255, 148, 64),
    "vignette": (12, 10, 8, 64),
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
    "rim_pulse_lo": 100,
    "rim_pulse_hi": 168,
}

# Opaque float plates (calendar, contacts, notify, settings). Same lamp as
# COLORS; kept here so GlassFrame is not a second palette.
PLATE = {
    "seal": (16, 13, 11, 255),
    "body": (22, 18, 15, 255),
    "opaque": ((0.0, (84, 62, 46)), (0.36, (42, 34, 28)), (1.0, (16, 13, 11))),
    "smoked": (
        (0.0, (48, 38, 30), 20),
        (0.42, (22, 18, 15), 4),
        (1.0, (12, 10, 8), -6),
    ),
}

HAIRLINE = {"rest": 100, "live": 210}

# Control heights. Two tiers on purpose, and only two: dock furniture, and the
# composer, which is the one row that is not furniture. A third tier is how the
# workspace dock ended up with 24px buttons beside 28px ones.
METRICS = {
    "row": 28,  # search fields, dock actions, inbox buttons
    "control": 34,  # composer: role picker, attach, mic, send
    "chrome": 28,  # close / minimize on a floating plate
    "icon": 24,
}

# Space. Same rule as METRICS: few named steps, not a sitting's taste.
# 6 / 10 / 14 / 18 / 22 is how plates drifted — each edit picked a number
# that looked fine in isolation. New padding is one of these, or it is
# control_pad_y() (derived from row height + type, not chosen).
SPACE = {
    "hair": 2,  # list rows, optical nudge against a 1px stroke
    "micro": 4,  # chrome siblings, chip inset
    "gap": 8,  # default between controls / sections
    "inset": 12,  # panel body, form, dock gutter
    "plate": 16,  # float window / dialog pad
    "stage": 24,  # empty states, shortcuts, stage breath
}

# Dock gutters. Neighbors each contribute half so the visible gap is inset.
# bottom used to be 14 — the extra 2px was a sitting, not a step.
SHELL = {
    "outer": SPACE["inset"],
    "half": SPACE["inset"] // 2,
    "top": SPACE["inset"],
    "bottom": SPACE["inset"],
}

# One number for body type, shared by the QFont the application is given and by
# the stylesheet, which used to say 13px while app_font() said 10pt.
FONT_PX = 13

# Keys space_box() accepts beyond SPACE (flush is the absence of space).
_BOX = {"flush": 0, **SPACE}


def control_pad_y() -> int:
    """Vertical pad that fits FONT_PX inside METRICS.row behind a 1px border.

    (28 - 13 - 2) // 2 = 6. That 6 is not a taste. A sitting that writes
    5px is guessing the same number and missing.
    """
    return max(SPACE["hair"], (METRICS["row"] - FONT_PX - 2) // 2)


def space_box(*steps: str) -> tuple[int, int, int, int]:
    """Qt contents margins (left, top, right, bottom) from SPACE keys.

    Named this way because `box` is a Qt widget local in half the plates.
    One key = all sides. Two = x, y. Four = l, t, r, b.
    """
    vals = [_BOX[step] for step in steps]
    if len(vals) == 1:
        return (vals[0], vals[0], vals[0], vals[0])
    if len(vals) == 2:
        return (vals[0], vals[1], vals[0], vals[1])
    if len(vals) == 4:
        return (vals[0], vals[1], vals[2], vals[3])
    raise ValueError(f"space_box() takes 1, 2, or 4 steps, got {len(steps)}")


def space_allowed() -> frozenset[int]:
    """Integers a padding / margin / spacing call may use.

    0 is flush. 1 is a stroke, not a step. 6 is control_pad_y(). half is
    the dock gutter that makes two neighbors add up to inset.
    """
    return frozenset(
        {0, 1, control_pad_y(), SHELL["half"]} | set(SPACE.values())
    )

# Desk face. Files live in ui/fonts/. IBM Plex is the fallback if those
# files fail to register. Segoe / Cascadia / Consolas are the system floor.
DESK_SANS = "Zen Kaku Gothic New"
DESK_MONO = "Space Mono"

FONTS = {
    "display": f'"{DESK_SANS}", "IBM Plex Sans", "Segoe UI Semibold", "Segoe UI", sans-serif',
    "body": f'"{DESK_SANS}", "IBM Plex Sans", "Segoe UI", sans-serif',
    "mono": f'"{DESK_MONO}", "IBM Plex Mono", "Cascadia Mono", "Consolas", monospace',
}

# Body weight rides the active palette so a later room can change type
# without a second stylesheet. 400 is Regular. Light (300) at 13px drops
# the strokes on the dark plate. Tracking stays 0: Qt does not add
# letter-spacing to the text width, so any of it clips the last glyph.
TYPE = {
    "body_weight": "400",
    "track_wide": "0em",
    "track_mid": "0em",
    "track_idle": "0em",
    "track_heading": "0em",
}

# Sodium is the product. Filament is a test face (View → themes).
DEFAULT_THEME = "sodium"
_ACTIVE_THEME = DEFAULT_THEME

# Snapshot the shipped lamp so apply_theme can restore it without a rewrite.
# A new room is another entry in _PALETTES with the same token names — not a
# second stylesheet and not a hue slider. Sodium stays the default.
_SODIUM_COLORS = dict(COLORS)
_SODIUM_FILAMENT = dict(FILAMENT)
_SODIUM_BLOOM = dict(BLOOM)
_SODIUM_GLASS = dict(GLASS)
_SODIUM_PLATE = dict(PLATE)
_SODIUM_HAIRLINE = dict(HAIRLINE)
_SODIUM_TYPE = dict(TYPE)


def _filament_colors() -> dict[str, str]:
    """Charcoal void, gold type. Same token names as sodium. Float stays opaque."""
    c = dict(_SODIUM_COLORS)
    gold = (196, 160, 106)
    cream = (232, 212, 176)
    void = (7, 8, 11)
    plate = (18, 20, 26)
    well = (28, 30, 38)

    def rgba(rgb: tuple[int, int, int], a: int) -> str:
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {a})"

    def hex6(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    c.update({
        "bg0": hex6(void),
        "bg1": "#101218",
        "bg2": "#181c24",
        "plate": rgba(plate, 255),
        "panel_fill": rgba(plate, 255),
        "veil": rgba(void, 36),
        "scrim": rgba(void, 200),
        "code_fill": rgba((12, 14, 18), 180),
        "glass": rgba(void, 140),
        "glass_strong": rgba((14, 16, 22), 176),
        "glass_soft": rgba((32, 34, 42), 110),
        "glass_fill": rgba(void, 248),
        "glass_fill_float": rgba(void, 248),
        "glass_fill_docked": rgba(void, 0),
        "glass_fill_settings": rgba(void, 255),
        "bubble_fill": rgba((24, 26, 32), 130),
        "bubble_wash": rgba((20, 22, 28), 190),
        "menu_fill": rgba((22, 24, 30), 242),
        "inset": rgba((14, 16, 22), 150),
        "well": rgba(well, 255),
        "well_focus": rgba((40, 42, 52), 255),
        "well_soft": rgba(well, 130),
        "card_fill": rgba((32, 34, 42), 160),
        "raised": rgba((36, 38, 46), 255),
        "raised_warm": rgba((48, 42, 32), 255),
        "sunk": rgba((16, 18, 24), 255),
        "sunk_soft": rgba((16, 18, 24), 190),
        "tab_selected": rgba((72, 58, 36), 255),
        "groove": rgba((32, 34, 42), 170),
        "chip": rgba((40, 36, 28), 110),
        "chip_solid": rgba((40, 36, 28), 220),
        "row_hover": rgba(gold, 80),
        "row_selected": rgba(gold, 110),
        "hover_soft": rgba(gold, 110),
        "hover": rgba(gold, 150),
        "hover_strong": rgba(gold, 210),
        "button_fill": rgba((64, 52, 32), 170),
        "button_hover": rgba(gold, 210),
        "button_hover_hot": rgba((212, 168, 96), 220),
        "button_hover_soft": rgba(gold, 150),
        "live_fill": rgba(gold, 150),
        "selection": rgba(gold, 190),
        "selection_strong": rgba(gold, 210),
        "rim": rgba(gold, 110),
        "rim_glow": rgba(gold, 56),
        "hairline_faint": rgba(gold, 44),
        "hairline": rgba(gold, 68),
        "hairline_mid": rgba(gold, 88),
        "edge_soft": rgba(gold, 70),
        "edge": rgba(gold, 96),
        "edge_mid": rgba(gold, 130),
        "edge_strong": rgba(gold, 165),
        "edge_hot": rgba(gold, 210),
        "edge_warm": rgba(cream, 96),
        "edge_bright": rgba(cream, 140),
        "catch": rgba(cream, 80),
        "text": hex6(cream),
        "hint": "#d4b888",
        "thinking": "#c4a06a",
        "text_dim": "#b89468",
        "dim": "#a88858",
        "status_white": hex6(cream),
        "text_soft": rgba(cream, 200),
        "text_muted": rgba(cream, 150),
        "text_faint": rgba(cream, 96),
        "accent": "#c4a06a",
        "accent2": "#e4c896",
        "amber": "#c4a06a",
        "status_amber": "#c4a06a",
        "warn": "#d4783c",
    })
    return c


_FILAMENT_COLORS = _filament_colors()
_FILAMENT_CORE = {
    "core": (255, 236, 210),
    "core_halo": (212, 168, 96),
    "tick": (196, 160, 106),
    "tick_halo": (196, 160, 106),
}
_FILAMENT_BLOOM = {
    "inner": (
        (0.0, (196, 160, 106, 36)),
        (0.22, (120, 96, 64, 22)),
        (0.55, (40, 32, 24, 10)),
        (1.0, (7, 8, 11, 0)),
    ),
    "outer": (
        (0.0, (196, 160, 106, 18)),
        (0.5, (40, 32, 24, 8)),
    ),
    "grain": (196, 160, 106),
    "vignette": (7, 8, 11, 56),
}
_FILAMENT_PLATE = {
    "seal": (7, 8, 11, 255),
    "body": (18, 20, 26, 255),
    "opaque": ((0.0, (48, 40, 28)), (0.36, (22, 24, 30)), (1.0, (7, 8, 11))),
    "smoked": (
        (0.0, (36, 32, 24), 20),
        (0.42, (16, 18, 22), 4),
        (1.0, (7, 8, 11), -6),
    ),
}

def _night_colors() -> dict[str, str]:
    """Near-black void, brand purple ring. Same token names as sodium."""
    c = dict(_SODIUM_COLORS)
    # Measured from Arelis brand art (glowing purple ring, white star).
    void = (6, 10, 32)  # #060a20 window bg
    deep = (2, 4, 24)  # #020418
    panel = (11, 12, 38)  # #0b0c26
    panel_hi = (14, 15, 45)  # #0e0f2d
    card = (22, 20, 54)  # #161436
    border = (48, 41, 76)  # #30294c
    hover = (48, 32, 80)  # #302050
    selected = (64, 48, 96)  # #403060
    mid = (80, 64, 128)  # #504080
    pressed = (112, 80, 160)  # #7050a0
    accent = (128, 80, 176)  # #8050b0
    focus = (128, 96, 176)  # #8060b0
    # Secondary lavender-grey: ≥4.5:1 on #060a20, panel, and card (WCAG).
    lav = (144, 136, 168)  # #9088a8
    lav_dim = (132, 124, 156)  # #847c9c
    lav_faint = (122, 114, 144)  # #7a7290
    paper = (255, 255, 255)
    well = (14, 15, 45)  # #0e0f2d
    well_focus = (22, 20, 54)  # #161436

    def rgba(rgb: tuple[int, int, int], a: int) -> str:
        return f"rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {a})"

    def hex6(rgb: tuple[int, int, int]) -> str:
        return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    c.update({
        "bg0": hex6(void),
        "bg1": hex6(panel),
        "bg2": hex6(card),
        "plate": rgba(panel, 255),
        "panel_fill": rgba(panel, 255),
        "veil": rgba(void, 36),
        "scrim": rgba(deep, 200),
        "code_fill": rgba(deep, 180),
        "glass": rgba(void, 140),
        "glass_strong": rgba((7, 9, 30), 176),
        "glass_soft": rgba(panel_hi, 110),
        "glass_fill": rgba(void, 248),
        "glass_fill_float": rgba(void, 248),
        "glass_fill_docked": rgba(void, 0),
        "glass_fill_settings": rgba(void, 255),
        "bubble_fill": rgba(card, 130),
        "bubble_wash": rgba(panel, 190),
        "menu_fill": rgba(panel, 242),
        "inset": rgba(deep, 150),
        "well": rgba(well, 255),
        "well_focus": rgba(well_focus, 255),
        "well_soft": rgba(well, 130),
        "card_fill": rgba(card, 170),
        "raised": rgba(card, 255),
        "raised_warm": rgba(selected, 255),
        "sunk": rgba(deep, 255),
        "sunk_soft": rgba(deep, 190),
        "tab_selected": rgba(selected, 255),
        "groove": rgba(card, 180),
        "chip": rgba(card, 120),
        "chip_solid": rgba(card, 230),
        "row_hover": rgba(hover, 180),
        "row_selected": rgba(selected, 220),
        "hover_soft": rgba(hover, 140),
        "hover": rgba(hover, 200),
        "hover_strong": rgba(selected, 220),
        "button_fill": rgba(mid, 180),
        "button_hover": rgba(accent, 200),
        "button_hover_hot": rgba(focus, 220),
        "button_hover_soft": rgba(pressed, 160),
        "live_fill": rgba(accent, 160),
        "selection": rgba(selected, 210),
        "selection_strong": rgba(pressed, 220),
        "rim": rgba(focus, 160),
        "rim_glow": rgba(accent, 80),
        "hairline_faint": rgba(border, 100),
        "hairline": rgba(border, 160),
        "hairline_mid": rgba(border, 200),
        "edge_soft": rgba(border, 140),
        "edge": rgba(border, 200),
        "edge_mid": rgba(mid, 180),
        "edge_strong": rgba(accent, 200),
        "edge_hot": rgba(focus, 235),
        "edge_warm": rgba(lav, 140),
        "edge_bright": rgba(lav, 185),
        "catch": rgba(focus, 120),
        "text": hex6(paper),
        "hint": hex6(lav),
        "thinking": hex6(lav_dim),
        "text_dim": hex6(lav_dim),
        "dim": hex6(lav_faint),
        "status_white": hex6(paper),
        "text_soft": rgba(paper, 220),
        "text_muted": rgba(lav, 180),
        "text_faint": rgba(lav, 120),
        "accent": hex6(accent),
        "accent2": hex6(focus),
        "amber": hex6(accent),
        "status_amber": hex6(accent),
        "warn": "#b060d0",
    })
    return c


_NIGHT_COLORS = _night_colors()
_NIGHT_CORE = {
    "core": (255, 255, 255),
    "core_halo": (128, 96, 176),
    "tick": (128, 80, 176),
    "tick_halo": (112, 80, 160),
}
_NIGHT_BLOOM = {
    "inner": (
        (0.0, (128, 80, 176, 90)),
        (0.18, (112, 80, 160, 64)),
        (0.45, (64, 48, 96, 32)),
        (0.75, (6, 10, 32, 14)),
    ),
    "outer": (
        (0.0, (128, 96, 176, 40)),
        (0.5, (48, 32, 80, 12)),
    ),
    "grain": (128, 80, 176),
    "vignette": (2, 4, 24, 72),
}
_NIGHT_PLATE = {
    "seal": (6, 10, 32, 255),
    "body": (11, 12, 38, 255),
    "opaque": ((0.0, (64, 48, 96)), (0.36, (22, 20, 54)), (1.0, (6, 10, 32))),
    "smoked": (
        (0.0, (48, 32, 80), 20),
        (0.42, (11, 12, 38), 4),
        (1.0, (2, 4, 24), -6),
    ),
}

_PALETTES = {
    "sodium": {
        "colors": _SODIUM_COLORS,
        "filament": _SODIUM_FILAMENT,
        "bloom": _SODIUM_BLOOM,
        "glass": _SODIUM_GLASS,
        "plate": _SODIUM_PLATE,
        "hairline": _SODIUM_HAIRLINE,
        "type": _SODIUM_TYPE,
    },
    "filament": {
        "colors": _FILAMENT_COLORS,
        "filament": _FILAMENT_CORE,
        "bloom": _FILAMENT_BLOOM,
        "glass": dict(_SODIUM_GLASS),
        "plate": _FILAMENT_PLATE,
        "hairline": dict(_SODIUM_HAIRLINE),
        "type": dict(_SODIUM_TYPE),
    },
    "night": {
        "colors": _NIGHT_COLORS,
        "filament": _NIGHT_CORE,
        "bloom": _NIGHT_BLOOM,
        "glass": dict(_SODIUM_GLASS),
        "plate": _NIGHT_PLATE,
        "hairline": dict(_SODIUM_HAIRLINE),
        "type": dict(_SODIUM_TYPE),
    },
}

THEME_IDS = tuple(_PALETTES)
_THEME_LABELS = {
    "sodium": "sodium",
    "filament": "filament (testing)",
    "night": "night",
}
THEME_CHOICES = tuple((tid, _THEME_LABELS.get(tid, tid)) for tid in THEME_IDS)

_THEME_ALIASES = {
    "default": "sodium",
    "dark": "sodium",
    "lamp": "sodium",
}


def resolve_theme_id(value: str | None) -> str:
    """Known room, or sodium. Unknown names do not invent a palette."""
    raw = (value or "").strip().lower()
    if raw in _PALETTES:
        return raw
    return _THEME_ALIASES.get(raw, DEFAULT_THEME)


def active_theme() -> str:
    return _ACTIVE_THEME


def theme_from_config(config: dict | None) -> str:
    ui = (config or {}).get("ui") or {}
    return resolve_theme_id(str(ui.get("theme") or DEFAULT_THEME))


def _install_palette(theme_id: str) -> None:
    pal = _PALETTES[theme_id]
    COLORS.clear()
    COLORS.update(pal["colors"])
    FILAMENT.clear()
    FILAMENT.update(pal["filament"])
    BLOOM.clear()
    BLOOM.update(pal["bloom"])
    GLASS.clear()
    GLASS.update(pal["glass"])
    PLATE.clear()
    PLATE.update(pal["plate"])
    HAIRLINE.clear()
    HAIRLINE.update(pal["hairline"])
    TYPE.clear()
    TYPE.update(pal["type"])

