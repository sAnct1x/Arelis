"""The room sheet as two layers: structure that never changes, colour that does.

Every room's sheet has the same rules with the same properties; only colour
values differ. Splitting by property family keeps each property in exactly one
layer, so no rule in one layer can override a rule in the other and the
cascade inside each layer is the one the full sheet had.
"""

from __future__ import annotations

import re
from functools import lru_cache

# Properties that carry a room colour, and every property that shares a
# shorthand with one. A border width rides with its colour in `border:`.
COLOUR_FAMILIES = ("background", "border", "color", "selection")

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _is_colour(decl: str) -> bool:
    return decl.split(":", 1)[0].strip().lower().startswith(COLOUR_FAMILIES)


@lru_cache(maxsize=8)
def split_sheet(css: str) -> tuple[str, str]:
    """Return (structural, colour) for one full room sheet."""
    structural: list[str] = []
    colour: list[str] = []
    for match in _RULE.finditer(_COMMENT.sub("", css)):
        selector = " ".join(match.group(1).split())
        decls = [d.strip() for d in match.group(2).split(";") if d.strip()]
        keep = [d for d in decls if not _is_colour(d)]
        paint = [d for d in decls if _is_colour(d)]
        if keep:
            structural.append(f"{selector} {{ {'; '.join(keep)}; }}")
        if paint:
            colour.append(f"{selector} {{ {'; '.join(paint)}; }}")
    return "\n".join(structural), "\n".join(colour)


# The hub (the parentless main window) owns the tile windows, so a sheet on it
# would re-match every hidden tile too. It carries no sheet: its own few colour
# rules live in the app sheet, gated on this property, one copy per room, and
# its colour layer goes on each of its non-window children instead.
HUB_PROPERTY = "arelisTheme"
_STAMP = "_arelis_colour_room"
_OWN = "_arelis_own_sheet"
_FILTER = "_arelis_colour_filter"
_HUB_SUBJECTS = frozenset({"", "*", "QWidget", "QMainWindow"})
_PSEUDO = re.compile(r"[:]")


def _subject_head(item: str) -> str:
    subject = item.replace(">", " ").split()[-1]
    return re.split(r"[:#.\[]", subject, maxsplit=1)[0]


def _gate(item: str, room: str) -> str:
    """Add the hub property to the subject compound, before any pseudo part."""
    head, _, subject = item.rpartition(" ")
    cut = _PSEUDO.search(subject)
    at = cut.start() if cut else len(subject)
    gated = f'{subject[:at]}[{HUB_PROPERTY}="{room}"]{subject[at:]}'
    return f"{head} {gated}".strip()


def hub_rules(colour_by_room: dict[str, str]) -> str:
    """The colour rules that can land on the hub itself, gated per room."""
    out: list[str] = []
    for room, colour in colour_by_room.items():
        for line in colour.splitlines():
            selector, _, body = line.partition("{")
            items = [i.strip() for i in selector.split(",")]
            items = [i for i in items if _subject_head(i) in _HUB_SUBJECTS]
            if items:
                out.append(f"{', '.join(_gate(i, room) for i in items)} {{{body}")
    return "\n".join(out)


def is_hub(widget) -> bool:
    from PySide6.QtWidgets import QMainWindow

    return widget.parentWidget() is None and isinstance(widget, QMainWindow)


def is_colour_root(widget) -> bool:
    """A widget that carries a colour layer: a window not already under one,
    or a non-window child of the hub."""
    if is_hub(widget):
        return False
    parent = widget.parentWidget()
    if not widget.isWindow():
        return parent is not None and is_hub(parent)
    while parent is not None:
        if is_hub(parent):
            return True
        if is_colour_root(parent):
            return False
        parent = parent.parentWidget()
    return True


def colour_roots(app) -> list:
    roots = []
    for top in app.topLevelWidgets():
        if is_hub(top):
            roots.extend(c for c in top.children() if _is_widget(c) and not c.isWindow())
        elif is_colour_root(top):
            roots.append(top)
    return roots


def _is_widget(obj) -> bool:
    from PySide6.QtWidgets import QWidget

    return isinstance(obj, QWidget)


def apply_colour(widget, room: str, colour: str) -> None:
    own = getattr(widget, _OWN, "")
    css = f"{colour}\n{own}" if own else colour
    if widget.styleSheet() != css:
        widget.setStyleSheet(css)
    setattr(widget, _STAMP, room)


def set_own_sheet(widget, css: str) -> None:
    """Give a widget its own sheet without dropping a colour layer it carries."""
    setattr(widget, _OWN, css)
    if getattr(widget, _STAMP, None) is not None:
        apply_colour(widget, widget.__dict__[_STAMP], _current()[1])
    elif widget.styleSheet() != css:
        widget.setStyleSheet(css)


def stamp(widget) -> str | None:
    return getattr(widget, _STAMP, None)


def _current() -> tuple[str, str]:
    from arelis.ui.theme_qss import stylesheet
    from arelis.ui.theme_tokens import active_theme

    return active_theme(), split_sheet(stylesheet())[1]


def restyle(app, *, hidden: bool) -> None:
    """Put the current room's colour on every visible root, and on hidden ones
    too when asked. A hidden root is restyled when it is next shown."""
    room, colour = _current()
    for top in app.topLevelWidgets():
        if is_hub(top) and top.property(HUB_PROPERTY) != room:
            top.setProperty(HUB_PROPERTY, room)
            top.style().unpolish(top)
            top.style().polish(top)
            top.update()
    for root in colour_roots(app):
        if (hidden or root.isVisible()) and stamp(root) != room:
            apply_colour(root, room, colour)
    _ensure_show_filter(app)


def _ensure_show_filter(app) -> None:
    if getattr(app, _FILTER, None) is not None:
        return
    from PySide6.QtCore import QEvent, QObject

    show = QEvent.Type.Show

    class _ColourOnShow(QObject):
        def eventFilter(self, obj, event):  # type: ignore[override]
            if event.type() == show and _is_widget(obj) and is_colour_root(obj):
                room, colour = _current()
                if stamp(obj) != room:
                    apply_colour(obj, room, colour)
            return False

    filt = _ColourOnShow(app)
    app.installEventFilter(filt)
    setattr(app, _FILTER, filt)
