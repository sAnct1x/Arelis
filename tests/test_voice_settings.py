"""Phase 6.4: Listen / Speak cannot silently miss the running voice service.

VoiceService has no reconfigure. A toggle that writes config when wanted !=
live, with no live apply and no restart prompt, is the defect.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from arelis.ui.voice_host import (
    VOICE_BLOCK,
    VOICE_PERSIST,
    commit_voice_directions,
    voice_settings_plan,
)


def _plan(**kwargs):
    return voice_settings_plan(**kwargs)


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


