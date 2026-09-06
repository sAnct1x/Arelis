from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyleFactory,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.desk import Artifact, infer_kind, is_image_kind, is_text_kind
from arelis.mathtext import flatten_latex
from arelis.rooms import PHYSICS_DISPLAY_NAME, PHYSICS_ROOM_ID
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
    note_keep_icon,
    refresh_icon,
)
from arelis.ui.image_rail import (
    CAPTION_NAME,
    DESK_EMPTY_PICTURES,
    STRIP_NAME,
    THUMB_NAME,
    WELL_NAME,
    load_fail_line,
    load_fitted_pixmap,
    load_square_thumb,
    sidecar_caption,
)
from arelis.ui.image_rail import (
    THUMB_LONG as _THUMB_LONG,
)
from arelis.ui.image_rail import (
    recent_output_images as _recent_output_images,
)
from arelis.ui.image_rail import (
    sidecar_tooltip as _sidecar_tooltip,
)
from arelis.ui.theme import METRICS, SPACE, polish_combo_popup, space_box

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
    keep_requested = Signal()
    pin_requested = Signal(str, bool)
    drop_requested = Signal(str)
    desk_open_requested = Signal(str)
    reveal_requested = Signal(str)
    outside_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._project_names: list[str] = []
        self._project_paths: dict[str, str] = {}
        self._root_name = ""
        self._room_id = ""
        self._room_name = ""
        self._mode = "desk"
        self._desk_items: list[Artifact] = []
        self._preview_md = False
        self._image_mode = False
        self._hero_path = ""
        self._image_paths: list[Path] = []
        self._browse_cwd = Path(".")
        # What the editor held when the file was last loaded or saved. Dirty is
        # derived from it rather than latched, so setPlainText() firing
        # textChanged does not mark a freshly loaded file as edited.
        self._baseline = ""
        self._loaded_abs = ""
        self._loaded_label = ""
        self._dirty = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*space_box("micro", "hair", "micro", "gap"))
        layout.setSpacing(SPACE["gap"])

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        self.project_combo = QComboBox()
        self.project_combo.setObjectName("InstrumentCombo")
        self.project_combo.setFixedHeight(METRICS["row"])
        polish_combo_popup(self.project_combo)
        self.project_combo.setMinimumWidth(100)
        self.project_combo.setToolTip("Active project")
        self.project_combo.currentTextChanged.connect(self._on_project_changed)
        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("InstrumentSearch")
        self.path_edit.setPlaceholderText("file in this project…")
        self.path_edit.setFixedHeight(METRICS["row"])
        self.open_btn = _icon_btn(file_open_icon(16), "Open file")
        self.save_btn = _icon_btn(file_save_icon(16), "Save file")
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
        self.keep_btn = _icon_btn(note_keep_icon(16), "Keep a note on the desk")
        self.add_root_btn.clicked.connect(self.add_root_requested.emit)
        self.new_root_btn.clicked.connect(self.new_root_requested.emit)
        self.remove_root_btn.clicked.connect(self.remove_root_requested.emit)
        self.keep_btn.clicked.connect(self.keep_requested.emit)
        self.recent_combo = QComboBox()
        self.recent_combo.setObjectName("InstrumentCombo")
        self.recent_combo.setFixedHeight(METRICS["row"])
        self.recent_combo.setMinimumWidth(100)
        self.recent_combo.setToolTip("Recently opened or saved files")
        self.recent_combo.setPlaceholderText("recent")
        polish_combo_popup(self.recent_combo)
        self.recent_combo.activated.connect(self._on_recent_activated)
        self.dirty_label = QLabel("")
        self.dirty_label.setObjectName("InstrumentHint")
        path_row.addWidget(self.project_combo)
        path_row.addWidget(self.path_edit, stretch=1)
        path_row.addWidget(self.open_btn)
        path_row.addWidget(self.save_btn)
        path_row.addWidget(self.keep_btn)
        path_row.addWidget(self.add_root_btn)
        path_row.addWidget(self.new_root_btn)
        path_row.addWidget(self.remove_root_btn)
        path_row.addWidget(self.recent_combo)
        path_row.addWidget(self.dirty_label)
        layout.addLayout(path_row)

        self.root_label = QLabel("")
        self.root_label.setObjectName("InstrumentHint")
        self.root_label.hide()

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 2, 0, 0)
        mode_row.setSpacing(8)
        self.desk_btn = QPushButton("desk")
        self.folders_btn = QPushButton("folders")
        for btn, tip in (
            (self.desk_btn, "Things she made, and notes you kept"),
            (self.folders_btn, "Browse the project folder"),
        ):
            btn.setObjectName("InstrumentAction")
            btn.setFixedHeight(METRICS["row"])
            btn.setMinimumWidth(76)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setToolTip(tip)
        self.desk_btn.setChecked(True)
        self.desk_btn.clicked.connect(lambda: self.show_desk())
        self.folders_btn.clicked.connect(lambda: self.show_folders())
        mode_row.addWidget(self.desk_btn)
        mode_row.addWidget(self.folders_btn)
        mode_row.addStretch(1)
        self.desk_hint = QLabel("this project's papers")
        self.desk_hint.setObjectName("DeskHint")
        self.desk_hint.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        mode_row.addWidget(self.desk_hint)
        layout.addLayout(mode_row)

        self.empty_face = QWidget()
        self.empty_face.setObjectName("DeskEmptyFace")
        self.empty_face.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        empty_l = QVBoxLayout(self.empty_face)
        empty_l.setContentsMargins(*space_box("stage", "plate"))
        empty_l.setSpacing(SPACE["gap"])
        empty_l.addStretch(1)
        self.empty_title = QLabel("Desk")
        self.empty_title.setObjectName("DeskEmptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.desk_empty = QLabel(
            "Nothing on the desk yet.\n"
            "Files she writes and notes you keep land here.\n"
            f"{DESK_EMPTY_PICTURES}\n"
            "Say keep this: and what to write down, or press the note mark."
        )
        self.desk_empty.setObjectName("DeskEmpty")
        self.desk_empty.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.desk_empty.setWordWrap(True)
        empty_l.addWidget(self.empty_title)
        empty_l.addWidget(self.desk_empty)
        empty_l.addStretch(2)

        self.split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 8, 0)
        left_l.setSpacing(8)
        self.desk_list = QListWidget()
        self.desk_list.setObjectName("DeskList")
        self.desk_list.setFrameShape(QListWidget.Shape.NoFrame)
        self.desk_list.setWordWrap(True)
        self.desk_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.desk_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.desk_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.desk_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.desk_list.itemClicked.connect(self._on_desk_activated)
        self.desk_list.customContextMenuRequested.connect(self._on_desk_menu)
        left_l.addWidget(self.desk_list, stretch=1)
        browse_head = QHBoxLayout()
        browse_head.setSpacing(6)
        self.browse_label = QLabel("browse")
        self.browse_label.setObjectName("InstrumentHint")
        self.up_btn = _icon_btn(folder_up_icon(16), "Up one folder")
        self.up_btn.clicked.connect(self._browse_up)
        self.up_btn.hide()
        self.refresh_btn = _icon_btn(refresh_icon(16), "Refresh this folder")
        self.refresh_btn.clicked.connect(self.refresh_browse)
        self.refresh_btn.hide()
        browse_head.addWidget(self.browse_label, stretch=1)
        left_l.addLayout(browse_head)
        self.browse_list = QListWidget()
        # Not #OutputView: that is the code editor's rule and it set filenames
        # in the mono face, which made a folder listing look like a diff.
        self.browse_list.setObjectName("BrowseList")
        self.browse_list.setIconSize(QSize(0, 0))
        self.browse_list.setToolTip("Caches and dot-folders are hidden")
        self.browse_list.itemActivated.connect(self._on_browse_activated)
        self._folder_icon = browse_folder_icon(14)
        self._file_icon = browse_file_icon(14)
        self._fusion_style = QStyleFactory.create("Fusion")
        if self._fusion_style is not None:
            self._fusion_style.setParent(self)
            self.browse_list.setStyle(self._fusion_style)
            self.desk_list.setStyle(self._fusion_style)
        left_l.addWidget(self.browse_list, stretch=1)

        mid = QWidget()
        mid.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        mid_l = QVBoxLayout(mid)
        mid_l.setContentsMargins(8, 0, 0, 0)
        mid_l.setSpacing(8)
        read_row = QHBoxLayout()
        read_row.setSpacing(6)
        self.read_btn = QPushButton("read")
        self.edit_btn = QPushButton("edit")
        for btn, tip in (
            (self.read_btn, "Read this note as a page"),
            (self.edit_btn, "Edit the source"),
        ):
            btn.setObjectName("InstrumentAction")
            btn.setFixedHeight(METRICS["row"])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setToolTip(tip)
        self.read_btn.clicked.connect(lambda: self._show_preview(True))
        self.edit_btn.clicked.connect(lambda: self._show_preview(False))
        self.open_outside_btn = QPushButton("open")
        self.open_outside_btn.setObjectName("InstrumentAction")
        self.open_outside_btn.setFixedHeight(METRICS["row"])
        self.open_outside_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_outside_btn.setToolTip("Open in the usual app")
        self.open_outside_btn.clicked.connect(self._open_loaded_outside)
        read_row.addWidget(self.read_btn)
        read_row.addWidget(self.edit_btn)
        read_row.addWidget(self.open_outside_btn)
        read_row.addStretch(1)
        mid_l.addLayout(read_row)
        self.editor_stack = QStackedWidget()
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("Editor")
        self.editor.setPlaceholderText(
            "Pick something on the desk, or keep a note."
        )
        self.editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._highlight = QuietPythonHighlighter(self.editor.document())
        self._highlight.set_enabled(False)
        self.preview = QTextBrowser()
        self.preview.setObjectName("DeskPreview")
        self.preview.setOpenExternalLinks(False)
        self.preview.setPlaceholderText("")
        self.binary_label = QLabel("This file opens in the usual app.")
        self.binary_label.setObjectName("DeskEmpty")
        self.binary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.binary_label.setWordWrap(True)
        self.editor_stack.addWidget(self.editor)
        self.editor_stack.addWidget(self.preview)
        self.editor_stack.addWidget(self.binary_label)
        mid_l.addWidget(self.editor_stack, stretch=1)

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
        self.image_label.setObjectName(WELL_NAME)
        self.image_label.hide()
        right_layout.addWidget(self.image_label)

        caption_row = QHBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(SPACE["gap"])
        self.image_open_btn = QPushButton("open")
        self.image_open_btn.setObjectName("InstrumentAction")
        self.image_open_btn.setFixedHeight(METRICS["row"])
        self.image_open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.image_open_btn.setToolTip("Open in the usual app")
        self.image_open_btn.clicked.connect(self._open_loaded_outside)
        self.image_open_btn.hide()
        self.image_caption = QLabel("")
        self.image_caption.setObjectName(CAPTION_NAME)
        self.image_caption.setWordWrap(True)
        self.image_caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.image_caption.hide()
        caption_row.addWidget(self.image_open_btn)
        caption_row.addWidget(self.image_caption, stretch=1)
        right_layout.addLayout(caption_row)

        self.image_strip = QScrollArea()
        self.image_strip.setObjectName(STRIP_NAME)
        self.image_strip.setWidgetResizable(False)
        self.image_strip.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.image_strip.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.image_strip.setFrameShape(QScrollArea.Shape.NoFrame)
        self.image_strip.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.image_strip.setFixedHeight(_THUMB_LONG + SPACE["inset"])
        self.image_strip.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.image_strip.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.image_strip.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._image_strip_host = QWidget()
        self._image_strip_host.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self._image_strip_row = QHBoxLayout(self._image_strip_host)
        self._image_strip_row.setContentsMargins(0, 0, 0, 0)
        self._image_strip_row.setSpacing(SPACE["gap"])
        self._image_strip_row.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.image_strip.setWidget(self._image_strip_host)
        self.image_strip.hide()
        right_layout.addWidget(self.image_strip)

        self.split.addWidget(left)
        self.split.addWidget(mid)
        self.split.addWidget(right)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setCollapsible(0, True)
        self.split.setCollapsible(1, True)
        self.split.setCollapsible(2, True)
        self.split.setSizes([240, 720, 0])
        self.face_stack = QStackedWidget()
        self.face_stack.setObjectName("WorkspaceFace")
        self.face_stack.addWidget(self.empty_face)
        self.face_stack.addWidget(self.split)
        layout.addWidget(self.face_stack, stretch=1)

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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.show_desk()
        self._sync_chrome()

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
        self._sync_desk_hint()
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
        self._sync_desk_hint()
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
        try:
            can_up = cwd.resolve() != root.resolve()
        except OSError:
            can_up = False
        if can_up:
            up = QListWidgetItem("..")
            up.setData(Qt.ItemDataRole.UserRole, "..")
            self.browse_list.addItem(up)
        for entry in shown:
            item = QListWidgetItem(entry.name)
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
        if raw == "..":
            self._browse_up()
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
        self._apply_page_mode(abs_path or display, content)
        self._sync_dirty()
        self._sync_chrome()
        self._sync_face()
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
        self.show_folders()

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
        target = Path(path)
        self._hero_path = str(target)
        self._loaded_abs = str(target)
        self._loaded_label = target.name
        self._set_image_mode(True)
        self.image_label.show()
        self.path_edit.setText(str(target))
        tip = _sidecar_tooltip(target)
        self.image_label.setToolTip(tip)
        self.image_caption.setText(sidecar_caption(target))
        self.image_caption.setToolTip(tip)
        self.image_caption.show()
        self.image_open_btn.show()
        pix = self._fitted_hero(target)
        if pix.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(load_fail_line(target))
            self._refresh_image_strip(str(target))
            return
        self.image_label.setText("")
        self.image_label.setPixmap(pix)
        self._refresh_image_strip(str(target))
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _fitted_hero(self, path: Path | str) -> QPixmap:
        target_w = max(self.image_label.width(), self.width() // 2, 420)
        target_h = max(self.image_label.height(), 280)
        return load_fitted_pixmap(path, target_w, target_h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._image_mode or not self._hero_path:
            return
        pix = self._fitted_hero(self._hero_path)
        if not pix.isNull():
            self.image_label.setText("")
            self.image_label.setPixmap(pix)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._image_mode and event.key() in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            delta = 1 if event.key() == Qt.Key.Key_Right else -1
            if self._step_image(delta):
                event.accept()
                return
        super().keyPressEvent(event)

    def _step_image(self, delta: int) -> bool:
        if not self._image_paths:
            return False
        current = Path(self._hero_path) if self._hero_path else None
        try:
            index = next(
                i
                for i, path in enumerate(self._image_paths)
                if current is not None and path.resolve() == current.resolve()
            )
        except (StopIteration, OSError):
            index = 0
        nxt = self._image_paths[(index + delta) % len(self._image_paths)]
        self.show_image(str(nxt))
        return True

    def _set_image_mode(self, on: bool) -> None:
        """Image takes the right well; the editor yields. Status stays a strip."""
        self._image_mode = on
        if on:
            self.editor_stack.hide()
            self.read_btn.hide()
            self.edit_btn.hide()
            self.open_outside_btn.hide()
            self.image_label.show()
            self.image_caption.show()
            self.image_open_btn.show()
            self.split.setCollapsible(1, True)
            self.split.setCollapsible(2, False)
        else:
            self.editor_stack.show()
            self.image_label.hide()
            self.image_caption.hide()
            self.image_open_btn.hide()
            self.image_strip.hide()
            self._hero_path = ""
            self._image_paths = []
            self._clear_image_strip()
            self.split.setCollapsible(1, True)
            self.split.setCollapsible(2, True)
            self._sync_chrome()
        if self.output.toPlainText().strip():
            self.output.show()
        else:
            self.output.hide()
        self._sync_face()

    def _clear_image_strip(self) -> None:
        row = self._image_strip_row
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _fit_image_strip(self) -> None:
        thumbs: list[QWidget] = []
        for i in range(self._image_strip_row.count()):
            widget = self._image_strip_row.itemAt(i).widget()
            if widget is not None:
                thumbs.append(widget)
        gap = self._image_strip_row.spacing()
        width = sum(thumb.width() for thumb in thumbs)
        if thumbs:
            width += gap * (len(thumbs) - 1)
        self._image_strip_host.setFixedSize(max(width, 1), _THUMB_LONG)

    def _make_strip_thumb(self, path: Path, *, current: bool) -> QToolButton:
        btn = QToolButton()
        btn.setObjectName(THUMB_NAME)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setAutoRaise(False)
        btn.setCheckable(True)
        btn.setChecked(current)
        btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setToolTip(_sidecar_tooltip(path))
        btn.setAccessibleName(path.name)
        btn.setFixedSize(_THUMB_LONG, _THUMB_LONG)
        pix = load_square_thumb(path, _THUMB_LONG)
        if pix.isNull():
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setText(path.name)
        else:
            btn.setIcon(QIcon(pix))
            btn.setIconSize(QSize(_THUMB_LONG, _THUMB_LONG))
        target = str(path)
        btn.clicked.connect(lambda _checked=False, p=target: self.show_image(p))
        return btn

    def _refresh_image_strip(self, path: str) -> None:
        images = _recent_output_images(Path(path).parent)
        self._image_paths = images
        self._clear_image_strip()
        if not images:
            self.image_strip.hide()
            return
        current = Path(path)
        for image in images:
            try:
                is_current = image.resolve() == current.resolve()
            except OSError:
                is_current = image.name == current.name
            self._image_strip_row.addWidget(
                self._make_strip_thumb(image, current=is_current)
            )
        self._fit_image_strip()
        self.image_strip.show()

    def set_desk_context(self, *, room_id: str = "", room_name: str = "") -> None:
        self._room_id = room_id
        self._room_name = room_name
        self._sync_desk_hint()

    def set_desk_items(self, items: list[Artifact] | list[dict]) -> None:
        parsed: list[Artifact] = []
        for raw in items:
            if isinstance(raw, Artifact):
                parsed.append(raw)
                continue
            if not isinstance(raw, dict):
                continue
            abs_path = str(raw.get("abs_path") or "").strip()
            if not abs_path:
                continue
            parsed.append(
                Artifact(
                    abs_path=abs_path,
                    label=str(raw.get("label") or Path(abs_path).name),
                    kind=str(raw.get("kind") or "file"),
                    source=str(raw.get("source") or "open"),
                    root_name=str(raw.get("root_name") or ""),
                    room_id=str(raw.get("room_id") or ""),
                    created_at=str(raw.get("created_at") or ""),
                    last_seen=str(raw.get("last_seen") or ""),
                    pinned=bool(raw.get("pinned")),
                )
            )
        pinned = [item for item in parsed if item.pinned]
        rest = [item for item in parsed if not item.pinned]
        self._desk_items = pinned + rest
        self.desk_list.clear()
        for item in self._desk_items:
            pin = "pinned · " if item.pinned else ""
            kind = item.kind or "file"
            row = QListWidgetItem(f"{item.label}\n{pin}{kind}")
            row.setData(Qt.ItemDataRole.UserRole, item.abs_path)
            row.setToolTip(item.abs_path)
            self.desk_list.addItem(row)
        self.desk_list.setVisible(bool(parsed) and self._mode == "desk")
        self._sync_desk_hint()
        self._sync_face()

    def show_desk(self) -> None:
        self._mode = "desk"
        self.desk_btn.setChecked(True)
        self.folders_btn.setChecked(False)
        self.desk_list.setVisible(bool(self._desk_items))
        self.desk_hint.setVisible(True)
        self.browse_label.hide()
        self.browse_list.hide()
        self._sync_chrome()
        self._sync_face()

    def show_folders(self) -> None:
        self._mode = "files"
        self.desk_btn.setChecked(False)
        self.folders_btn.setChecked(True)
        self.desk_list.hide()
        self.desk_hint.setVisible(True)
        self.browse_label.show()
        self.browse_list.show()
        self.refresh_browse()
        self._sync_chrome()
        self._sync_face()

    def _desk_idle(self) -> bool:
        return (
            self._mode == "desk"
            and not self._desk_items
            and not self._loaded_abs
            and not self._image_mode
        )

    def _sync_face(self) -> None:
        """Empty desk is one face. The editor only exists when there is a file."""
        idle = self._desk_idle()
        self.face_stack.setCurrentWidget(self.empty_face if idle else self.split)
        if idle:
            return
        left = self.split.widget(0)
        mid = self.split.widget(1)
        right = self.split.widget(2)
        show_left = self._mode == "files" or bool(self._desk_items)
        if left is not None:
            left.setVisible(show_left)
        if self._image_mode:
            if mid is not None:
                mid.hide()
            if right is not None:
                right.show()
            self.split.setSizes([180 if show_left else 0, 0, 620])
            return
        if right is not None:
            right.hide()
        has_file = bool(self._loaded_abs)
        if mid is not None:
            mid.setVisible(has_file)
        if has_file:
            self.split.setSizes([240 if show_left else 0, 720, 0])
        else:
            self.split.setSizes([240 if show_left else 1, 0, 0])

    def _sync_desk_hint(self) -> None:
        room = (self._room_name or "").strip()
        room_id = (self._room_id or "").strip()
        # Reality is a zone, not a papers room. The combo already names
        # the project; do not stamp the physics plate onto this chrome.
        if (
            room_id == PHYSICS_ROOM_ID
            or room.casefold() == PHYSICS_DISPLAY_NAME.casefold()
        ):
            room = ""
        project = self.project_combo.currentText() or self._root_name
        if room and project:
            self.desk_hint.setText(f"{room} · {project}")
        elif project:
            self.desk_hint.setText(f"{project} · papers")
        else:
            self.desk_hint.setText("this project's papers")

    def _sync_chrome(self) -> None:
        files_mode = self._mode == "files"
        has_file = bool(self._loaded_abs)
        self.path_edit.setVisible(files_mode or has_file)
        self.open_btn.setVisible(files_mode)
        self.save_btn.setVisible(has_file and not self._image_mode)
        self.recent_combo.setVisible(files_mode)
        suffix = Path(self._loaded_abs or self.path_edit.text()).suffix.lower()
        md = suffix == ".md"
        _binary = has_file and not is_text_kind(
            infer_kind(self._loaded_abs or "", source=""),
            self._loaded_abs,
        ) and not is_image_kind(
            infer_kind(self._loaded_abs or "", source=""),
            self._loaded_abs,
        )
        self.read_btn.setVisible(md and has_file and not self._image_mode)
        self.edit_btn.setVisible(md and has_file and not self._image_mode)
        self.open_outside_btn.setVisible(has_file and not self._image_mode)

    def _apply_page_mode(self, path: str, content: str) -> None:
        kind = infer_kind(path)
        if is_image_kind(kind, path):
            return
        if not is_text_kind(kind, path):
            leaf = Path(path).name
            self.binary_label.setText(
                f"{leaf} opens in the usual app.\n"
                "Press open, or show it in its folder from the desk."
            )
            self.editor_stack.setCurrentWidget(self.binary_label)
            self.read_btn.setChecked(False)
            self.edit_btn.setChecked(False)
            self._sync_chrome()
            return
        suffix = Path(path).suffix.lower()
        if suffix == ".md" and not self._dirty:
            self._set_preview_text(content)
            self._show_preview(True)
        else:
            self._show_preview(False)
        self._sync_chrome()

    def _set_preview_text(self, content: str) -> None:
        shown = flatten_latex(content)
        try:
            self.preview.setMarkdown(shown)
        except Exception:
            self.preview.setPlainText(shown)

    def _show_preview(self, on: bool) -> None:
        self._preview_md = on
        if on:
            self._set_preview_text(self.editor.toPlainText())
            self.editor_stack.setCurrentWidget(self.preview)
        else:
            self.editor_stack.setCurrentWidget(self.editor)
        self.read_btn.setChecked(on)
        self.edit_btn.setChecked(not on)

    def _open_loaded_outside(self) -> None:
        path = self._loaded_abs or self.qualified_path()
        if path:
            self.outside_requested.emit(path)

    def _on_desk_activated(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if path:
            self.desk_open_requested.emit(path)

    def _on_desk_menu(self, pos) -> None:
        item = self.desk_list.itemAt(pos)
        if item is None:
            return
        path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not path:
            return
        pinned = False
        for art in self._desk_items:
            if art.abs_path == path:
                pinned = art.pinned
                break
        menu = QMenu(self)
        pin = menu.addAction("unpin" if pinned else "pin")
        drop = menu.addAction("take off the desk")
        show = menu.addAction("show in folder")
        chosen = menu.exec(self.desk_list.mapToGlobal(pos))
        if chosen is pin:
            self.pin_requested.emit(path, not pinned)
        elif chosen is drop:
            self.drop_requested.emit(path)
        elif chosen is show:
            self.reveal_requested.emit(path)
