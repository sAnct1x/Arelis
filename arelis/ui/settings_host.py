"""Settings apply and chrome prefs. Window methods stay as delegates."""

from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtCore import Qt

from arelis.config import deep_merge, merge_local_config
from arelis.paths import outputs_dir
from arelis.spatial.scene import clamp_reach
from arelis.ui.layout_store import clamp_away_rest_min, save_ui_prefs
from arelis.ui.settings_dialog import SettingsDialog
from arelis.ui.voice_host import voice_restart_notices
from arelis.ui.window_resize import enable_win32_resize_frame


def apply_settings(window, values: dict[str, Any]) -> None:
    voice_patch = values.get("voice") or {}
    presence_patch = values.get("presence") or {}
    ui_prefs = values.get("ui_prefs") or {}

    deep_merge(window.config.setdefault("voice", {}), {
        k: v for k, v in voice_patch.items() if k not in {"stt", "tts"}
    })
    if "stt" in voice_patch:
        stt_cfg = window.config.setdefault("voice", {}).setdefault("stt", {})
        deep_merge(stt_cfg, voice_patch["stt"])
    if "tts" in voice_patch:
        tts_cfg = window.config.setdefault("voice", {}).setdefault("tts", {})
        deep_merge(tts_cfg, voice_patch["tts"])
    if presence_patch:
        deep_merge(window.config.setdefault("presence", {}), presence_patch)
        if "close_to_tray" in presence_patch:
            window._close_to_tray = bool(presence_patch["close_to_tray"])

    merge_local_config(
        {
            "voice": {
                "enabled": bool(voice_patch.get("enabled", True)),
                "input_device": str(voice_patch.get("input_device") or ""),
                "output_device": str(voice_patch.get("output_device") or ""),
                "output_volume": float(voice_patch.get("output_volume", 1.0)),
                "stt": {"enabled": bool((voice_patch.get("stt") or {}).get("enabled", True))},
                "tts": {"enabled": bool((voice_patch.get("tts") or {}).get("enabled", True))},
            },
            "presence": {
                "close_to_tray": bool(presence_patch.get("close_to_tray", True)),
            },
        }
    )

    ui_patch = values.get("ui") or {}
    if "scale" in ui_patch:
        from arelis.ui.scale import clamp_scale, scale_from_config

        new_scale = clamp_scale(ui_patch.get("scale"))
        old_scale = scale_from_config(window.config)
        window.config.setdefault("ui", {})["scale"] = new_scale
        merge_local_config({"ui": {"scale": new_scale}})
        if abs(new_scale - old_scale) > 0.001:
            window.thinking.append(
                "Restart Arelis to apply interface scale.",
                kind="status",
            )
    notify_patch = ui_patch.get("notifications") or {}
    if notify_patch:
        deep_merge(
            window.config.setdefault("ui", {}).setdefault("notifications", {}),
            notify_patch,
        )
        merge_local_config({"ui": {"notifications": notify_patch}})
        window.notify_center.set_config(window.config)
        from arelis.ui.notify_host import sync_notify_surface

        sync_notify_surface(window)

    agent_patch = values.get("agent") or {}
    if agent_patch:
        deep_merge(window.config.setdefault("agent", {}), agent_patch)
        merge_local_config({"agent": dict(agent_patch)})
        window._schedule_readiness_probe()

    workspace_patch = values.get("workspace") or {}
    if "roots" in workspace_patch:
        from arelis.ui.workspace_host import apply_workspace_roots

        apply_workspace_roots(window, list(workspace_patch.get("roots") or []))

    if window.voice_controller is not None and "input_device" in voice_patch:
        window.voice_controller.set_input_device(str(voice_patch.get("input_device") or ""))
    if window.speech_player is not None:
        if "output_device" in voice_patch:
            window.speech_player.set_output_device(str(voice_patch.get("output_device") or ""))
        if "output_volume" in voice_patch:
            try:
                window.speech_player.set_volume(float(voice_patch["output_volume"]))
            except (TypeError, ValueError):
                pass

    if "always_on_top" in ui_prefs:
        apply_always_on_top(window, bool(ui_prefs["always_on_top"]))
    if "chat_font_scale" in ui_prefs:
        apply_chat_font_scale(window, float(ui_prefs["chat_font_scale"]))
    if "away_rest" in ui_prefs or "away_rest_min" in ui_prefs:
        if "away_rest" in ui_prefs:
            window._away_rest = bool(ui_prefs["away_rest"])
        if "away_rest_min" in ui_prefs:
            window._away_rest_min = clamp_away_rest_min(ui_prefs["away_rest_min"])
        save_ui_prefs(
            away_rest=window._away_rest,
            away_rest_min=window._away_rest_min,
        )
        if not window._away_rest and window._away_resting:
            from arelis.ui.idle_host import wake_from_away_rest

            wake_from_away_rest(window)
        else:
            from arelis.ui.idle_host import arm_away_rest_timer

            arm_away_rest_timer(window)

    # Soft-apply listen/speak availability without a full restart when possible.
    master = bool((window.config.get("voice") or {}).get("enabled", True))
    if master and window.voice is None:
        window.thinking.append(
            "Restart Arelis to load voice hardware after enabling Voice.",
            kind="status",
        )
    if window.voice is not None:
        stt_on = bool((window.config.get("voice") or {}).get("stt", {}).get("enabled", True))
        tts_on = bool((window.config.get("voice") or {}).get("tts", {}).get("enabled", True))
        for notice in voice_restart_notices(
            listen_wanted=master and stt_on,
            listen_live=bool(window.voice.stt_enabled),
            speak_wanted=master and tts_on,
            speak_live=bool(window.voice.tts_enabled),
        ):
            window.thinking.append(notice, kind="status")
        if not master or not stt_on:
            if window.voice_controller is not None:
                window.voice_controller.stop_all()
            window.conversation.set_voice_available(False, "Voice listen is off in Settings.")
        elif window.voice_controller is not None:
            window.conversation.set_voice_available(True, "")
            window.voice_controller.resume_wake()
        if not master or not tts_on:
            from arelis.ui.voice_host import stop_speech

            stop_speech(window)


