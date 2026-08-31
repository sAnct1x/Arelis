from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QWidget,
)

from arelis.ui.icons import (
    window_close_icon,
    window_maximize_icon,
    window_minimize_icon,
)


def _chrome_btn(obj: str, icon, slot, *, tooltip: str = "") -> QPushButton:
    btn = QPushButton()
    btn.setObjectName(obj)
    btn.setIcon(icon)
    btn.setFixedSize(32, 26)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFlat(True)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.clicked.connect(slot)
    return btn


class TitleBar(QWidget):
    """Frameless window chrome that matches the glass shell."""

    view_menu_requested = Signal(object)  # emits the view button for QMenu.exec
    rooms_menu_requested = Signal(object)  # emits the rooms button for QMenu.exec
    settings_requested = Signal()
    span_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(40)
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 10, 0)
        layout.setSpacing(4)

        self._span_left = QWidget()
        self._span_left.setFixedWidth(0)
        self._span_right = QWidget()
        self._span_right.setFixedWidth(0)
        layout.addWidget(self._span_left)

        self.title = QLabel("arelis")
        self.title.setObjectName("ChromeTitle")
        layout.addWidget(self.title)
        layout.addSpacing(10)

        self.view_btn = QToolButton()
        self.view_btn.setObjectName("ChromeViewBtn")
        self.view_btn.setText("view")
        self.view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_btn.clicked.connect(lambda: self.view_menu_requested.emit(self.view_btn))
        layout.addWidget(self.view_btn)

        self.rooms_btn = QToolButton()
        self.rooms_btn.setObjectName("ChromeRoomsBtn")
        self.rooms_btn.setText("rooms")
        self.rooms_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rooms_btn.clicked.connect(
            lambda: self.rooms_menu_requested.emit(self.rooms_btn)
        )
        layout.addWidget(self.rooms_btn)

        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("ChromeSettingsBtn")
        self.settings_btn.setText("settings")
        self.settings_btn.setToolTip("Settings (Ctrl+,)")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

        self.span_group = QButtonGroup(self)
        self.span_group.setExclusive(True)
        self.span_btns: dict[int, QToolButton] = {}
        for n in (1, 2, 3):
            btn = QToolButton()
            btn.setObjectName("ChromeSpanBtn")
            btn.setText(str(n))
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            tips = {
                1: "primary only",
                2: "primary and the right desk",
                3: "all three, left to right",
            }
            btn.setToolTip(tips[n])
            btn.setVisible(False)
            btn.clicked.connect(lambda _c=False, k=n: self.span_requested.emit(k))
            self.span_group.addButton(btn, n)
            self.span_btns[n] = btn
            layout.addWidget(btn)
        self.span_btns[1].setChecked(True)

        layout.addStretch(1)

        self.min_btn = _chrome_btn("ChromeMin", window_minimize_icon(14), self._minimize)
        self.max_btn = _chrome_btn("ChromeMax", window_maximize_icon(14), self._maximize)
        self.close_btn = _chrome_btn("ChromeClose", window_close_icon(14), self._close)
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)
        layout.addWidget(self._span_right)

    def set_home_band(self, left: int, width: int, total: int) -> None:
        """Keep arelis + 1/2/3 + window buttons on the primary desk."""
        if width <= 0 or total <= 0:
            self._span_left.setFixedWidth(0)
            self._span_right.setFixedWidth(0)
            return
        left = max(0, int(left))
        width = max(280, int(width))
        total = max(1, int(total))
        if left + 280 > total:
            self._span_left.setFixedWidth(0)
            self._span_right.setFixedWidth(0)
            return
        right = max(0, total - left - width)
        self._span_left.setFixedWidth(left)
        self._span_right.setFixedWidth(right)

    def set_slim(self, on: bool) -> None:
        """Filament: word + window buttons. View / rooms / settings live on the field."""
        slim = bool(on)
        self.view_btn.setVisible(not slim)
        self.rooms_btn.setVisible(not slim)
        self.settings_btn.setVisible(not slim)
        for btn in self.span_btns.values():
            btn.setVisible(slim)
        self.setFixedHeight(32 if slim else 40)
        lay = self.layout()
        if lay is not None:
            lay.setContentsMargins(14 if slim else 18, 0, 6 if slim else 10, 0)

    def set_span_choice(self, n: int) -> None:
        btn = self.span_btns.get(max(1, min(3, int(n))))
        if btn is None:
            return
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)

    def set_span_available(self, n: int) -> None:
        have = max(1, min(3, int(n)))
        for k, btn in self.span_btns.items():
            btn.setEnabled(k <= have)

    def refresh_theme_icons(self) -> None:
        """Redraw chrome glyphs from the live palette."""
        self.min_btn.setIcon(window_minimize_icon(14))
        self.close_btn.setIcon(window_close_icon(14))
        self.sync_window_state()

    def sync_window_state(self, window=None) -> None:
        """Keep the maximize glyph in sync after taskbar / shortcut restore."""
        w = window or self._window()
        if not w or not hasattr(self, "max_btn"):
            return
        spanned = False
        check = getattr(w, "_filament_is_spanned", None)
        if callable(check):
            spanned = bool(check())
        restore = w.isFullScreen() or w.isMaximized() or spanned
        self.max_btn.setIcon(window_maximize_icon(14, restore=restore))

    def _window(self):
        return self.window()

    def _minimize(self) -> None:
        w = self._window()
        if w:
            w.showMinimized()

    def _maximize(self) -> None:
        w = self._window()
        if not w:
            return
        from arelis.ui.theme import active_theme

        toggle = getattr(w, "_filament_toggle_span", None)
        if active_theme() == "filament" and callable(toggle):
            # Snap to the chosen 1 / 2 / 3. Do not fullscreen.
            toggle()
            self.sync_window_state(w)
            return
        if w.isFullScreen():
            w.showNormal()
        elif w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()
        self.sync_window_state(w)

    def _close(self) -> None:
        w = self._window()
        if w:
            w.close()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            origin = self._window().frameGeometry().topLeft()
            self._drag_pos = event.globalPosition().toPoint() - origin
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            w = self._window()
            if w and not w.isMaximized() and not w.isFullScreen():
                w.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._maximize()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class FloatingDockTitleBar(QWidget):
    """In-panel min/max/close chrome for undocked instrument plates.

    Transparent strip so the parent GlassFrame reads as one continuous slab.
    Double-click redocks into the main window; maximize still maximizes.
    """

    def __init__(self, title: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FloatingTitleBar")
        self.setFixedHeight(40)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 10, 0)
        layout.setSpacing(6)

        self.title = QLabel(title)
        self.title.setObjectName("FloatingDockTitle")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.title.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.title.setAutoFillBackground(False)
        self.title.setToolTip("drag to move · double-click to dock")
        layout.addWidget(self.title)
        layout.addStretch(1)

        self.min_btn = _chrome_btn("ChromeMin", window_minimize_icon(14), self._minimize)
        self.max_btn = _chrome_btn("ChromeMax", window_maximize_icon(14), self._maximize)
        self.close_btn = _chrome_btn(
            "ChromeClose",
            window_close_icon(14),
            self._close,
            tooltip="Hide panel (View menu to restore)",
        )
        layout.addWidget(self.min_btn)
        layout.addWidget(self.max_btn)
        layout.addWidget(self.close_btn)

        self.setToolTip("drag to move · double-click to dock · maximize · hide")

    def set_title(self, title: str) -> None:
        self.title.setText(title)

    def refresh_theme_icons(self) -> None:
        self.min_btn.setIcon(window_minimize_icon(14))
        self.close_btn.setIcon(window_close_icon(14))
        self.sync_window_state()

    def sync_window_state(self, window=None) -> None:
        w = window or self._window()
        if not w or not hasattr(self, "max_btn"):
            return
        restore = w.isMaximized() or w.isFullScreen()
        self.max_btn.setIcon(window_maximize_icon(14, restore=restore))

    def _window(self):
        return self.window()

    def _dock(self):
        w = self._window()
        return w if isinstance(w, QDockWidget) else None

    def _minimize(self) -> None:
        w = self._window()
        if w:
            w.showMinimized()

    def _maximize(self) -> None:
        w = self._window()
        if not w:
            return
        if w.isMaximized() or w.isFullScreen():
            w.showNormal()
        else:
            w.showMaximized()
        self.sync_window_state(w)

    def _close(self) -> None:
        w = self._window()
        if w:
            w.close()

    def _try_redock_over_main(self) -> bool:
        """If released over the main window, snap the panel back in."""
        from arelis.ui.theme import active_theme

        if active_theme() == "filament":
            return False
        dock = self._dock()
        if dock is None or not dock.isFloating():
            return False
        main = dock.parentWidget()
        if main is None:
            return False
        host = main.window() if main.window() is not None else main
        if host is dock:
            return False
        if host.frameGeometry().contains(QCursor.pos()):
            dock.setFloating(False)
            return True
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            w = self._window()
            if w:
                origin = w.frameGeometry().topLeft()
                self._drag_pos = event.globalPosition().toPoint() - origin
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            w = self._window()
            if w and not w.isMaximized() and not w.isFullScreen():
                w.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self._try_redock_over_main()
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            from arelis.ui.theme import active_theme

            dock = self._dock()
            if (
                dock is not None
                and dock.isFloating()
                and active_theme() != "filament"
            ):
                dock.setFloating(False)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
