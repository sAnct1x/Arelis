from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.code_highlight import QuietPythonHighlighter
from arelis.ui.icons import (
    browse_file_icon,
    browse_folder_icon,
    file_open_icon,
    file_save_icon,
    folder_minus_icon,
    folder_new_icon,
    folder_plus_icon,
    folder_up_icon,
    refresh_icon,
)
from arelis.ui.theme import METRICS, polish_combo_popup

# Cap browse listing the same way the workspace tool caps directory list.
_MAX_BROWSE_ENTRIES = 500
_JUNK_DIR_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        ".git",
        ".hg",
        ".svn",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".eggs",
        ".cursor",
    }
)
_LOG_LINES = 12
_STATUS_HEIGHT = METRICS["row"] + 4
_STATUS_CHARS = 240


def _icon_btn(glyph: QIcon, tip: str) -> QToolButton:
    btn = QToolButton()
    btn.setObjectName("InstrumentIcon")
    btn.setText("")
    btn.setIcon(glyph)
    btn.setIconSize(QSize(16, 16))
    btn.setFixedSize(METRICS["row"], METRICS["row"])
    btn.setMinimumHeight(METRICS["row"])
    btn.setMaximumHeight(METRICS["row"])
    btn.setToolTip(tip)
    btn.setAccessibleName(tip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setAutoRaise(False)
    btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return btn


def _clip_log(text: str, limit: int = _LOG_LINES) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text.rstrip("\n")
    extra = len(lines) - limit
    return "\n".join(lines[:limit]) + f"\n[{extra} more lines not shown]"


def _first_status_line(text: str) -> str:
    line = (text or "").strip().splitlines()[0] if text else ""
    return line[:_STATUS_CHARS]


def is_workspace_listing(action: str, output: str, abs_path: str = "") -> bool:
    """True when the result is a directory listing, not a file body."""
    act = (action or "").strip().lower()
    if act == "list":
        return True
    if act:
        return False
    line = (output or "").lstrip()
    if line.startswith("[dir]") or line.startswith("[file]"):
        return True
    if not abs_path:
        return False
    try:
        return Path(abs_path).is_dir()
    except OSError:
        return False


def status_for_tool_result(
    tool: str,
    *,
    ok: bool,
    action: str = "",
    output: str = "",
) -> str | None:
    """One line for the dock strip, or None when the well should stay quiet.

    Listings belong in browse. File bodies belong in the editor. Analyze
    tables belong in chat. The strip is Wrote / Edited / a failure.
    """
    line = _first_status_line(output)
    name = (tool or "").strip()
    act = (action or "").strip().lower()
    if name == "analyze":
        return line if (not ok and line) else None
    if name in {"image", "image_edit"}:
        return line if (not ok and line) else None
    if name != "workspace":
        return None
    if not ok:
        return line or None
    if act in {"list", "read"}:
        return None
    if act in {"write", "edit"}:
        return line or None
    lowered = line.lower()
    if lowered.startswith("wrote ") or lowered.startswith("edited "):
        return line
    if line.startswith("[dir]") or line.startswith("[file]"):
        return None
    return None


def _browse_junk(path: Path) -> bool:
    name = path.name
    if name.endswith(".pyc") or name.endswith(".pyo"):
        return True
    if not path.is_dir():
        return False
    if name.startswith("."):
        return True
    if name in _JUNK_DIR_NAMES:
        return True
    return name.endswith(".egg-info")


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
        # What the editor held when the file was last loaded or saved. Dirty is
        # derived from it rather than latched, so setPlainText() firing
        # textChanged does not mark a freshly loaded file as edited.
        self._baseline = ""
        self._loaded_abs = ""
        self._loaded_label = ""
        self._dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self.project_combo = QComboBox()
        self.project_combo.setObjectName("InstrumentCombo")
        self.project_combo.setFixedHeight(METRICS["row"])
        polish_combo_popup(self.project_combo)
        self.project_combo.setMinimumWidth(120)
        self.project_combo.setToolTip("Active project")
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("InstrumentSearch")
        self.path_edit.setPlaceholderText("file in this project…")
        self.path_edit.setFixedHeight(METRICS["row"])
        self.open_btn = _icon_btn(file_open_icon(16), "Open file")
        self.save_btn = _icon_btn(file_save_icon(16), "Save file")
        path_row.addWidget(self.project_combo)
        path_row.addWidget(self.path_edit, stretch=1)
        path_row.addWidget(self.open_btn)
        path_row.addWidget(self.save_btn)
        layout.addLayout(path_row)

        roots_row = QHBoxLayout()
        roots_row.setSpacing(6)
        self.add_root_btn = _icon_btn(
            folder_plus_icon(16),
            "Add an existing folder as a project",
        )
        self.new_root_btn = _icon_btn(
            folder_new_icon(16),
            "Create a folder and add it as a project",
        )
        self.remove_root_btn = _icon_btn(
            folder_minus_icon(16),
            "Remove this project from the workspace — files stay on disk",
        )
        self.add_root_btn.clicked.connect(self.add_root_requested.emit)
        self.new_root_btn.clicked.connect(self.new_root_requested.emit)
        self.remove_root_btn.clicked.connect(self.remove_root_requested.emit)
        roots_row.addWidget(self.add_root_btn)
        roots_row.addWidget(self.new_root_btn)
        roots_row.addWidget(self.remove_root_btn)
        self.recent_combo = QComboBox()
        self.recent_combo.setObjectName("InstrumentCombo")
        self.recent_combo.setFixedHeight(METRICS["row"])
        self.recent_combo.setMinimumWidth(160)
        self.recent_combo.setToolTip("Recently opened or saved files")
        self.recent_combo.setPlaceholderText("recent")
        polish_combo_popup(self.recent_combo)
        self.recent_combo.activated.connect(self._on_recent_activated)
        roots_row.addWidget(self.recent_combo, stretch=1)
        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("InstrumentHint")
        roots_row.addWidget(self.dirty_label)
        layout.addLayout(roots_row)

        self.root_label = QLabel("")
        self.root_label.setObjectName("InstrumentHint")
        self.root_label.hide()

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
        self.up_btn = _icon_btn(folder_up_icon(16), "Up one folder")
        self.up_btn.clicked.connect(self._browse_up)
        self.refresh_btn = _icon_btn(refresh_icon(16), "Refresh this folder")
        self.refresh_btn.clicked.connect(self.refresh_browse)
        browse_head.addWidget(self.browse_label, stretch=1)
        browse_head.addWidget(self.up_btn)
        browse_head.addWidget(self.refresh_btn)
        left_l.addLayout(browse_head)
        self.browse_list = QListWidget()
        # Not #OutputView: that is the code editor's rule and it set filenames
        # in the mono face, which made a folder listing look like a diff.
        self.browse_list.setObjectName("BrowseList")
        self.browse_list.setIconSize(QSize(14, 14))
        self.browse_list.setToolTip("Caches and dot-folders are hidden")
        self.browse_list.itemActivated.connect(self._on_browse_activated)
        self._folder_icon = browse_folder_icon(14)
        self._file_icon = browse_file_icon(14)
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
        self._highlight = QuietPythonHighlighter(self.editor.document())
        self._highlight.set_enabled(False)
        mid_l.addWidget(self.editor)

        right = QWidget()
        right.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        # Image is the hero when present; otherwise this column collapses.
        self.image_label = QLabel()
        self.image_label.setMinimumHeight(220)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setObjectName("WorkspaceImageWell")
        self.image_label.hide()
        right_layout.addWidget(self.image_label)

        self.split.addWidget(left)
        self.split.addWidget(mid)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setCollapsible(0, False)
        self.split.setCollapsible(1, False)
        self.split.setCollapsible(2, True)
        self.split.setSizes([220, 720, 0])
        layout.addWidget(self.split, stretch=1)

        self.output = QPlainTextEdit()
        self.output.setObjectName("OutputView")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("")
        self.output.setFixedHeight(_STATUS_HEIGHT)
        self.output.setMaximumBlockCount(1)
        self.output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.output.hide()
        layout.addWidget(self.output)

        self.open_btn.clicked.connect(self._on_open)
        self.save_btn.clicked.connect(self._on_save)
        self.editor.textChanged.connect(self._sync_dirty)

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
            self.project_combo.setToolTip(path)
        elif name:
            self.root_label.setText(f"project: {name}")
            self.root_label.setToolTip("")
            self.project_combo.setToolTip("Active project")
        else:
            self.root_label.setText("")
            self.root_label.setToolTip("")
            self.project_combo.setToolTip("Active project")
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
            self.browse_label.setToolTip("")
            return
        try:
            cwd = self._browse_cwd.resolve()
            cwd.relative_to(root.resolve())
        except (OSError, ValueError):
            cwd = root.resolve()
            self._browse_cwd = cwd
        self.browse_label.setText(cwd.name or str(cwd))
        self.browse_label.setToolTip(str(cwd))
        self.browse_list.clear()
        try:
            entries = sorted(
                cwd.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except OSError:
            return
        visible = [entry for entry in entries if not _browse_junk(entry)]
        shown = visible[:_MAX_BROWSE_ENTRIES]
        for entry in shown:
            item = QListWidgetItem(entry.name)
            item.setIcon(self._folder_icon if entry.is_dir() else self._file_icon)
            item.setData(Qt.ItemDataRole.UserRole, str(entry))
            self.browse_list.addItem(item)
        if len(visible) > len(shown):
            self.browse_list.addItem(
                QListWidgetItem(f"[{len(visible) - len(shown)} more not shown]")
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

    def has_unsaved_changes(self) -> bool:
        return self._dirty

    def baseline_text(self) -> str:
        """Editor contents as of the last load or save — what a diff is against."""
        return self._baseline

    def loaded_abs(self) -> str:
        return self._loaded_abs

    def loaded_label(self) -> str:
        return self._loaded_label or self.path_edit.text().strip()

    def _sync_dirty(self) -> None:
        dirty = self.editor.toPlainText() != self._baseline
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirty_label.setText("unsaved changes" if dirty else "")

    def set_file(
        self,
        path: str,
        content: str,
        root_name: str = "",
        *,
        abs_path: str = "",
        force: bool = False,
    ) -> bool:
        """Put a file in the editor. False means unsaved edits were kept instead.

        Arelis writing a file the operator has open used to replace the buffer
        underneath them, and typing for ten minutes into a file she then touched
        lost ten minutes of work with no message and nothing to undo. Her write
        still lands on disk; it just does not get to overwrite the editor. The
        caller says force=True for replacements the operator asked for.
        """
        if not force and self._dirty and content != self.editor.toPlainText():
            return False
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
        self._baseline = content
        self._loaded_abs = abs_path
        self._loaded_label = path
        self.editor.setPlainText(content)
        self._highlight.set_enabled(
            Path(abs_path or display).suffix.lower() in {".py", ".pyw"}
        )
        self._sync_dirty()
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
        return True

    def browse_to(self, abs_path: str, root_name: str = "") -> None:
        """Point browse at a folder the workspace tool just listed."""
        if root_name and root_name in self._project_names:
            self.project_combo.blockSignals(True)
            self.project_combo.setCurrentText(root_name)
            self.project_combo.blockSignals(False)
            self._sync_root_label(root_name)
        if abs_path:
            path = Path(abs_path)
            try:
                target = path if path.is_dir() else path.parent
                if target.is_dir():
                    self._browse_cwd = target
            except OSError:
                pass
        self.refresh_browse()

    def append_output(self, text: str) -> None:
        """One status line. A dump cannot become a third column again."""
        line = _first_status_line(text)
        if not line:
            return
        clipped = _clip_log(line, limit=1)
        self.output.setPlainText(clipped)
        self.output.setFixedHeight(_STATUS_HEIGHT)
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
        """Image takes the right well; the editor yields. Status stays a strip."""
        self._image_mode = on
        if on:
            self.editor.hide()
            self.image_label.show()
            self.split.setCollapsible(1, True)
            self.split.setCollapsible(2, False)
            self.split.setSizes([180, 0, 620])
        else:
            self.editor.show()
            self.image_label.hide()
            self.split.setCollapsible(1, False)
            self.split.setCollapsible(2, True)
            self.split.setSizes([220, 700, 0])
        if self.output.toPlainText().strip():
            self.output.show()
        else:
            self.output.hide()
