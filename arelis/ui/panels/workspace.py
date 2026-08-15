from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

# Cap browse listing the same way the workspace tool caps directory list.
_MAX_BROWSE_ENTRIES = 500


class WorkspacePanel(QWidget):
    open_requested = Signal(str)
    save_requested = Signal(str, str)
    project_changed = Signal(str)
    add_root_requested = Signal()
    new_root_requested = Signal()
    remove_root_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._project_names: list[str] = []
        self._project_paths: dict[str, str] = {}
        self._root_name = ""
        self._image_mode = False
        self._browse_cwd = Path(".")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.project_combo = QComboBox()
        self.project_combo.setFixedHeight(28)
        self.project_combo.setMinimumWidth(120)
        self.project_combo.setToolTip("Active project")
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("InstrumentSearch")
        self.path_edit.setPlaceholderText("path under allowed roots…")
        self.path_edit.setFixedHeight(28)
        self.open_btn = QPushButton("open")
        self.open_btn.setObjectName("InstrumentAction")
        self.save_btn = QPushButton("save")
        self.save_btn.setObjectName("InstrumentAction")
        self.open_btn.setFixedHeight(28)
        self.save_btn.setFixedHeight(28)
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        path_row.addWidget(self.project_combo)
        path_row.addWidget(self.path_edit, stretch=1)
        path_row.addWidget(self.open_btn)
        path_row.addWidget(self.save_btn)
        layout.addLayout(path_row)

        roots_row = QHBoxLayout()
        roots_row.setSpacing(6)
        root_actions = (
            (
                "add folder",
                "Add an existing folder as a workspace root",
                self.add_root_requested.emit,
            ),
            (
                "new folder",
                "Create a folder and add it as a workspace root",
                self.new_root_requested.emit,
            ),
            (
                "remove",
                "Remove the active project from the workspace (files stay on disk)",
                self.remove_root_requested.emit,
            ),
        )
        for label, tip, slot in root_actions:
            btn = QPushButton(label)
            btn.setObjectName("InstrumentAction")
            btn.setFixedHeight(24)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            roots_row.addWidget(btn)
        roots_row.addStretch(1)
        layout.addLayout(roots_row)

        recent_row = QHBoxLayout()
        recent_row.setSpacing(6)
        recent_label = QLabel("recent")
        recent_label.setObjectName("InstrumentHint")
        self.recent_combo = QComboBox()
        self.recent_combo.setObjectName("InstrumentSearch")
        self.recent_combo.setFixedHeight(28)
        self.recent_combo.setMinimumWidth(160)
        self.recent_combo.setToolTip("Recently opened or saved workspace files")
        self.recent_combo.activated.connect(self._on_recent_activated)
        recent_row.addWidget(recent_label)
        recent_row.addWidget(self.recent_combo, stretch=1)
        layout.addLayout(recent_row)

        self.root_label = QLabel("")
        self.root_label.setObjectName("InstrumentHint")
        layout.addWidget(self.root_label)

        self.split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        left_l.setSpacing(6)
        browse_head = QHBoxLayout()
        browse_head.setSpacing(6)
        self.browse_label = QLabel("browse")
        self.browse_label.setObjectName("InstrumentHint")
        up_btn = QPushButton("up")
        up_btn.setObjectName("InstrumentAction")
        up_btn.setFixedHeight(24)
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.clicked.connect(self._browse_up)
        refresh_btn = QPushButton("refresh")
        refresh_btn.setObjectName("InstrumentAction")
        refresh_btn.setFixedHeight(24)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh_browse)
        browse_head.addWidget(self.browse_label, stretch=1)
        browse_head.addWidget(up_btn)
        browse_head.addWidget(refresh_btn)
        left_l.addLayout(browse_head)
        self.browse_list = QListWidget()
        self.browse_list.setObjectName("OutputView")
        self.browse_list.itemActivated.connect(self._on_browse_activated)
        left_l.addWidget(self.browse_list, stretch=1)

        mid = QWidget()
        mid.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        mid_l = QVBoxLayout(mid)
        mid_l.setContentsMargins(0, 0, 0, 0)
        mid_l.setSpacing(0)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("Editor")
        self.editor.setPlaceholderText("file contents…")
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        mid_l.addWidget(self.editor)

        right = QWidget()
        right.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Image is the hero when present; tool log collapses underneath.
        self.image_label = QLabel()
        self.image_label.setMinimumHeight(220)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setObjectName("WorkspaceImageWell")
        self.image_label.hide()

        self.output = QPlainTextEdit()
        self.output.setObjectName("OutputView")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("tool output…")
        self.output.setMaximumHeight(140)
        self.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

        right_layout.addWidget(self.image_label, stretch=5)
        right_layout.addWidget(self.output, stretch=1)

        self.split.addWidget(left)
        self.split.addWidget(mid)
        self.split.addWidget(right)
        self.split.setSizes([200, 360, 320])
        layout.addWidget(self.split, stretch=1)

        self.open_btn.clicked.connect(self._on_open)
        self.save_btn.clicked.connect(self._on_save)

    def set_projects(
        self,
        names: list[str],
        active: str,
        *,
        paths: dict[str, str] | None = None,
    ) -> None:
        self._project_names = list(names)
        if paths is not None:
            self._project_paths = dict(paths)
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItems(names)
        if active in names:
            self.project_combo.setCurrentText(active)
        elif names:
            self.project_combo.setCurrentIndex(0)
        self.project_combo.setEnabled(len(names) > 1)
        self.project_combo.show()
        self.project_combo.blockSignals(False)
        self._browse_cwd = Path(".")
        self._sync_root_label(active if active in names else (names[0] if names else ""))
        self.refresh_browse()

    def set_recent(self, paths: list[str]) -> None:
        self.recent_combo.blockSignals(True)
        self.recent_combo.clear()
        self.recent_combo.addItem("—", "")
        for path in paths:
            self.recent_combo.addItem(path, path)
        self.recent_combo.blockSignals(False)

    def set_active_project(self, name: str) -> None:
        if name not in self._project_names:
            return
        self.project_combo.blockSignals(True)
        self.project_combo.setCurrentText(name)
        self.project_combo.blockSignals(False)
        self._sync_root_label(name)
        self.refresh_browse()

    def _sync_root_label(self, name: str) -> None:
        self._root_name = name
        path = self._project_paths.get(name, "")
        if name and path:
            self.root_label.setText(f"project: {name} — {path}")
            self.root_label.setToolTip(path)
            self.root_label.show()
        elif name:
            self.root_label.setText(f"project: {name}")
            self.root_label.show()
        else:
            self.root_label.hide()

    def _on_project_changed(self, name: str) -> None:
        if name and name in self._project_names:
            self._sync_root_label(name)
            self.refresh_browse()
            self.project_changed.emit(name)

    def _on_recent_activated(self, index: int) -> None:
        path = str(self.recent_combo.itemData(index) or "").strip()
        if not path:
            return
        self.path_edit.setText(path)
        self.open_requested.emit(self.qualified_path() or path)

    def _active_root_path(self) -> Path | None:
        active = self.project_combo.currentText() or self._root_name
        raw = self._project_paths.get(active or "")
        if not raw:
            return None
        root = Path(raw)
        return root if root.is_dir() else None

    def refresh_browse(self) -> None:
        root = self._active_root_path()
        if root is None:
            self.browse_list.clear()
            self.browse_label.setText("browse")
            return
        try:
            cwd = self._browse_cwd.resolve()
            cwd.relative_to(root.resolve())
        except (OSError, ValueError):
            cwd = root.resolve()
            self._browse_cwd = cwd
        self.browse_label.setText(f"browse · {cwd.name or cwd}")
        self.browse_list.clear()
        try:
            entries = sorted(
                cwd.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except OSError:
            return
        shown = entries[:_MAX_BROWSE_ENTRIES]
        for entry in shown:
            kind = "[dir] " if entry.is_dir() else "[file] "
            item = QListWidgetItem(kind + entry.name)
            item.setData(Qt.ItemDataRole.UserRole, str(entry))
            self.browse_list.addItem(item)
        if len(entries) > len(shown):
            self.browse_list.addItem(
                QListWidgetItem(f"[{len(entries) - len(shown)} more not shown]")
            )

    def _browse_up(self) -> None:
        root = self._active_root_path()
        if root is None:
            return
        root_r = root.resolve()
        cwd = getattr(self, "_browse_cwd", root_r).resolve()
        parent = cwd.parent
        try:
            parent.relative_to(root_r)
            self._browse_cwd = parent
        except ValueError:
            self._browse_cwd = root_r
        self.refresh_browse()

    def _on_browse_activated(self, item: QListWidgetItem) -> None:
        raw = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not raw:
            return
        path = Path(raw)
        if path.is_dir():
            self._browse_cwd = path
            self.refresh_browse()
            return
        if path.is_file():
            active = self.project_combo.currentText() or self._root_name
            root = self._active_root_path()
            display = path.name
            if root is not None:
                try:
                    display = path.relative_to(root.resolve()).as_posix()
                except ValueError:
                    display = str(path)
            if active and len(self._project_names) > 1:
                qualified = f"{active}:{display}"
            else:
                qualified = display
            self.path_edit.setText(display)
            self.open_requested.emit(qualified)

    def _on_open(self) -> None:
        path = self.qualified_path()
        if not path:
            start = self._dialog_start_dir()
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Open workspace file",
                start,
                "All files (*.*)",
            )
            if not chosen:
                return
            path = chosen
            self.path_edit.setText(path)
            path = self.qualified_path() or path
        self.open_requested.emit(path)

    def _on_save(self) -> None:
        path = self.qualified_path()
        if not path:
            start = self._dialog_start_dir()
            chosen, _ = QFileDialog.getSaveFileName(
                self,
                "Save workspace file",
                start,
                "All files (*.*)",
            )
            if not chosen:
                return
            self.path_edit.setText(chosen)
            path = self.qualified_path() or chosen
        self.save_requested.emit(path, self.editor.toPlainText())

    def _dialog_start_dir(self) -> str:
        """Prefer the active project root when picking a file."""
        active = self.project_combo.currentText() or self._root_name
        if active and active in self._project_paths:
            root = Path(self._project_paths[active])
            if root.is_dir():
                return str(root)
        if len(self._project_paths) == 1:
            only = Path(next(iter(self._project_paths.values())))
            if only.is_dir():
                return str(only)
        tip = (self.root_label.toolTip() or "").strip()
        if tip and Path(tip).is_dir():
            return tip
        return str(Path.cwd())

    def qualified_path(self) -> str:
        """Path for slash commands: qualify when multiple projects exist."""
        raw = self.path_edit.text().strip()
        if not raw:
            return ""
        if ":" in raw or Path(raw).is_absolute() or len(self._project_names) <= 1:
            return raw
        active = self.project_combo.currentText() or self._root_name
        if not active:
            return raw
        return f"{active}:{raw}"

    def set_file(
        self,
        path: str,
        content: str,
        root_name: str = "",
        *,
        abs_path: str = "",
    ) -> None:
        self._set_image_mode(False)
        display = path
        owning = root_name
        if ":" in path and not Path(path).is_absolute():
            name, rest = path.split(":", 1)
            if name in self._project_names:
                owning = name
                display = rest or "."
        self._root_name = owning
        self.path_edit.setText(display)
        self.editor.setPlainText(content)
        if abs_path:
            parent = Path(abs_path).parent
            self.root_label.setToolTip(str(parent))
            try:
                if parent.is_dir():
                    self._browse_cwd = parent
            except OSError:
                pass
        if owning:
            self._sync_root_label(owning)
            if owning in self._project_names:
                self.project_combo.blockSignals(True)
                self.project_combo.setCurrentText(owning)
                self.project_combo.blockSignals(False)
        self.refresh_browse()

    def append_output(self, text: str) -> None:
        self.output.appendPlainText(text)
        if self._image_mode:
            self.output.setMaximumHeight(72)
            self.output.show()
        else:
            self.output.setMaximumHeight(16777215)
            self.output.show()

    def show_image(self, path: str) -> None:
        pix = QPixmap(path)
        self._set_image_mode(True)
        self.image_label.show()
        self.path_edit.setText(str(path))
        if pix.isNull():
            self.image_label.setText(f"could not load\n{path}")
            return
        # Fill the available pane — image is the product of this dock.
        target_w = max(self.image_label.width(), self.width() // 2, 420)
        target_h = max(self.image_label.height(), 280)
        self.image_label.setPixmap(
            pix.scaled(
                target_w,
                target_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.image_label.setToolTip(str(Path(path)))

    def _set_image_mode(self, on: bool) -> None:
        """When an image is showing: hide the empty editor, collapse empty log."""
        self._image_mode = on
        if on:
            self.editor.hide()
            self.output.setPlaceholderText("generation log…")
            if not self.output.toPlainText().strip():
                self.output.hide()
            else:
                self.output.setMaximumHeight(72)
                self.output.show()
            self.split.setSizes([160, 0, 640])
        else:
            self.editor.show()
            self.image_label.hide()
            self.output.show()
            self.output.setMaximumHeight(140)
            self.output.setPlaceholderText("tool output…")
            self.split.setSizes([200, 360, 320])