def apply_window_theme(window, theme_id: str, *, persist: bool = True) -> str:
    """Install a room palette and restyle the open window. No restart."""
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QComboBox, QDockWidget, QWidget

    from arelis.ui.dock_surface import apply_dock_surface
    from arelis.ui.glass import GlassFrame, Hairline
    from arelis.ui.theme import (
        PLATE,
        apply_theme,
        polish_combo_popup,
        stylesheet,
    )

    resolved = apply_theme(theme_id)
    window.config.setdefault("ui", {})["theme"] = resolved
    if persist:
        merge_local_config({"ui": {"theme": resolved}})

    css = stylesheet()
    window.setStyleSheet(css)
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(css)

    pal = window.palette()
    pal.setColor(window.backgroundRole(), QColor(*PLATE["seal"]))
    window.setPalette(pal)
    for frame in window.findChildren(GlassFrame):
        frame.update()
    for line in window.findChildren(Hairline):
        line.update()
    for dock in window.findChildren(QDockWidget):
        apply_dock_surface(dock)
    for combo in window.findChildren(QComboBox):
        polish_combo_popup(combo, compact=combo.count() <= 2)

    for child in window.findChildren(QWidget):
        refresh = getattr(child, "refresh_theme_icons", None)
        if callable(refresh):
            refresh()
    conversation = getattr(window, "conversation", None)
    if conversation is not None and hasattr(conversation, "refresh_theme_icons"):
        conversation.refresh_theme_icons()
    chat = getattr(window, "chat", None)
    if chat is not None:
        empty = getattr(chat, "empty", None)
        if empty is not None:
            empty.update()
            orbit = getattr(empty, "orbit", None)
            if orbit is not None:
                orbit.update()
    sync = getattr(window, "_sync_filament_face", None)
    if callable(sync):
        sync()
    window.update()
    return resolved


def toggle_fullscreen(window) -> None:
    if window.isFullScreen():
        window.showNormal()
    else:
        window.showFullScreen()
    window._sync_chrome_state()
    window._apply_round_mask()


def toggle_always_on_top(window, checked: bool) -> None:
    apply_always_on_top(window, checked)


