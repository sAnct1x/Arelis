from __future__ import annotations

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
        (0.16, (255, 122, 40, 70)),
        (0.42, (200, 84, 26, 40)),
        (0.72, (96, 38, 12, 18)),
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

# Tracking and body weight ride the active palette so a later room can
# change type without a second stylesheet.
TYPE = {
    "body_weight": "300",
    "track_wide": "0.14em",
    "track_mid": "0.12em",
    "track_idle": "0.16em",
    "track_heading": "0.08em",
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
        "bubble_wash": rgba((20, 22, 28), 120),
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
}

THEME_IDS = tuple(_PALETTES)
_THEME_LABELS = {
    "sodium": "sodium",
    "filament": "filament (testing)",
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

