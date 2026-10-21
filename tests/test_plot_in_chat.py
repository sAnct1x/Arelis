"""A generated plot has to show up in the transcript, not only as an open chip."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage, QTextCursor, QTextDocument

from arelis.core.events import Event, EventType
from arelis.ui.event_host import dispatch_event
from tests.test_plot_charts import _tool


def _chart_formats(doc):
    found = []
    cursor = QTextCursor(doc)
    count = doc.characterCount()
    for pos in range(max(0, count - 1)):
        cursor.setPosition(pos)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if cursor.selectedText() != "\ufffc":
            continue
        fmt = cursor.charFormat()
        if not fmt.isImageFormat():
            continue
        image = fmt.toImageFormat()
        if image.name().startswith("arelis-chart:"):
            found.append(image)
    return found


def _loaded(view, fmt) -> QImage:
    url = QUrl(fmt.name())
    res = view.document().resource(QTextDocument.ResourceType.ImageResource, url)
    if res is None:
        res = view.loadResource(
            int(QTextDocument.ResourceType.ImageResource.value),
            url,
        )
    return res.toImage() if hasattr(res, "toImage") else res


async def test_plot_file_ready_paints_the_png_in_chat(
    tmp_path: Path, arelis_window, qt_app, monkeypatch
) -> None:
    """FILE_READY for a plot has to put the PNG in the transcript.

    The bubble is open on purpose. A picture appended into that bubble is
    wiped when the answer is finalized, so the image has to wait and land
    after the reply. One subplot panel is still refused here, with the same
    message the old standalone check used.
    """
    tool, _drop = _tool(tmp_path, monkeypatch)
    refused = await tool.run(
        action="subplots", panels="histogram", ys="1,2,3", out="nope.png"
    )
    assert not refused.ok
    assert "at least two" in refused.output.lower()

    png = tmp_path / "fake-plot.png"
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(png))

    window = arelis_window()
    window.chat.begin_assistant()
    window.chat.append_delta("working")
    dispatch_event(
        window,
        Event(
            EventType.FILE_READY,
            {
                "abs_path": str(png.resolve()),
                "title": "fake-plot.png",
                "kind": "plot",
                "source": "plot",
                "show_card": True,
                "open": False,
            },
        ),
    )
    window.chat.finish_assistant("Here is the chart.")
    qt_app.processEvents()

    charts = _chart_formats(window.chat.view.document())
    assert len(charts) == 1
    loaded = _loaded(window.chat.view, charts[0])
    assert loaded is not None and not loaded.isNull()
    assert loaded.width() == 8 and loaded.height() == 8

    # A full-size chart in a narrow window used to paint at file size and
    # get clipped on the right. Logical width follows the bubble; pixels
    # and aspect stay.
    wide = tmp_path / "wide-plot.png"
    wide_image = QImage(1200, 600, QImage.Format.Format_ARGB32)
    wide_image.fill(0xFF993366)
    assert wide_image.save(str(wide))
    window.resize(360, 800)
    window.show()
    qt_app.processEvents()
    dispatch_event(
        window,
        Event(
            EventType.FILE_READY,
            {
                "abs_path": str(wide.resolve()),
                "title": "wide-plot.png",
                "kind": "plot",
                "source": "plot",
                "show_card": True,
                "open": False,
            },
        ),
    )
    qt_app.processEvents()
    view = window.chat.view
    limit = view.formula_width()
    assert limit > 1
    charts = _chart_formats(view.document())
    assert len(charts) == 2
    wide_loaded = _loaded(view, charts[1])
    ratio = wide_loaded.devicePixelRatio() or 1.0
    logical_w = wide_loaded.width() / ratio
    logical_h = wide_loaded.height() / ratio
    assert logical_w <= limit + 0.51
    assert abs((logical_w / logical_h) - 2.0) < 0.02
    assert wide_loaded.width() == 1200 and wide_loaded.height() == 600
    assert view.document().idealWidth() <= view.viewport().width() + 4
