"""Phase 6.8: Settings can pick Chat / Research / Vision after the wizard."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from arelis.ui.settings_dialog import SettingsDialog
from arelis.ui.settings_host import apply_settings


def _dialog_config(**models: str) -> dict:
    return {
        "voice": {},
        "presence": {},
        "models": {
            "fast": models.get("fast", "qwen3.5:9b"),
            "research": models.get("research", "qwen3.5:9b"),
            "vision": models.get("vision", "qwen2.5vl:3b"),
        },
        "workspace": {
            "named_roots": [{"name": "arelis", "path": str(Path.cwd()), "read_only": False}]
        },
        "tools": {"sms": {"inbound": {"ingest": {}}}},
    }


def _tags() -> list[str]:
    return ["qwen3.5:9b", "llama3:8b", "qwen2.5vl:3b"]


def test_model_picker_shows_three_roles(qt_app) -> None:
    dlg = SettingsDialog(_dialog_config(), list_models=_tags)
    try:
        assert dlg.fast_model.accessibleName() == "Chat"
        assert dlg.research_model.accessibleName() == "Research"
        assert dlg.vision_model.accessibleName() == "Vision fallback"
        labels = []
        form = dlg.fast_model.parent().layout()
        for row in range(form.rowCount()):
            item = form.itemAt(row, form.ItemRole.LabelRole)
            if item is not None and item.widget() is not None:
                labels.append(item.widget().text())
        assert "Chat" in labels
        assert "Research" in labels
        assert "Vision fallback" in labels
        assert dlg.fast_model.currentData() == "qwen3.5:9b"
        assert dlg.research_model.currentData() == "qwen3.5:9b"
        assert dlg.vision_model.currentData() == "qwen2.5vl:3b"
    finally:
        dlg.close()


def test_model_picker_applied_payload_contains_models(qt_app) -> None:
    dlg = SettingsDialog(_dialog_config(), list_models=_tags)
    try:
        idx = dlg.fast_model.findData("llama3:8b")
        assert idx >= 0
        dlg.fast_model.setCurrentIndex(idx)
        values = dlg.values()
        assert "models" in values
        assert values["models"]["fast"] == "llama3:8b"
        assert values["models"]["research"] == "qwen3.5:9b"
        assert values["models"]["vision"] == "qwen2.5vl:3b"
    finally:
        dlg.close()


def test_model_picker_payload_mutant_drops_models(qt_app) -> None:
    """Mutant: dropping models from the applied payload must fail."""
    dlg = SettingsDialog(_dialog_config(), list_models=_tags)
    try:
        values = dlg.values()
        assert "models" in values
        assert set(values["models"]) >= {"fast", "research", "vision"}
        for role in ("fast", "research", "vision"):
            assert values["models"][role], role
    finally:
        dlg.close()


def test_model_picker_keeps_configured_tag_when_not_installed(qt_app) -> None:
    dlg = SettingsDialog(
        _dialog_config(fast="custom:local"),
        list_models=lambda: ["llama3:8b"],
    )
    try:
        tags = [dlg.fast_model.itemData(i) for i in range(dlg.fast_model.count())]
        assert "custom:local" in tags
        assert "llama3:8b" in tags
        assert dlg.fast_model.currentData() == "custom:local"
    finally:
        dlg.close()


def test_model_picker_ollama_down_shows_configured(qt_app) -> None:
    def _down() -> list[str]:
        raise OSError("ollama down")

    dlg = SettingsDialog(_dialog_config(), list_models=_down)
    try:
        assert "Ollama not reachable" in dlg._models_note.text()
        assert dlg.fast_model.currentData() == "qwen3.5:9b"
        assert dlg.vision_model.currentData() == "qwen2.5vl:3b"
    finally:
        dlg.close()


def test_apply_settings_writes_models_and_router(monkeypatch) -> None:
    writes: list[dict] = []
    monkeypatch.setattr(
        "arelis.ui.settings_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    monkeypatch.setattr(
        "arelis.ui.voice_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    router = SimpleNamespace(
        models={
            "fast": "qwen3.5:9b",
            "research": "qwen3.5:9b",
            "vision": "qwen2.5vl:3b",
        }
    )
    window = SimpleNamespace(
        config={
            "voice": {"enabled": True, "stt": {"enabled": True}, "tts": {"enabled": True}},
            "models": dict(router.models),
        },
        router=router,
        voice=None,
        voice_controller=None,
        speech_player=None,
        thinking=SimpleNamespace(append=lambda *_a, **_k: None),
        _schedule_readiness_probe=lambda: None,
    )
    apply_settings(
        window,
        {
            "voice": {
                "input_device": "",
                "output_device": "",
                "output_volume": 1.0,
            },
            "models": {
                "fast": "llama3:8b",
                "research": "qwen3.5:9b",
                "vision": "qwen2.5vl:3b",
            },
        },
    )
    assert window.config["models"]["fast"] == "llama3:8b"
    assert router.models["fast"] == "llama3:8b"
    assert any("models" in item for item in writes)


def test_composer_send_stop_have_accessible_names(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        assert stage.send_btn.accessibleName().strip()
        assert stage.stop_btn.accessibleName().strip()
    finally:
        stage.deleteLater()
