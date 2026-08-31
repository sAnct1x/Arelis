"""Filament room: palette, field, voice grant. Sodium stays the default."""

from __future__ import annotations

from datetime import UTC

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import QPushButton

from arelis.tools.policy import (
    action_is_delete,
    action_is_destructive,
    confirm_mode,
    evaluate_confirm,
    set_confirm_mode,
)
from arelis.ui.filament_field import (
    FLOATS,
    FilamentField,
    _union_desks,
    choose_span_desks,
    chrome_band_on_glass,
    clamp_filament_span,
    filament_work_region,
    home_band_from_union,
    home_band_in_window,
)
from arelis.ui.theme import COLORS, THEME_IDS, active_theme, apply_theme, color


def test_tile_opacity_clamps_and_loads() -> None:
    from arelis.ui.filament_tile import (
        clamp_opacity,
        load_opacities,
        load_tile_origins,
        load_tile_sizes,
    )

    assert clamp_opacity(0.01) == 0.15
    assert clamp_opacity(2.0) == 1.0
    assert clamp_opacity(0.8) == 0.8
    loaded = load_opacities({"ui": {"filament_opacity": {"history": 0.4, "bad": "x"}}})
    assert loaded["history"] == 0.4
    assert "bad" not in loaded
    sizes = load_tile_sizes(
        {"ui": {"filament_tile_size": {"history": {"w": 280, "h": 220}, "bad": 1}}}
    )
    assert sizes["history"] == (280, 220)
    assert "bad" not in sizes
    origins = load_tile_origins(
        {
            "ui": {
                "filament_tile_pos": {
                    "history": {"x": -2560, "y": 80},
                    "chat": {"x": 140, "y": 90},
                    "bad": 1,
                }
            }
        }
    )
    assert origins["history"] == (-2560, 80)
    assert origins["chat"] == (140, 90)
    assert "bad" not in origins


def test_filament_is_a_theme() -> None:
    assert "sodium" in THEME_IDS
    assert "filament" in THEME_IDS
    apply_theme("filament")
    assert active_theme() == "filament"
    assert COLORS["accent"].lower() == "#c4a06a"
    assert confirm_mode() == "voice"
    apply_theme("sodium")
    assert active_theme() == "sodium"
    assert COLORS["accent"].lower() == "#ff7a22"
    hue = color("accent").hueF() * 360
    assert 18 <= hue <= 28
    assert confirm_mode() == "card"


def test_voice_grant_only_pauses_on_delete() -> None:
    set_confirm_mode("voice")
    try:
        assert action_is_delete("agenda", {"action": "delete"})
        assert action_is_delete("rooms", {"action": "forget"})
        assert action_is_delete("inbox", {"action": "trash"})
        assert action_is_delete("workspace", {"action": "delete"})
        assert not action_is_delete("workspace", {"action": "write"})
        assert not action_is_delete("send_sms", {})
        assert action_is_destructive("browser", {"action": "click", "text": "Pay now"})
        assert not action_is_destructive("browser", {"action": "open", "url": "youtube"})
        assert evaluate_confirm("agenda", {"action": "delete"}, risk="read")
        assert evaluate_confirm(
            "browser", {"action": "click", "text": "Checkout"}, risk="side_effect"
        )
        assert not evaluate_confirm("workspace", {"action": "write"}, risk="read")
        assert not evaluate_confirm("send_sms", {}, risk="side_effect")
        assert not evaluate_confirm("image", {"prompt": "x"}, risk="side_effect")
        assert not evaluate_confirm(
            "browser", {"action": "open", "url": "youtube"}, risk="side_effect"
        )
    finally:
        set_confirm_mode("card")


def test_filament_field_paints(qt_app) -> None:
    field = FilamentField()
    field.set_state("speak")
    field.set_span(1)
    for _ in range(10):
        field.tick(0.033)
    pix = QPixmap(640, 360)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    field.paint(painter, pix.rect())
    painter.end()
    assert pix.width() == 640
    corner = QColor(pix.toImage().pixelColor(2, 2))
    assert corner.red() < 24 and corner.green() < 24 and corner.blue() < 24
    band = field.hit_band(pix.rect())
    assert abs(band.center().y() - int(360 * 0.40)) < 24
    assert abs(band.center().x() - 320) < 20
    assert field.shape_region(pix.rect(), []).contains(pix.rect().center())
    cx, cy, _rx, ry = field.ellipse(pix.rect())
    assert abs(cx - 320) < 2
    prompt = field.prompt_point(pix.rect())
    assert prompt.y() > cy + ry + 40
    assert abs(prompt.x() - cx) < 2
    lit = False
    for x in range(180, 460, 6):
        sample = QColor(pix.toImage().pixelColor(x, int(360 * 0.40)))
        if sample.red() + sample.green() + sample.blue() > 80:
            lit = True
            break
    assert lit


