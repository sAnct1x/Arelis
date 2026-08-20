"""Orbit-void calendar tile: month/week/day/agenda plus a tasks tab."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from PySide6.QtCore import QDate, QRect, QRectF, QSize, Qt, QTime, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from arelis.calendar.layout import (
    WEEKDAY_LABELS,
    event_spans_day,
    events_on_day,
    format_event_time,
    month_cells,
    month_title,
    parse_task_due,
    tasks_due_on_day,
    week_cells,
)
from arelis.calendar.models import CachedEvent
from arelis.calendar.store import CalendarStore
from arelis.memory.store import MemoryStore
from arelis.ui.theme import COLORS, METRICS, color

CHROME_TILE_SIZE = (1100, 800)
_HOUR_START = 6
_HOUR_END = 22
_VIEWS = ("month", "week", "day", "agenda")


def _c(name: str) -> QColor:
    return color(name)


class _Hit:
    __slots__ = ("rect", "kind", "payload")

    def __init__(self, rect: QRect, kind: str, payload: Any) -> None:
        self.rect = rect
        self.kind = kind
        self.payload = payload


def _row_button(text: str, *, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("InstrumentAction")
    btn.setFixedHeight(METRICS["row"])
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


class CalendarMonthView(QWidget):
    cell_clicked = Signal(object)  # date
    event_clicked = Signal(object)  # CachedEvent
    task_clicked = Signal(object)  # dict

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarMonthView")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._anchor = date.today()
        self._events: list[CachedEvent] = []
        self._tasks: list[dict[str, Any]] = []
        self._hits: list[_Hit] = []

    def set_anchor(self, day: date) -> None:
        self._anchor = day
        self.update()

    def set_events(self, events: list[CachedEvent]) -> None:
        self._events = list(events)
        self.update()

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self._tasks = list(tasks)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(720, 520)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._hits = []
        bounds = self.rect().adjusted(0, 0, -1, -1)
        header_h = 22
        grid = QRect(bounds.x(), bounds.y() + header_h, bounds.width(), bounds.height() - header_h)
        cols, rows = 7, 6
        cw = max(1, grid.width() / cols)
        ch = max(1, grid.height() / rows)
        cells = month_cells(self._anchor.year, self._anchor.month)
        today = date.today()

        p.setPen(_c("text_dim"))
        font = p.font()
        font.setPixelSize(11)
        p.setFont(font)
        for i, label in enumerate(WEEKDAY_LABELS):
            cell = QRect(int(bounds.x() + i * cw), bounds.y(), int(cw), header_h)
            p.drawText(cell, Qt.AlignmentFlag.AlignCenter, label)

        for i, day in enumerate(cells):
            r = i // cols
            c = i % cols
            rect = QRect(
                int(grid.x() + c * cw),
                int(grid.y() + r * ch),
                int(cw) - 1,
                int(ch) - 1,
            )
            self._hits.append(_Hit(rect, "cell", day))
            in_month = day.month == self._anchor.month
            p.setPen(QPen(_c("hairline"), 1))
            p.setBrush(_c("inset") if in_month else QColor(0, 0, 0, 0))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)
            if day == today:
                p.setPen(QPen(_c("accent"), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)

            num = QRect(rect.x() + 6, rect.y() + 4, rect.width() - 12, 16)
            p.setPen(_c("text") if in_month else _c("dim"))
            font = p.font()
            font.setPixelSize(12)
            p.setFont(font)
            p.drawText(num, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(day.day))

            y = rect.y() + 22
            for ev in events_on_day(self._events, day)[:4]:
                chip = QRect(rect.x() + 5, y, rect.width() - 10, 16)
                if chip.bottom() > rect.bottom() - 4:
                    break
                self._paint_chip(p, chip, format_event_time(ev), ev.summary, all_day=ev.all_day)
                self._hits.append(_Hit(chip, "event", ev))
                y += 18
            for task in tasks_due_on_day(self._tasks, day)[:2]:
                chip = QRect(rect.x() + 5, y, rect.width() - 10, 14)
                if chip.bottom() > rect.bottom() - 4:
                    break
                title = str(task.get("title") or "task")
                self._paint_chip(p, chip, "due", title, task=True)
                self._hits.append(_Hit(chip, "task", task))
                y += 16
        p.end()

    def _paint_chip(
        self,
        p: QPainter,
        rect: QRect,
        when: str,
        title: str,
        *,
        all_day: bool = False,
        task: bool = False,
    ) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), 4, 4)
        fill = _c("card_fill") if not all_day else _c("raised")
        if task:
            fill = _c("chip")
        p.fillPath(path, fill)
        p.setPen(QPen(_c("hairline_mid" if task else "edge"), 1))
        p.drawPath(path)
        p.setPen(_c("text_dim") if task else _c("accent2"))
        font = p.font()
        font.setPixelSize(10)
        p.setFont(font)
        label = f"{when}  {title}" if when else title
        p.drawText(
            rect.adjusted(5, 0, -4, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            label,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        # Prefer chips over the cell they sit in.
        for hit in reversed(self._hits):
            if not hit.rect.contains(pos):
                continue
            if hit.kind == "event":
                self.event_clicked.emit(hit.payload)
                return
            if hit.kind == "task":
                self.task_clicked.emit(hit.payload)
                return
            if hit.kind == "cell":
                self.cell_clicked.emit(hit.payload)
                return


class CalendarWeekView(QWidget):
    slot_clicked = Signal(object, int)  # date, hour
    event_clicked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarWeekView")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._anchor = date.today()
        self._events: list[CachedEvent] = []
        self._hits: list[_Hit] = []

    def set_anchor(self, day: date) -> None:
        self._anchor = day
        self.update()

    def set_events(self, events: list[CachedEvent]) -> None:
        self._events = list(events)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._hits = []
        days = week_cells(self._anchor)
        hours = _HOUR_END - _HOUR_START
        gutter = 44
        header_h = 28
        bounds = self.rect().adjusted(0, 0, -1, -1)
        body = QRect(
            bounds.x() + gutter,
            bounds.y() + header_h,
            bounds.width() - gutter,
            bounds.height() - header_h,
        )
        cw = max(1, body.width() / 7)
        ch = max(1, body.height() / hours)
        today = date.today()

        p.setPen(_c("text_dim"))
        font = p.font()
        font.setPixelSize(11)
        p.setFont(font)
        for i, day in enumerate(days):
            head = QRect(int(body.x() + i * cw), bounds.y(), int(cw), header_h)
            label = day.strftime("%a %d").lower()
            p.setPen(_c("accent") if day == today else _c("text_dim"))
            p.drawText(head, Qt.AlignmentFlag.AlignCenter, label)

        p.setPen(_c("dim"))
        font.setPixelSize(10)
        p.setFont(font)
        for h in range(hours):
            hour = _HOUR_START + h
            stamp = datetime(2000, 1, 1, hour).strftime("%I %p").lstrip("0").lower()
            label = QRect(bounds.x(), int(body.y() + h * ch), gutter - 4, int(ch))
            p.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, stamp)
            y = int(body.y() + h * ch)
            p.setPen(QPen(_c("hairline"), 1))
            p.drawLine(body.x(), y, body.right(), y)

        for i, day in enumerate(days):
            x = int(body.x() + i * cw)
            p.setPen(QPen(_c("hairline"), 1))
            p.drawLine(x, body.y(), x, body.bottom())
            for h in range(hours):
                slot = QRect(x, int(body.y() + h * ch), int(cw) - 1, int(ch))
                self._hits.append(_Hit(slot, "slot", (day, _HOUR_START + h)))
            for ev in events_on_day(self._events, day):
                rect = self._event_rect(ev, day, x, int(cw) - 2, body, ch)
                if rect is None:
                    continue
                self._hits.append(_Hit(rect, "event", ev))
                path = QPainterPath()
                path.addRoundedRect(QRectF(rect), 4, 4)
                p.fillPath(path, _c("raised"))
                p.setPen(QPen(_c("edge"), 1))
                p.drawPath(path)
                p.setPen(_c("accent2"))
                font.setPixelSize(10)
                p.setFont(font)
                p.drawText(
                    rect.adjusted(5, 2, -4, -2),
                    Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                    f"{format_event_time(ev)}  {ev.summary}",
                )
        p.end()

    def _event_rect(
        self,
        ev: CachedEvent,
        day: date,
        x: int,
        width: int,
        body: QRect,
        ch: float,
    ) -> QRect | None:
        if ev.all_day:
            return QRect(x + 2, body.y() + 2, width - 4, 16)
        start = ev.starts_at.astimezone() if ev.starts_at.tzinfo else ev.starts_at
        end = ev.ends_at or (ev.starts_at + timedelta(hours=1))
        end = end.astimezone() if end.tzinfo else end
        if start.date() != day and not event_spans_day(ev, day):
            return None
        start_h = start.hour + start.minute / 60
        end_h = end.hour + end.minute / 60
        if start.date() < day:
            start_h = _HOUR_START
        if end.date() > day:
            end_h = _HOUR_END
        top = body.y() + (start_h - _HOUR_START) * ch
        height = max(16.0, (end_h - start_h) * ch)
        return QRect(x + 2, int(top), width - 4, int(height))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        for hit in reversed(self._hits):
            if not hit.rect.contains(pos):
                continue
            if hit.kind == "event":
                self.event_clicked.emit(hit.payload)
                return
            if hit.kind == "slot":
                day, hour = hit.payload
                self.slot_clicked.emit(day, hour)
                return


class CalendarDayView(CalendarWeekView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarDayView")

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._hits = []
        day = self._anchor
        hours = _HOUR_END - _HOUR_START
        gutter = 52
        bounds = self.rect().adjusted(0, 0, -1, -1)
        body = QRect(bounds.x() + gutter, bounds.y() + 8, bounds.width() - gutter, bounds.height() - 16)
        ch = max(1, body.height() / hours)
        p.setPen(_c("dim"))
        font = p.font()
        font.setPixelSize(10)
        p.setFont(font)
        for h in range(hours):
            hour = _HOUR_START + h
            stamp = datetime(2000, 1, 1, hour).strftime("%I:%M %p").lstrip("0").lower()
            label = QRect(bounds.x(), int(body.y() + h * ch), gutter - 6, int(ch))
            p.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, stamp)
            y = int(body.y() + h * ch)
            p.setPen(QPen(_c("hairline"), 1))
            p.drawLine(body.x(), y, body.right(), y)
            slot = QRect(body.x(), y, body.width(), int(ch))
            self._hits.append(_Hit(slot, "slot", (day, hour)))
        for ev in events_on_day(self._events, day):
            rect = self._event_rect(ev, day, body.x() + 4, body.width() - 12, body, ch)
            if rect is None:
                continue
            self._hits.append(_Hit(rect, "event", ev))
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), 5, 5)
            p.fillPath(path, _c("raised"))
            p.setPen(QPen(_c("edge_mid"), 1))
            p.drawPath(path)
            p.setPen(_c("accent2"))
            font.setPixelSize(12)
            p.setFont(font)
            p.drawText(
                rect.adjusted(8, 4, -6, -4),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                f"{format_event_time(ev)}\n{ev.summary}",
            )
        p.end()


class CalendarAgendaView(QWidget):
    event_clicked = Signal(object)
    empty_day_clicked = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarAgendaView")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setObjectName("CalendarAgendaList")
        self.list.itemActivated.connect(self._on_item)
        layout.addWidget(self.list)
        self._events: list[CachedEvent] = []
        self._anchor = date.today()

    def set_anchor(self, day: date) -> None:
        self._anchor = day
        self._rebuild()

    def set_events(self, events: list[CachedEvent]) -> None:
        self._events = list(events)
        self._rebuild()

    def _rebuild(self) -> None:
        self.list.clear()
        start = self._anchor
        finish = start + timedelta(days=21)
        rows = [
            ev
            for ev in self._events
            if ev.starts_at.date() <= finish and (ev.ends_at or ev.starts_at).date() >= start
        ]
        rows.sort(key=lambda ev: (ev.starts_at, ev.summary.lower()))
        if not rows:
            item = QListWidgetItem("nothing on the calendar in this stretch")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
            return
        last_day: date | None = None
        for ev in rows:
            day = ev.starts_at.date()
            if day != last_day:
                heading = QListWidgetItem(day.strftime("%A, %d %B").lower())
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                heading.setData(Qt.ItemDataRole.UserRole, None)
                self.list.addItem(heading)
                last_day = day
            line = QListWidgetItem(f"{format_event_time(ev)}  {ev.summary}")
            line.setData(Qt.ItemDataRole.UserRole, ev)
            self.list.addItem(line)

    def _on_item(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(payload, CachedEvent):
            self.event_clicked.emit(payload)


class EventSheet(QWidget):
    save_requested = Signal(dict)
    delete_requested = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarEventSheet")
        self._event_id = ""
        self._provider = ""
        self._calendar_id = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.heading = QLabel("new event")
        self.heading.setObjectName("InstrumentTitle")
        root.addWidget(self.heading)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("InstrumentSearch")
        self.title_edit.setPlaceholderText("title")
        self.title_edit.setFixedHeight(METRICS["row"])
        form.addRow("title", self.title_edit)

        self.all_day = QCheckBox("all day")
        self.all_day.toggled.connect(self._on_all_day)
        form.addRow("", self.all_day)

        self.date_edit = QDateEdit()
        self.date_edit.setObjectName("CalendarDate")
        self.date_edit.setCalendarPopup(False)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setFixedHeight(METRICS["row"])
        form.addRow("date", self.date_edit)

        times = QHBoxLayout()
        times.setSpacing(8)
        self.start_time = QTimeEdit()
        self.end_time = QTimeEdit()
        for widget in (self.start_time, self.end_time):
            widget.setObjectName("CalendarTime")
            widget.setDisplayFormat("hh:mm AP")
            widget.setFixedHeight(METRICS["row"])
        times.addWidget(self.start_time)
        times.addWidget(self.end_time)
        form.addRow("time", times)

        self.location_edit = QLineEdit()
        self.location_edit.setObjectName("InstrumentSearch")
        self.location_edit.setPlaceholderText("optional")
        self.location_edit.setFixedHeight(METRICS["row"])
        form.addRow("place", self.location_edit)

        self.notes_edit = QLineEdit()
        self.notes_edit.setObjectName("InstrumentSearch")
        self.notes_edit.setPlaceholderText("optional notes")
        self.notes_edit.setFixedHeight(METRICS["row"])
        form.addRow("notes", self.notes_edit)
        root.addLayout(form)
        root.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.delete_btn = _row_button("delete", tooltip="remove this event")
        self.delete_btn.setObjectName("CalendarDelete")
        self.delete_btn.clicked.connect(self._on_delete)
        self.cancel_btn = _row_button("cancel")
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        self.save_btn = _row_button("save")
        self.save_btn.clicked.connect(self._on_save)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.save_btn)
        root.addLayout(row)

    def open_new(self, day: date, *, hour: int | None = None) -> None:
        self._event_id = ""
        self._provider = ""
        self._calendar_id = ""
        self.heading.setText("new event")
        self.title_edit.setText("")
        self.location_edit.setText("")
        self.notes_edit.setText("")
        self.all_day.setChecked(hour is None)
        self.date_edit.setDate(QDate(day.year, day.month, day.day))
        start = QTime(9 if hour is None else hour, 0)
        self.start_time.setTime(start)
        self.end_time.setTime(start.addSecs(3600))
        self.delete_btn.hide()
        self._on_all_day(self.all_day.isChecked())
        self.title_edit.setFocus()

    def open_event(self, ev: CachedEvent) -> None:
        self._event_id = ev.id
        self._provider = ev.provider
        self._calendar_id = ev.calendar_id
        self.heading.setText("edit event")
        self.title_edit.setText(ev.summary)
        self.location_edit.setText(ev.location or "")
        self.notes_edit.setText(ev.description or "")
        self.all_day.setChecked(ev.all_day)
        local = ev.starts_at.astimezone() if ev.starts_at.tzinfo else ev.starts_at
        self.date_edit.setDate(QDate(local.year, local.month, local.day))
        self.start_time.setTime(QTime(local.hour, local.minute))
        end = ev.ends_at or (ev.starts_at + timedelta(hours=1))
        end = end.astimezone() if end.tzinfo else end
        self.end_time.setTime(QTime(end.hour, end.minute))
        self.delete_btn.show()
        self._on_all_day(ev.all_day)
        self.title_edit.setFocus()

    def _on_all_day(self, checked: bool) -> None:
        self.start_time.setEnabled(not checked)
        self.end_time.setEnabled(not checked)

    def _on_save(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setFocus()
            return
        qdate = self.date_edit.date()
        day = date(qdate.year(), qdate.month(), qdate.day())
        all_day = self.all_day.isChecked()
        tz = datetime.now().astimezone().tzinfo
        if all_day:
            starts = datetime(day.year, day.month, day.day, tzinfo=tz)
            ends = starts + timedelta(days=1)
        else:
            st = self.start_time.time()
            et = self.end_time.time()
            starts = datetime(day.year, day.month, day.day, st.hour(), st.minute(), tzinfo=tz)
            ends = datetime(day.year, day.month, day.day, et.hour(), et.minute(), tzinfo=tz)
            if ends <= starts:
                ends = starts + timedelta(hours=1)
        self.save_requested.emit(
            {
                "event_id": self._event_id,
                "provider": self._provider,
                "calendar_id": self._calendar_id,
                "summary": title,
                "starts_at": starts,
                "ends_at": ends,
                "all_day": all_day,
                "location": self.location_edit.text().strip(),
                "description": self.notes_edit.text().strip(),
            }
        )

    def _on_delete(self) -> None:
        if self._event_id:
            self.delete_requested.emit(self._event_id)


class TasksPage(QWidget):
    add_requested = Signal(str, str)
    status_requested = Signal(int, str)
    remove_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarTasksPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        add = QHBoxLayout()
        add.setSpacing(6)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("InstrumentSearch")
        self.title_edit.setPlaceholderText("new task")
        self.title_edit.setFixedHeight(METRICS["row"])
        self.title_edit.returnPressed.connect(self._on_add)
        self.due_edit = QLineEdit()
        self.due_edit.setObjectName("InstrumentSearch")
        self.due_edit.setPlaceholderText("due YYYY-MM-DD")
        self.due_edit.setFixedHeight(METRICS["row"])
        self.due_edit.setMaximumWidth(140)
        self.add_btn = _row_button("add")
        self.add_btn.clicked.connect(self._on_add)
        add.addWidget(self.title_edit, stretch=1)
        add.addWidget(self.due_edit)
        add.addWidget(self.add_btn)
        root.addLayout(add)

        self.show_done = QCheckBox("show done")
        self.show_done.toggled.connect(self._rebuild)
        root.addWidget(self.show_done)

        self.list = QListWidget()
        self.list.setObjectName("CalendarTaskList")
        root.addWidget(self.list, stretch=1)
        self._tasks: list[dict[str, Any]] = []

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self._tasks = list(tasks)
        self._rebuild()

    def _rebuild(self) -> None:
        self.list.clear()
        show_done = self.show_done.isChecked()
        rows = [
            row
            for row in self._tasks
            if show_done or str(row.get("status") or "open") == "open"
        ]
        if not rows:
            item = QListWidgetItem("no open tasks")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
            return
        for row in rows:
            widget = QWidget()
            widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            line = QHBoxLayout(widget)
            line.setContentsMargins(4, 2, 4, 2)
            line.setSpacing(8)
            box = QCheckBox()
            tid = int(row["id"])
            box.blockSignals(True)
            box.setChecked(str(row.get("status")) == "done")
            box.blockSignals(False)
            box.toggled.connect(
                lambda checked, task_id=tid: self.status_requested.emit(
                    task_id, "done" if checked else "open"
                )
            )
            title = QLabel(str(row.get("title") or ""))
            title.setObjectName("CalendarTaskTitle")
            due = parse_task_due(row.get("due"))
            due_l = QLabel(due.isoformat() if due else "")
            due_l.setObjectName("InstrumentHint")
            remove = _row_button("remove")
            remove.clicked.connect(lambda _=False, task_id=tid: self.remove_requested.emit(task_id))
            line.addWidget(box)
            line.addWidget(title, stretch=1)
            line.addWidget(due_l)
            line.addWidget(remove)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint().expandedTo(QSize(100, METRICS["row"] + 8)))
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)

    def _on_add(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            return
        self.add_requested.emit(title, self.due_edit.text().strip())
        self.title_edit.clear()


class CalendarPanel(QWidget):
    create_requested = Signal(dict)
    update_requested = Signal(dict)
    delete_requested = Signal(str)
    sync_requested = Signal()
    task_add_requested = Signal(str, str)
    task_status_requested = Signal(int, str)
    task_remove_requested = Signal(int)

    def __init__(self, parent=None, *, memory: MemoryStore | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CalendarPanel")
        self._memory = memory
        self._anchor = date.today()
        self._view = "month"
        self._events: list[CachedEvent] = []
        self._tasks: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("CalendarTabs")
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        calendar_page = QWidget()
        calendar_page.setObjectName("CalendarTabBody")
        cal_layout = QVBoxLayout(calendar_page)
        cal_layout.setContentsMargins(0, 8, 0, 0)
        cal_layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.prev_btn = _row_button("prev")
        self.today_btn = _row_button("today")
        self.next_btn = _row_button("next")
        self.prev_btn.clicked.connect(lambda: self._shift(-1))
        self.next_btn.clicked.connect(lambda: self._shift(1))
        self.today_btn.clicked.connect(self._go_today)
        self.title_label = QLabel(month_title(self._anchor))
        self.title_label.setObjectName("CalendarMonthTitle")
        bar.addWidget(self.prev_btn)
        bar.addWidget(self.today_btn)
        bar.addWidget(self.next_btn)
        bar.addWidget(self.title_label, stretch=1)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        self._view_btns: dict[str, QPushButton] = {}
        for name in _VIEWS:
            btn = _row_button(name)
            btn.setCheckable(True)
            btn.setChecked(name == "month")
            btn.clicked.connect(lambda _=False, view=name: self._set_view(view))
            self._view_group.addButton(btn)
            self._view_btns[name] = btn
            bar.addWidget(btn)

        self.sync_btn = _row_button("sync", tooltip="pull from Google")
        self.sync_btn.clicked.connect(self.sync_requested.emit)
        self.new_btn = _row_button("new")
        self.new_btn.clicked.connect(lambda: self._open_new(self._anchor))
        self.status = QLabel("")
        self.status.setObjectName("InstrumentHint")
        bar.addWidget(self.status)
        bar.addWidget(self.sync_btn)
        bar.addWidget(self.new_btn)
        cal_layout.addLayout(bar)

        self.views = QStackedWidget()
        self.month_view = CalendarMonthView()
        self.week_view = CalendarWeekView()
        self.day_view = CalendarDayView()
        self.agenda_view = CalendarAgendaView()
        self.sheet = EventSheet()
        for widget in (
            self.month_view,
            self.week_view,
            self.day_view,
            self.agenda_view,
            self.sheet,
        ):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.views.addWidget(widget)
        cal_layout.addWidget(self.views, stretch=1)

        self.month_view.cell_clicked.connect(self._open_new)
        self.month_view.event_clicked.connect(self._open_event)
        self.month_view.task_clicked.connect(lambda _task: self.tabs.setCurrentIndex(1))
        self.week_view.event_clicked.connect(self._open_event)
        self.week_view.slot_clicked.connect(self._open_slot)
        self.day_view.event_clicked.connect(self._open_event)
        self.day_view.slot_clicked.connect(self._open_slot)
        self.agenda_view.event_clicked.connect(self._open_event)
        self.sheet.save_requested.connect(self._on_sheet_save)
        self.sheet.delete_requested.connect(self.delete_requested.emit)
        self.sheet.cancelled.connect(self._close_sheet)

        self.tabs.addTab(calendar_page, "calendar")

        self.tasks_page = TasksPage()
        self.tasks_page.add_requested.connect(self.task_add_requested.emit)
        self.tasks_page.status_requested.connect(self.task_status_requested.emit)
        self.tasks_page.remove_requested.connect(self.task_remove_requested.emit)
        self.tabs.addTab(self.tasks_page, "tasks")

        self.reload()

    def set_status(self, text: str, *, failed: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("failed", "1" if failed else "0")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def reload(self) -> None:
        start, end = self._window()
        store = CalendarStore()
        try:
            self._events = store.list_range(start, end)
        finally:
            store.close()
        self.reload_tasks()
        self._paint()

    def reload_tasks(self) -> None:
        if self._memory is None:
            self._tasks = []
        else:
            try:
                self._tasks = self._memory.list_tasks(status=None, limit=200)
            except Exception:
                self._tasks = []
        self.tasks_page.set_tasks(self._tasks)
        self._paint()

    def set_events(self, events: list[CachedEvent]) -> None:
        """Test hook: skip the cache and paint these events."""
        self._events = list(events)
        self._paint()

    def close_sheet(self) -> None:
        self._close_sheet()

    def _window(self) -> tuple[date, date]:
        if self._view == "week":
            days = week_cells(self._anchor)
            return days[0], days[-1]
        if self._view == "day":
            return self._anchor, self._anchor
        if self._view == "agenda":
            return self._anchor, self._anchor + timedelta(days=21)
        cells = month_cells(self._anchor.year, self._anchor.month)
        return cells[0], cells[-1]

    def _paint(self) -> None:
        self.title_label.setText(month_title(self._anchor) if self._view == "month" else self._anchor.strftime("%A, %d %B").lower())
        for view in (self.month_view, self.week_view, self.day_view, self.agenda_view):
            view.set_anchor(self._anchor)
            view.set_events(self._events)
        self.month_view.set_tasks(self._tasks)

    def _set_view(self, name: str) -> None:
        self._view = name
        for key, btn in self._view_btns.items():
            btn.setChecked(key == name)
        index = _VIEWS.index(name)
        self.views.setCurrentIndex(index)
        self.reload()

    def _shift(self, delta: int) -> None:
        self._close_sheet()
        if self._view == "month":
            month = self._anchor.month + delta
            year = self._anchor.year
            while month < 1:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1
            self._anchor = date(year, month, 1)
        elif self._view == "week":
            self._anchor = self._anchor + timedelta(days=7 * delta)
        else:
            self._anchor = self._anchor + timedelta(days=delta)
        self.reload()

    def _go_today(self) -> None:
        self._close_sheet()
        self._anchor = date.today()
        self.reload()

    def _open_new(self, day: date, hour: int | None = None) -> None:
        self._anchor = day
        self.sheet.open_new(day, hour=hour)
        self.views.setCurrentWidget(self.sheet)

    def _open_slot(self, day: date, hour: int) -> None:
        self._open_new(day, hour)

    def _open_event(self, ev: CachedEvent) -> None:
        self.sheet.open_event(ev)
        self.views.setCurrentWidget(self.sheet)

    def _close_sheet(self) -> None:
        index = _VIEWS.index(self._view)
        self.views.setCurrentIndex(index)

    def _on_sheet_save(self, payload: dict[str, Any]) -> None:
        if payload.get("event_id"):
            self.update_requested.emit(payload)
        else:
            self.create_requested.emit(payload)
        self._close_sheet()
