"""History panel: empty pending queue stays collapsed (UI polish Pass A)."""

from __future__ import annotations

from PySide6.QtCore import Qt

from arelis.ui.panels.history import HistoryPanel, _display_session_title, _format_when
from arelis.ui.panels.memory import ActiveFactsPanel


def test_empty_pending_queue_hidden(qt_app) -> None:
    panel = HistoryPanel()
    assert not panel.facts_list.isVisibleTo(panel)
    assert not panel.fact_actions.isVisibleTo(panel)


def test_pending_facts_reveal_queue(qt_app) -> None:
    panel = HistoryPanel()
    panel.show()
    panel.set_pending_facts([{"id": 1, "text": "Sam prefers dark mode"}])
    assert panel.facts_list.isVisible()
    assert panel.fact_actions.isVisible()
    assert panel.facts_list.count() == 1

    panel.set_pending_facts([])
    assert not panel.facts_list.isVisible()
    assert not panel.fact_actions.isVisible()


def test_history_scrubs_attachment_boilerplate_titles(qt_app) -> None:
    assert (
        _display_session_title(
            "Attachments for this turn (call the listed tool; do not invent contents):"
        )
        == "Attached files"
    )
    panel = HistoryPanel()
    panel.set_sessions(
        [
            {
                "id": "a",
                "title": (
                    "Attachments for this turn (call the listed tool; "
                    "do not invent contents):"
                ),
                "started_at": "2026-08-11T07:49:00+00:00",
            },
            {
                "id": "b",
                "title": "describe this image to me",
                "started_at": "2026-08-11T07:50:00+00:00",
            },
        ]
    )
    assert panel.list.count() == 2
    assert panel.list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    texts = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert not any(t.startswith("Attachments for this turn") for t in texts)
    assert any(t.startswith("describe this image to me") for t in texts)


def test_missing_session_date_copy() -> None:
    assert _format_when("") == "no date"


def test_fact_buttons_have_object_names(qt_app) -> None:
    history = HistoryPanel()
    memory = ActiveFactsPanel()
    assert history.approve_btn.objectName() == "FactApprove"
    assert history.reject_btn.objectName() == "FactReject"
    assert memory.forget_btn.objectName() == "FactForget"