def test_dust_rides_every_strand() -> None:
    field = FilamentField()
    strands = {int(d["strand"]) for d in field.dust}
    assert strands == {0, 1, 2, 3}
    assert any(d["hot"] for d in field.dust)
    assert not all(d["hot"] for d in field.dust)


def test_ask_stays_on_the_home_desk() -> None:
    field = FilamentField()
    field.set_span(3, desk_left=2560, desk_width=2560)
    rect = QRect(0, 0, 7680, 1440)
    home = field.home_rect(rect)
    assert home.x() == 2560
    assert home.width() == 2560
    prompt = field.prompt_point(rect)
    assert home.left() <= prompt.x() <= home.right()


def test_awake_field_unwraps() -> None:
    field = FilamentField()
    field.set_state("awake")
    for _ in range(80):
        field.tick(0.033)
    assert field.form > 0.7
    assert field.state == "awake"


def test_span_choice_grows_and_shrinks() -> None:
    home = QRect(2560, 0, 2560, 1440)
    row = [QRect(0, 0, 2560, 1440), home, QRect(5120, 0, 2560, 1440)]
    assert clamp_filament_span("2") == 2
    assert clamp_filament_span("nope") == 1
    one = choose_span_desks(row, home, 1)
    assert len(one) == 1 and one[0].x() == 2560
    two = choose_span_desks(row, home, 2)
    assert [g.x() for g in two] == [2560, 5120]
    three = choose_span_desks(row, home, 3)
    assert [g.x() for g in three] == [0, 2560, 5120]
    assert choose_span_desks(row, home, 1)[0].width() == 2560
    # Taskbar / availableGeometry insets must not drop home to the leftmost desk.
    drifted = QRect(2564, 32, 2552, 1400)
    assert [g.x() for g in choose_span_desks(row, drifted, 1)] == [2560]
    assert [g.x() for g in choose_span_desks(row, drifted, 2)] == [2560, 5120]
    assert [g.x() for g in choose_span_desks(row, drifted, 3)] == [0, 2560, 5120]
    # 2 never borrows the left desk. Sequential: 3 → 2 → 1 drops left, then right.
    assert [g.x() for g in choose_span_desks(row, home, 3)] == [0, 2560, 5120]
    assert [g.x() for g in choose_span_desks(row, home, 2)] == [2560, 5120]
    assert [g.x() for g in choose_span_desks(row, home, 1)] == [2560]
    rightmost = QRect(5120, 0, 2560, 1440)
    assert [g.x() for g in choose_span_desks(row, rightmost, 2)] == [5120]
    # Primary at 0, left desk has a negative origin — Windows often looks like this.
    origin_home = QRect(0, 0, 2560, 1440)
    origin_row = [QRect(-2560, 0, 2560, 1440), origin_home, QRect(2560, 0, 2560, 1440)]
    assert [g.x() for g in choose_span_desks(origin_row, origin_home, 2)] == [0, 2560]
    three_origin = choose_span_desks(origin_row, origin_home, 3)
    assert [g.x() for g in three_origin] == [-2560, 0, 2560]
    union = three_origin[0].united(three_origin[1]).united(three_origin[2])
    assert union.x() == -2560
    assert union.width() == 7680
    band = home_band_from_union(union, origin_home)
    assert band.x() == 2560
    assert band.width() == 2560
    two_union = QRect(0, 0, 5120, 1440)
    assert home_band_from_union(two_union, origin_home).x() == 0
    # This desk: left monitor is 74px higher. Bar at local y=0 is in the gap.
    raised = QRect(-2560, -74, 7680, 1466)
    stepped = home_band_from_union(raised, origin_home)
    assert stepped.x() == 2560
    assert stepped.y() == 74
    glass = QRect(0, 0, 7680, 1466)
    chrome = chrome_band_on_glass(raised, origin_home, glass)
    assert chrome.x() == 2560
    assert chrome.y() == 74
    assert chrome.height() == 32
    missed = chrome_band_on_glass(raised, origin_home, QRect(0, 0, 2560, 1440))
    assert missed.x() == 0
    assert missed.width() >= 320
    assert missed.right() <= 2560
    # Span is the real union — left at y=-74 must be covered, not cropped.
    flush = _union_desks(
        [QRect(-2560, -74, 2560, 1392), origin_home, QRect(2560, -1, 2560, 1392)],
        origin_home,
    )
    assert flush.x() == -2560
    assert flush.y() == -74
    assert flush.width() == 7680
    assert flush.bottom() >= origin_home.bottom()
    assert home_band_from_union(flush, origin_home).y() == 74
    left_desk = QRect(-2560, -74, 2560, 1392)
    home_desk = QRect(0, 0, 2560, 1392)
    right_desk = QRect(2560, -1, 2560, 1392)
    span = _union_desks([left_desk, home_desk, right_desk], home_desk)
    work = filament_work_region(span, [left_desk, home_desk, right_desk])
    # Bounding box hangs over the left taskbar; work area does not.
    assert not work.contains(QPoint(100, span.height() - 10))
    assert work.contains(QPoint(2560 + 100, span.height() - 10))
    assert work.contains(QPoint(100, 80))


