"""Settings → Memory lists dates and can edit or forget a fact."""

from __future__ import annotations

from pathlib import Path

from arelis.memory import MemoryStore
from arelis.ui.panels.memory import ActiveFactsPanel


def test_settings_memory_can_edit_and_forget_a_fact(qt_app, tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    try:
        fact_id = store.add_fact(
            "favorite fruit is mango",
            source="explicit",
            status="active",
        )
        assert fact_id is not None
        store._conn.execute(
            "UPDATE facts SET created_at = ?, updated_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00", "2026-01-02T00:00:00", fact_id),
        )
        store._conn.commit()

        panel = ActiveFactsPanel()
        panel.set_facts(store.list_facts(status="active"))
        assert panel.active_list.count() == 1
        shown = panel.active_list.item(0).text()
        assert "favorite fruit is mango" in shown
        assert "created 2026-01-01" in shown
        assert "updated 2026-01-02" in shown

        def _on_edit(fid: int, text: str) -> None:
            store.edit_fact(fid, text)
            panel.set_facts(store.list_facts(status="active"))

        def _on_forget(ids: object, status: str) -> None:
            for fid in ids:
                store.set_fact_status(int(fid), status)
            panel.set_facts(store.list_facts(status="active"))

        panel.fact_edited.connect(_on_edit)
        panel.fact_decided.connect(_on_forget)
        panel._ask_text = lambda *args, **kwargs: "favorite fruit is pineapple"
        panel.active_list.setCurrentRow(0)
        panel.edit_btn.click()

        rows = store.list_facts(status="active")
        assert len(rows) == 1
        assert rows[0]["id"] == fact_id
        assert rows[0]["text"] == "favorite fruit is pineapple"
        assert rows[0]["created_at"] == "2026-01-01T00:00:00"
        assert str(rows[0]["updated_at"]) > "2026-01-02T00:00:00"
        shown = panel.active_list.item(0).text()
        assert "favorite fruit is pineapple" in shown
        assert "created 2026-01-01" in shown

        panel._ask_text = lambda *args, **kwargs: ""
        panel.active_list.setCurrentRow(0)
        panel.edit_btn.click()
        assert store.list_facts(status="active")[0]["text"] == "favorite fruit is pineapple"

        panel.active_list.setCurrentRow(0)
        panel.forget_btn.click()
        assert store.list_facts(status="active") == []
        assert panel.active_list.count() == 0
    finally:
        store.close()