def apply_always_on_top(window, on: bool, *, persist: bool = True) -> None:
    window._always_on_top = bool(on)
    flags = window.windowFlags()
    if window._always_on_top:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    else:
        flags &= ~Qt.WindowType.WindowStaysOnTopHint
    visible = window.isVisible()
    window.setWindowFlags(flags)
    if visible:
        window.show()  # showEvent re-applies WS_THICKFRAME for edge resize
    else:
        enable_win32_resize_frame(window)
    if hasattr(window, "act_always_on_top"):
        window.act_always_on_top.blockSignals(True)
        window.act_always_on_top.setChecked(window._always_on_top)
        window.act_always_on_top.blockSignals(False)
    if persist:
        save_ui_prefs(always_on_top=window._always_on_top)


def nudge_chat_font(window, delta: float) -> None:
    apply_chat_font_scale(window, window._chat_font_scale + delta)


def apply_chat_font_scale(window, scale: float, *, persist: bool = True) -> None:
    window._chat_font_scale = max(0.75, min(1.75, float(scale)))
    window.chat.set_text_scale(window._chat_font_scale)
    body = max(10, min(24, round(14 * window._chat_font_scale)))
    window.conversation.input.setStyleSheet(f"font-size: {body}px;")
    if persist:
        save_ui_prefs(chat_font_scale=window._chat_font_scale)


def on_reach_changed(window, reach: float) -> None:
    apply_world_reach(window, reach)


def apply_world_reach(window, reach: float, *, persist: bool = True) -> None:
    window._world_reach = clamp_reach(reach)
    if hasattr(window, "camera"):
        window.camera.set_reach(window._world_reach)
    if persist:
        save_ui_prefs(world_reach=window._world_reach)


def open_settings(window, tab: str = "") -> None:
    active_facts: list[dict[str, object]] = []
    if window.store is not None:
        active_facts = window.store.list_facts(status="active", limit=50)
    dlg = SettingsDialog(
        window.config,
        always_on_top=window._always_on_top,
        chat_font_scale=window._chat_font_scale,
        away_rest=window._away_rest,
        away_rest_min=window._away_rest_min,
        active_facts=active_facts,
        parent=window,
        on_test_mic=lambda: settings_test_mic(window),
        on_test_speak=lambda: settings_test_speak(window),
        on_reset_layout=window._reset_layout,
        initial_tab=tab,
    )
    dlg.applied.connect(lambda values: apply_settings(window, values))

    def _on_memory_fact(fact_ids: object, status: str) -> None:
        from arelis.ui.history_host import on_fact_decided

        on_fact_decided(window, fact_ids, status)
        if window.store is not None:
            dlg.set_active_facts(window.store.list_facts(status="active", limit=50))

    dlg.fact_decided.connect(_on_memory_fact)
    dlg.exec()


def settings_test_mic(window) -> str:
    if window.voice_controller is not None:
        problem = window.voice_controller.problem()
        if problem:
            return problem
        name = window.voice_controller.device_name() or "microphone"
        return f"Using {name}."
    from arelis.ui.audio import MicRecorder

    voice = window.config.get("voice") or {}
    mic = MicRecorder(
        sample_rate=int((voice.get("stt") or {}).get("sample_rate", 16000)),
        device_hint=str(voice.get("input_device") or ""),
        parent=window,
    )
    problem = mic.problem()
    if problem:
        return problem
    return f"Using {mic.device_name() or 'microphone'}."


def settings_test_speak(window) -> None:
    async def _speak() -> None:
        if window.voice is None or not window.voice.tts_enabled:
            raise RuntimeError("Speech is disabled.")
        out = outputs_dir() / "voice" / "settings_test.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        path = await window.voice.tts.synthesize("Arelis settings test.", out)
        if window.speech_player is None:
            raise RuntimeError("No playback device.")
        window.speech_player.enqueue(path, utterance=0)

    fut = asyncio.run_coroutine_threadsafe(_speak(), window.loop)

    def _done(f) -> None:
        try:
            f.result()
        except Exception as exc:
            window.thinking.append(f"Speak test failed: {exc}", kind="status")

    fut.add_done_callback(_done)


def bind_settings(window) -> None:
    window.title_bar.settings_requested.connect(lambda: open_settings(window))
    window.readiness_strip.settings_requested.connect(
        lambda tab="": open_settings(window, tab)
    )