def test_place_frameless_rect_does_not_need_pyside_max(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui.window_resize import place_frameless_rect

    host = QWidget()
    try:
        host.show()
        assert host.windowHandle() is not None
        assert place_frameless_rect(host, QRect(40, 40, 640, 400))
        geo = host.geometry()
        assert geo.width() == 640
        assert geo.height() == 400
        # 2→3: origin jumps left and width grows. Offscreen may not honor
        # the x, but QWindow.setMinimumSize(QSize) must not throw.
        place_frameless_rect(host, QRect(-200, 40, 840, 400))
        grown = host.geometry()
        assert grown.height() == 400
        assert grown.width() >= 400
    finally:
        host.deleteLater()


def test_step_rects_grows_left_then_right() -> None:
    from arelis.ui.window_resize import _step_rects

    two = QRect(0, 0, 5120, 1440)
    three = QRect(-2560, 0, 7680, 1440)
    left = _step_rects(two, three)
    assert left[0] == QRect(-2560, 0, 5120, 1440)
    assert left[-1] == three
    right = _step_rects(three, two)
    assert right[0] == QRect(-2560, 0, 5120, 1440)
    assert right[-1] == two
    grow_right = _step_rects(QRect(0, 0, 2560, 1440), QRect(0, 0, 5120, 1440))
    assert grow_right == [QRect(0, 0, 5120, 1440)]


def test_edge_fade_stays_real() -> None:
    field = FilamentField()
    assert field._edge_fade(-80, 2560, 0) == 0.0
    assert field._edge_fade(3000, 2560, 0) == 0.0
    assert field._edge_fade(1280, 2560, 0) == 1.0
    # Failed 3-span left the coil aimed past a one-desk HWND; paint died.
    field.set_span(3, desk_left=2560, desk_width=2560)
    pix = QPixmap(2560, 400)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    field.paint(painter, pix.rect())
    painter.end()
    void = QColor(pix.toImage().pixelColor(2, 2))
    assert void.red() < 24 and void.green() < 24 and void.blue() < 24


def test_home_band_is_the_primary_overlap(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui.window_resize import _native_place_rect

    host = QWidget()
    host.setGeometry(-2560, 0, 7680, 1440)
    home = QRect(0, 0, 2560, 1440)
    band = home_band_in_window(host, home)
    if band.isValid() and band.width() >= 280:
        assert band.x() >= 0
        assert band.width() >= 280
        assert band.right() <= host.width() + 8
    nx, ny, nw, nh = _native_place_rect(union_rect := QRect(-2560, 0, 7680, 1440), 1.0)
    assert (nx, ny, nw, nh) == (-2560, 0, 7680, 1440)
    scaled = _native_place_rect(union_rect, 1.25)
    assert scaled[2] == round(7680 * 1.25)
    assert scaled[0] == round(-2560 * 1.25)
    host.deleteLater()


def test_home_band_empty_when_hwnd_misses_home(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    host.setGeometry(-2560, 0, 2560, 1440)
    missed = home_band_in_window(host, QRect(0, 0, 2560, 1440))
    assert not missed.isValid() or missed.width() < 280
    host.deleteLater()


def test_unwrapped_current_fills_one_desk() -> None:
    field = FilamentField()
    field.set_state("awake")
    field.set_span(1)
    field.form = 1.0
    rect = QRect(0, 0, 2560, 1440)
    assert field._desk_width(2560) == 2560
    left = field._point(0.04, 2.0, rect)
    right = field._point(0.96, 2.0, rect)
    assert right.x() - left.x() > 2100
    _cx, _cy, rx, _ry = field.ellipse(rect)
    assert rx > 500


def test_two_desks_keep_the_coil_on_home() -> None:
    field = FilamentField()
    field.set_state("awake")
    field.set_span(2, desk_left=0, desk_width=2560)
    field.form = 1.0
    rect = QRect(0, 0, 5120, 1440)
    cx, _cy, _rx, _ry = field.ellipse(rect)
    assert abs(cx - 1280) < 4
    right = field._point(0.92, 2.0, rect)
    assert right.x() > 4500


def test_three_desks_unwrap_across_the_row() -> None:
    field = FilamentField()
    field.set_state("awake")
    field.set_span(3, desk_left=2560, desk_width=2560)
    field.form = 1.0
    rect = QRect(0, 0, 7680, 1440)
    assert abs(field._desk_width(7680) - 2560) < 1
    cx, _cy, _rx, _ry = field.ellipse(rect)
    assert abs(cx - 3840) < 4
    hist = field.title_point("history", rect)
    files = field.title_point("files", rect)
    assert hist.x() < 2560
    assert files.x() > 5120
    for name in ("history", "notify", "contacts"):
        assert field.title_point(name, rect).x() < 2560
    for name in ("chat", "thinking", "camera"):
        x = field.title_point(name, rect).x()
        assert 2560 <= x < 5120
    for name in ("days", "files", "rooms"):
        assert field.title_point(name, rect).x() > 5120
    lure = field.bead_point("reality", rect)
    home = field.home_rect(rect)
    assert home.contains(lure.toPoint())
    from arelis.ui.filament_field import _REALITY_MARGIN, _REALITY_RINGS, _REALITY_RX, _REALITY_RY

    reach_x = _REALITY_RX * _REALITY_RINGS[-1]
    reach_y = _REALITY_RY * _REALITY_RINGS[-1]
    right_glass = home.right() - lure.x() - reach_x
    bottom_glass = home.bottom() - lure.y() - reach_y
    assert abs(right_glass - _REALITY_MARGIN) < 8
    assert abs(bottom_glass - _REALITY_MARGIN) < 8
    assert abs(right_glass - bottom_glass) < 8
    left = field._point(0.06, 2.0, rect)
    right = field._point(0.94, 2.0, rect)
    assert right.x() - left.x() > 6400


def test_each_tile_has_a_bead_on_the_current() -> None:
    field = FilamentField()
    field.set_state("idle")
    rect = QRect(0, 0, 800, 600)
    points = [field.bead_point(name, rect) for name, _t, _pad in FLOATS]
    for i, a in enumerate(points):
        for b in points[i + 1 :]:
            assert (a - b).manhattanLength() > 8
    start = field.bead_point("chat", rect)
    for _ in range(90):
        field.tick(0.033)
    moved = field.bead_point("chat", rect)
    assert (start - moved).manhattanLength() > 10
    bead = field.bead_point("history", rect)
    ring = field.anchor_point("history", rect)
    assert (bead - ring).manhattanLength() > 12
    hit = field.hit_float(bead.toPoint(), rect)
    assert hit == "history"


def test_titles_orbit_the_idle_coil() -> None:
    field = FilamentField()
    field.set_state("idle")
    rect = QRect(0, 0, 800, 600)
    start = field.title_point("history", rect)
    for _ in range(90):
        field.tick(0.033)
    moved = field.title_point("history", rect)
    assert (start - moved).manhattanLength() > 10
    anchor = field.anchor_point("history", rect)
    title = field.title_point("history", rect)
    assert (anchor - title).manhattanLength() > 20


def test_thinking_title_breathes_while_a_turn_runs() -> None:
    field = FilamentField()
    field.set_live_faces({"thinking"})
    assert field.is_live("thinking")
    assert not field.is_live("chat")
    first = field.live_breath()
    for _ in range(50):
        field.tick(0.033)
    assert field.live_breath() != first
    field.set_live_faces(set())
    assert not field.is_live("thinking")


def test_tether_grows_toward_a_plate() -> None:
    field = FilamentField()
    assert field.tether_grow("chat") == 0.0
    field.bind_tether("chat", QPointF(520, 380))
    for _ in range(40):
        field.tick(0.033)
    assert field.tether_grow("chat") > 0.6
    field.bind_tether("chat", None)
    for _ in range(40):
        field.tick(0.033)
    assert field.tether_grow("chat") < 0.15


def test_filament_restyles_the_window(arelis_window) -> None:
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    assert active_theme() == "filament"
    assert "#c4a06a" in window.styleSheet()
    apply_window_theme(window, "sodium", persist=False)
    assert active_theme() == "sodium"
    assert COLORS["accent"].lower() == "#ff7a22"


def test_view_menu_lists_filament(arelis_window) -> None:
    window = arelis_window()
    assert "filament" in window._theme_actions
    assert window._theme_actions["filament"].text() == "filament (testing)"
    assert window._theme_actions["sodium"].isChecked()


def test_filament_takes_the_desk(arelis_window) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui.filament_field import FilamentFloatBar
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    window.history_dock.show()
    window.think_dock.show()
    apply_window_theme(window, "filament", persist=False)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not window.title_bar.isHidden()
    assert window.chrome_bar.isHidden()
    assert window.title_bar.view_btn.isHidden()
    assert window.title_bar.rooms_btn.isHidden()
    assert window.title_bar.settings_btn.isHidden()
    assert not window.title_bar.min_btn.isHidden()
    assert not window.title_bar.close_btn.isHidden()
    assert not window.title_bar.span_btns[1].isHidden()
    assert not window.title_bar.span_btns[3].isHidden()
    assert window._filament_span == 1
    assert window.title_bar.span_btns[window._filament_span].isChecked()
    window._filament_set_span(1)
    assert window._filament_span == 1
    assert window.title_bar.span_btns[1].isChecked()
    window._filament_set_span(2)
    assert window._filament_span == 2
    window._filament_set_span(3)
    assert window._filament_span == 3
    assert window.title_bar.span_btns[3].isChecked()
    assert window.readiness_strip.isHidden()
    assert window.history_dock.isHidden()
    assert window.think_dock.isHidden()
    assert window.chat.view.isHidden()
    assert not window.chat.empty.isHidden()
    assert not window._filament_chat_open
    assert window.conversation.conversation_btn.isVisibleTo(window.conversation)
    assert window.conversation.conversation_btn.iconSize().width() == 32
    assert window.chat.empty.listen_word.text() == 'say "hey arelis"'
    assert not window.chat.empty.listen_word.isHidden()
    assert window.chat.empty.prompt_host.isHidden()
    assert window.conversation.input.parent() is not window.chat.empty.prompt_host
    assert window.conversation.input.isHidden()
    assert "chat" in {name for name, _t, _oy in FLOATS}
    assert not isinstance(window._filament_floats, QWidget)
    assert isinstance(window._filament_floats, FilamentFloatBar)
    menu = window._build_filament_menu()
    labels = [act.text() for act in menu.actions()]
    assert "themes" in labels
    assert "desks" in labels
    assert "settings" in labels
    assert "rooms" in labels
    assert "chat" in labels
    assert "fullscreen" not in labels
    assert not window.act_fullscreen.isEnabled()
    menu.deleteLater()
    chips = window._filament_floats.chips()
    assert set(chips) == {
        "history",
        "notify",
        "contacts",
        "chat",
        "thinking",
        "camera",
        "days",
        "files",
        "rooms",
        "reality",
    }
    history = chips["history"]
    assert isinstance(history, QPushButton)
    assert history.objectName() == "FilamentFloat"
    assert history.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu
    assert (
        window._filament_chat_tile.contextMenuPolicy()
        == Qt.ContextMenuPolicy.CustomContextMenu
    )
    assert abs(window.windowOpacity() - 1.0) < 0.02
    window.act_history.trigger()
    assert window.history_dock.isFloating()
    assert window.history_dock.allowedAreas() == Qt.DockWidgetArea.NoDockWidgetArea
    assert window.history_dock.width() < 420
    assert window.history_dock.height() < 420
    assert window._filament_weather() == "awake"
    assert (
        window.act_history.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut
    )
    window._filament_set_chat_open(True)
    assert window._filament_chat_tile.hasMouseTracking()
    assert window._filament_chat_tile.minimumWidth() <= 240
    assert window._filament_chat_tile.minimumHeight() <= 180
    assert window._filament_chat_tile.width() <= 720
    window._toggle_fullscreen()
    assert not window.isFullScreen()
    window._filament_set_chat_open(False)
    apply_window_theme(window, "sodium", persist=False)
    assert window.act_fullscreen.isEnabled()
    assert not window.chrome_bar.isHidden()
    assert not window.history_dock.isHidden()
    assert not window.think_dock.isHidden()
    assert not window.title_bar.view_btn.isHidden()
    assert not window.title_bar.rooms_btn.isHidden()
    assert not window.title_bar.settings_btn.isHidden()
    assert window.title_bar.span_btns[1].isHidden()
    assert window.conversation.conversation_btn.iconSize().width() == 24
    assert confirm_mode() == "card"


def test_filament_coil_only_at_rest(arelis_window) -> None:
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    assert window._filament_weather() == "idle"
    window._filament_woken = True
    assert window._filament_weather() == "awake"
    window._away_resting = True
    assert window._filament_weather() == "idle"
    assert window._filament_woken is False
    window._away_resting = False
    window.conversation.mic_btn.setChecked(True)
    assert window._filament_weather() == "listen"
    window.conversation.mic_btn.setChecked(False)
    window._set_busy(True)
    assert window._filament_weather() == "think"
    window._place_filament_floats()
    assert window._filament.is_live("thinking")
    word = window._filament_floats.chips()["thinking"]
    assert word.property("live") == "true"
    window._set_busy(False)
    window._place_filament_floats()
    assert not window._filament.is_live("thinking")
    window._set_confirm_pending(True)
    assert window._filament.is_live("thinking")
    window._set_confirm_pending(False)
    assert not window._filament.is_live("thinking")
    apply_window_theme(window, "sodium", persist=False)


def test_filament_notify_breathes_when_unread(arelis_window) -> None:
    from datetime import datetime

    from arelis.notify.center import Notice
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    window.notify_center.items.append(
        Notice(
            id="n1",
            kind="email",
            title="one",
            body="",
            group_key="n1",
            created_at=datetime.now(UTC),
        )
    )
    window._place_filament_floats()
    assert window._filament.is_live("notify")
    word = window._filament_floats.chips()["notify"]
    assert word.property("live") == "true"
    window.notify_inbox.show()
    window._place_filament_floats()
    assert not window._filament.is_live("notify")
    apply_window_theme(window, "sodium", persist=False)


def test_filament_paint_budget_caps_wide_span() -> None:
    field = FilamentField()
    field.set_span(1)
    assert field.atmosphere_ms() == 33
    assert field.dust_draw_stride(2560) == 1
    assert field.strand_steps(2560) <= 130
    field.set_span(3)
    assert field.atmosphere_ms() == 40
    assert field.strand_steps(7680) <= 144
    assert field.dust_draw_stride(7680) == 3
    field.set_load("camera")
    assert field.atmosphere_ms() == 50
    assert field.dust_draw_stride(7680) == 4
    field.set_load("")
    glass = QRect(0, 0, 7680, 1440)
    band = field.dirty_rect(glass)
    _cx, cy, _rx, ry = field.ellipse(glass)
    assert band.width() == 7680
    assert band.height() < 1400
    assert band.top() <= int(cy - ry) - 8
    assert band.bottom() >= int(cy + ry) + 8
    lure = field.bead_point("reality", glass).toPoint()
    assert band.contains(lure)


def test_filament_tick_does_not_remask(arelis_window) -> None:
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    hits = {"n": 0}
    real = window._filament_apply_shape

    def counted() -> None:
        hits["n"] += 1
        real()

    window._filament_apply_shape = counted  # type: ignore[method-assign]
    window._place_filament_floats(reshape=False)
    assert hits["n"] == 0
    window._place_filament_floats()
    assert hits["n"] == 1
    hits["n"] = 0
    window.resizeEvent(QResizeEvent(QSize(800, 600), QSize(640, 480)))
    assert hits["n"] == 0
    apply_window_theme(window, "sodium", persist=False)


def test_filament_rooms_menu_omits_reality(tmp_path, arelis_window) -> None:
    from arelis.rooms import RoomStore
    from arelis.ui.settings_host import apply_window_theme

    store = RoomStore(tmp_path / "rooms.yaml")
    store.create("Writing")
    window = arelis_window({"_rooms": store})
    apply_window_theme(window, "filament", persist=False)
    labels = [
        act.text()
        for act in window._build_rooms_menu().actions()
        if not act.isSeparator()
    ]
    assert "Reality" not in labels
    assert "Writing" in labels
    apply_window_theme(window, "sodium", persist=False)
    labels = [
        act.text()
        for act in window._build_rooms_menu().actions()
        if not act.isSeparator()
    ]
    assert labels[0] == "Reality"


def test_sodium_keeps_its_face_after_filament(tmp_path, arelis_window) -> None:
    from arelis.core.events import Event, EventType
    from arelis.rooms import RoomStore
    from arelis.ui.settings_host import apply_window_theme
    from arelis.ui.world_host import world_available

    store = RoomStore(tmp_path / "rooms.yaml")
    store.create("Writing")
    window = arelis_window({"_rooms": store})
    apply_window_theme(window, "filament", persist=False)
    apply_window_theme(window, "sodium", persist=False)
    assert active_theme() == "sodium"
    assert confirm_mode() == "card"
    labels = [
        act.text()
        for act in window._build_rooms_menu().actions()
        if not act.isSeparator()
    ]
    assert labels[0] == "Reality"
    assert "Writing" in labels
    assert not window.title_bar.view_btn.isHidden()
    assert not window.title_bar.rooms_btn.isHidden()
    assert window.conversation.conversation_btn.iconSize().width() == 24
    window.conversation.ask_confirm("c1", "send_sms", "send_sms()", headline="text")
    assert not window.conversation.confirm.isHidden()
    window.conversation.dismiss_confirm()
    if world_available():
        window._toggle_world(True)
        assert window.world_window.isHidden()
        window._on_event(
            Event(EventType.ROOM_CHANGED, {"room_id": "physics", "name": "Reality"})
        )
        window._toggle_world(True)
        assert not window.world_window.isHidden()
        window._toggle_world(False)


def test_filament_reality_bead_opens_the_plate(arelis_window) -> None:
    from arelis.ui.settings_host import apply_window_theme
    from arelis.ui.world_host import world_available

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    assert world_available()
    assert window.world_window.isHidden()
    window._on_filament_float("reality")
    assert not window.world_window.isHidden()
    window._on_filament_float("reality")
    assert window.world_window.isHidden()
    apply_window_theme(window, "sodium", persist=False)


def test_filament_tile_returns_to_parked_geom(arelis_window) -> None:
    from arelis.ui.filament_tile import origin_on_a_desk
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    assert origin_on_a_desk(120, 80, 300, 260)
    assert not origin_on_a_desk(400_000, 400_000, 300, 260)
    window._filament_tile_pos["chat"] = (120, 80)
    window._filament_tile_sizes["chat"] = (300, 260)
    tile = window._filament_chat_tile
    window._filament_place_near_title(tile, "chat")
    geo = tile.frameGeometry()
    assert (geo.x(), geo.y()) == (120, 80)
    assert (geo.width(), geo.height()) == (300, 260)
    apply_window_theme(window, "sodium", persist=False)


def test_orb_stamps_reuse(qt_app) -> None:
    from arelis.ui.filament_field import _orb_stamp, clear_orb_stamps

    clear_orb_stamps()
    a = _orb_stamp(8.0, (212, 168, 96), core=2.4, pin=0.85)
    b = _orb_stamp(8.0, (212, 168, 96), core=2.4, pin=0.85)
    assert not a.isNull()
    assert a is b


def test_filament_parks_fullscreen_before_normal(arelis_window, monkeypatch) -> None:
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    flags = {"fs": True}
    monkeypatch.setattr(window, "isFullScreen", lambda: flags["fs"])
    monkeypatch.setattr(window, "isMaximized", lambda: False)
    monkeypatch.setattr(window, "showNormal", lambda: flags.__setitem__("fs", False))
    apply_window_theme(window, "filament", persist=False)
    parked = window._filament_parked
    assert parked is not None
    assert parked["fullscreen"] is True
    apply_window_theme(window, "sodium", persist=False)
