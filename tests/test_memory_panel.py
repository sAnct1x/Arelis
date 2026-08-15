"""Settings Memory tab: active facts list + forget."""

from __future__ import annotations

from arelis.ui.panels.memory import ActiveFactsPanel
from arelis.ui.settings_dialog import SettingsDialog


def test_active_facts_empty_state(qt_app) -> None:
    panel = ActiveFactsPanel()
    panel.show()
    assert panel.empty_label.isVisible()
    assert not panel.active_list.isVisible()
    assert not panel.forget_btn.isEnabled()


def test_active_facts_reveal_list(qt_app) -> None:
    panel = ActiveFactsPanel()
    panel.show()
    panel.set_facts([{"id": 2, "text": "User builds an interferometer"}])
    assert panel.active_list.isVisible()
    assert panel.forget_btn.isEnabled()
    assert panel.active_list.count() == 1
    assert "active facts (1)" in panel.active_label.text()
    panel.set_facts([])
    assert not panel.active_list.isVisible()
    assert panel.empty_label.isVisible()
    assert not panel.forget_btn.isEnabled()


def test_active_facts_filter(qt_app) -> None:
    panel = ActiveFactsPanel()
    panel.set_facts(
        [
            {"id": 1, "text": "User climbs"},
            {"id": 2, "text": "Prefers Fahrenheit"},
        ]
    )
    panel.search.setText("fahr")
    assert panel.active_list.count() == 1
    assert panel.active_list.item(0).text() == "Prefers Fahrenheit"


def test_active_facts_panel_can_forget(qt_app) -> None:
    panel = ActiveFactsPanel()
    seen: list[tuple[object, str]] = []
    panel.fact_decided.connect(lambda ids, status: seen.append((ids, status)))
    panel.set_facts([{"id": 9, "text": "User climbs"}])
    panel.active_list.setCurrentRow(0)
    panel.forget_btn.click()
    assert seen == [([9], "rejected")]


def test_settings_dialog_hosts_memory_tab(qt_app) -> None:
    dlg = SettingsDialog(
        {"voice": {}, "presence": {}, "tools": {}},
        active_facts=[{"id": 3, "text": "Discord is sAnct1x"}],
    )
    assert dlg.memory.active_list.count() == 1
    assert dlg.memory.forget_btn.objectName() == "FactForget"
    seen: list[tuple[object, str]] = []
    dlg.fact_decided.connect(lambda ids, status: seen.append((ids, status)))
    dlg.memory.active_list.setCurrentRow(0)
    dlg.memory.forget_btn.click()
    assert seen == [([3], "rejected")]
    dlg.set_active_facts([])
    assert dlg.memory.active_list.count() == 0
