"""Phase 6.4: Listen / Speak cannot silently miss the running voice service.

VoiceService has no reconfigure. A toggle that writes config when wanted !=
live, with no live apply and no restart prompt, is the defect.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from arelis.ui.voice_host import (
    VOICE_BLOCK,
    VOICE_KEEP,
    VOICE_PERSIST,
    commit_voice_directions,
    voice_restart_notices,
    voice_settings_plan,
)


def _plan(**kwargs):
    return voice_settings_plan(**kwargs)


def test_matching_directions_stay_put() -> None:
    plan = _plan(
        listen_wanted=True,
        listen_live=True,
        speak_wanted=False,
        speak_live=False,
    )
    assert plan.action == VOICE_KEEP
    assert plan.apply_live is False
    assert plan.persist is False
    assert plan.message == ""


def test_mismatch_without_confirm_is_a_block() -> None:
    plan = _plan(
        listen_wanted=False,
        listen_live=True,
        speak_wanted=True,
        speak_live=True,
    )
    assert plan.action == VOICE_BLOCK
    assert plan.apply_live is False
    assert plan.persist is False
    assert plan.message
    assert "Listen" in plan.message
    assert "restart" in plan.message.lower()


def test_speak_on_from_dark_is_a_block() -> None:
    plan = _plan(
        listen_wanted=True,
        listen_live=True,
        speak_wanted=True,
        speak_live=False,
    )
    assert plan.action == VOICE_BLOCK
    assert not plan.persist
    assert not plan.apply_live
    assert "Speak" in plan.message


def test_confirmed_mismatch_persists_only() -> None:
    plan = _plan(
        listen_wanted=False,
        listen_live=True,
        speak_wanted=True,
        speak_live=True,
        restart_confirmed=True,
    )
    assert plan.action == VOICE_PERSIST
    assert plan.persist is True
    assert plan.apply_live is False
    assert plan.message


def test_already_saved_pending_restart_does_not_nag() -> None:
    plan = _plan(
        listen_wanted=False,
        listen_live=True,
        speak_wanted=True,
        speak_live=True,
        listen_saved=False,
        speak_saved=True,
    )
    assert plan.action == VOICE_KEEP
    assert plan.persist is False
    assert plan.apply_live is False


def test_revert_to_live_persists_without_a_prompt() -> None:
    plan = _plan(
        listen_wanted=True,
        listen_live=True,
        speak_wanted=True,
        speak_live=True,
        listen_saved=False,
        speak_saved=True,
    )
    assert plan.action == VOICE_KEEP
    assert plan.persist is True
    assert plan.apply_live is False
    assert plan.message == ""


def test_mismatch_is_never_a_silent_config_write() -> None:
    """Mutant: toggle writes config, does not apply, does not prompt."""
    cases = (
        (False, True, True, True),
        (True, False, True, True),
        (True, True, False, True),
        (True, True, True, False),
        (False, True, False, True),
    )
    for listen_wanted, listen_live, speak_wanted, speak_live in cases:
        plan = _plan(
            listen_wanted=listen_wanted,
            listen_live=listen_live,
            speak_wanted=speak_wanted,
            speak_live=speak_live,
            restart_confirmed=False,
        )
        silent = plan.persist and not plan.apply_live and not plan.message
        assert not silent, (listen_wanted, listen_live, speak_wanted, speak_live, plan)
        assert plan.action == VOICE_BLOCK
        assert not plan.persist
        assert not plan.apply_live
        assert plan.message


def test_restart_notices_still_name_the_direction() -> None:
    lines = voice_restart_notices(
        listen_wanted=False,
        listen_live=True,
        speak_wanted=True,
        speak_live=False,
    )
    assert len(lines) == 2
    assert any("Listen" in line and "off" in line for line in lines)
    assert any("Speak" in line and "on" in line for line in lines)


def _voice_window(*, listen_live: bool = True, speak_live: bool = True):
    said: list[str] = []
    return SimpleNamespace(
        config={
            "voice": {
                "enabled": True,
                "stt": {"enabled": True},
                "tts": {"enabled": True},
            }
        },
        voice=SimpleNamespace(
            enabled=True,
            stt_enabled=listen_live,
            tts_enabled=speak_live,
        ),
        chat=SimpleNamespace(add_system=said.append),
        said=said,
    )


def test_commit_without_confirm_does_not_write_or_apply(monkeypatch) -> None:
    writes: list[dict] = []
    monkeypatch.setattr(
        "arelis.ui.voice_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    window = _voice_window()
    plan = commit_voice_directions(
        window,
        {"enabled": True, "stt": {"enabled": False}, "tts": {"enabled": True}},
    )
    assert plan.action == VOICE_BLOCK
    assert writes == []
    assert window.config["voice"]["stt"]["enabled"] is True
    assert window.voice.stt_enabled is True
    assert window.said == []


def test_commit_with_confirm_persists_and_leaves_live_flags(monkeypatch) -> None:
    writes: list[dict] = []
    monkeypatch.setattr(
        "arelis.ui.voice_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    window = _voice_window()
    plan = commit_voice_directions(
        window,
        {"enabled": True, "stt": {"enabled": False}, "tts": {"enabled": True}},
        confirm_restart=lambda _plan: True,
    )
    assert plan.action == VOICE_PERSIST
    assert plan.apply_live is False
    assert window.config["voice"]["stt"]["enabled"] is False
    assert window.voice.stt_enabled is True
    assert writes
    assert any("Restart" in line and "Listen" in line for line in window.said)


def test_commit_honors_dialog_confirm_flag(monkeypatch) -> None:
    writes: list[dict] = []
    monkeypatch.setattr(
        "arelis.ui.voice_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    asked: list[object] = []
    window = _voice_window()
    plan = commit_voice_directions(
        window,
        {
            "enabled": True,
            "stt": {"enabled": False},
            "tts": {"enabled": True},
            "_voice_restart_confirmed": True,
        },
        confirm_restart=lambda p: asked.append(p) or True,
    )
    assert plan.action == VOICE_PERSIST
    assert asked == []
    assert window.config["voice"]["stt"]["enabled"] is False
    assert window.voice.stt_enabled is True


def test_apply_settings_cancel_is_not_a_silent_write(monkeypatch) -> None:
    from arelis.ui.settings_host import apply_settings

    writes: list[dict] = []
    monkeypatch.setattr(
        "arelis.ui.settings_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    monkeypatch.setattr(
        "arelis.ui.voice_host.merge_local_config",
        lambda data, **_k: writes.append(data),
    )
    monkeypatch.setattr("arelis.ui.dialog.confirm", lambda *_a, **_k: False)
    window = _voice_window()
    window.voice_controller = None
    window.speech_player = None
    window.thinking = SimpleNamespace(append=lambda *_a, **_k: None)
    apply_settings(
        window,
        {
            "voice": {
                "enabled": True,
                "input_device": "",
                "output_device": "",
                "output_volume": 1.0,
                "stt": {"enabled": False},
                "tts": {"enabled": True},
            }
        },
    )
    assert window.config["voice"]["stt"]["enabled"] is True
    assert window.voice.stt_enabled is True
    assert not any("stt" in (item.get("voice") or {}) for item in writes)


def _dialog_config() -> dict:
    return {
        "voice": {},
        "presence": {},
        "workspace": {
            "named_roots": [
                {"name": "arelis", "path": str(Path.cwd()), "read_only": False}
            ]
        },
        "tools": {"sms": {"inbound": {"ingest": {}}}},
    }


def test_settings_toggle_without_confirm_reverts(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    asked: list[str] = []

    def deny(plan) -> bool:
        asked.append(plan.message)
        return False

    dlg = SettingsDialog(
        _dialog_config(),
        listen_live=True,
        speak_live=True,
        confirm_voice_restart=deny,
        list_models=lambda: [],
    )
    try:
        dlg.stt_enabled.setChecked(False)
        assert dlg.stt_enabled.isChecked() is True
        assert dlg._voice_restart_ok is False
        assert asked
        assert "Listen" in asked[0]
    finally:
        dlg.close()


def test_settings_toggle_confirm_keeps_the_change(qt_app) -> None:
    from arelis.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        _dialog_config(),
        listen_live=True,
        speak_live=True,
        confirm_voice_restart=lambda _plan: True,
        list_models=lambda: [],
    )
    try:
        dlg.stt_enabled.setChecked(False)
        assert dlg.stt_enabled.isChecked() is False
        assert dlg._voice_restart_ok is True
        values = dlg.values()["voice"]
        assert values["stt"]["enabled"] is False
        assert values["_voice_restart_confirmed"] is True
    finally:
        dlg.close()
