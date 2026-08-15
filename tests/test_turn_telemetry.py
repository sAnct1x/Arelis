"""Turn latency log: stages and summary line."""

from __future__ import annotations

import json
from pathlib import Path

from arelis.core.turn_telemetry import (
    TurnTimer,
    ensure_turn_log,
    log_span,
    turn_telemetry_enabled,
)


def test_turn_telemetry_defaults_on() -> None:
    assert turn_telemetry_enabled({}) is True
    assert turn_telemetry_enabled({"agent": {}}) is True
    assert turn_telemetry_enabled({"agent": {"turn_telemetry": False}}) is False


def test_turn_timer_writes_stages_and_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.core.turn_telemetry.PROJECT_ROOT",
        tmp_path,
    )
    # Force re-attach against the temp logs dir.
    import arelis.core.turn_telemetry as mod

    mod._attached = False
    mod.log.handlers.clear()

    timer = TurnTimer(
        source="chat",
        role="fast",
        speak=False,
        user_chars=12,
        enabled=True,
        session_id="sessdeadbeef",
        user_text="open x.com",
    )
    timer.mark("summarize", ms=1200, dropped=3)
    timer.summarize_ms = 1200
    timer.note_first_delta()
    timer.model_ms = 2500
    timer.rounds = 1
    blurb = timer.finish("ok")

    log_path = tmp_path / "logs" / "turns.log"
    assert log_path.is_file()
    text = log_path.read_text(encoding="utf-8")
    assert "start" in text
    assert "session=sessdeadbeef" in text
    assert f"id={timer.id}" in text
    assert "summarize" in text
    assert "ttft" in text
    assert "done" in text
    jsonl = tmp_path / "logs" / "turns.jsonl"
    assert jsonl.is_file()
    assert "open x.com" in jsonl.read_text(encoding="utf-8")
    assert "total=" in blurb
    assert "model=" in blurb
    assert "summarize=" in blurb


def test_gate_firings_reach_the_record_that_outlives_the_text_log(
    tmp_path: Path, monkeypatch
) -> None:
    """Which gates fired has to be queryable, not just greppable.

    An audit of the gate layer had to re-derive turn ids out of turns.log to ask
    whether a gate still fires, and that file retains a fraction of the turns
    turns.jsonl does — so the answer came back from 127 real turns instead of 484.
    """
    monkeypatch.setattr("arelis.core.turn_telemetry.PROJECT_ROOT", tmp_path)
    import arelis.core.turn_telemetry as mod

    mod._attached = False
    mod.log.handlers.clear()

    timer = TurnTimer(
        source="chat",
        role="fast",
        speak=False,
        user_chars=9,
        enabled=True,
        session_id="sessgate001",
        user_text="text my wife",
    )
    timer.mark("exactness", gate="sms_force", action="preinject")
    timer.mark("verify", gate="refuse", kinds="web")
    timer.mark("round", n=1, ms=10)
    timer.finish("ok")

    record = json.loads(
        (tmp_path / "logs" / "turns.jsonl").read_text(encoding="utf-8").strip()
    )
    assert record["gates"] == [
        {"gate": "sms_force", "at": "exactness", "action": "preinject"},
        {"gate": "refuse", "at": "verify"},
    ]
    # A round is not a gate, so it must not turn up as one.
    assert all(entry["gate"] != "round" for entry in record["gates"])


def test_a_turn_with_no_gate_says_so_rather_than_omitting_it(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("arelis.core.turn_telemetry.PROJECT_ROOT", tmp_path)
    import arelis.core.turn_telemetry as mod

    mod._attached = False
    mod.log.handlers.clear()

    timer = TurnTimer(
        source="chat", role="fast", speak=False, user_chars=2, enabled=True
    )
    timer.finish("ok")
    record = json.loads(
        (tmp_path / "logs" / "turns.jsonl").read_text(encoding="utf-8").strip()
    )
    assert record["gates"] == []


def test_disabled_timer_is_silent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.turn_telemetry.PROJECT_ROOT", tmp_path)
    import arelis.core.turn_telemetry as mod

    mod._attached = False
    mod.log.handlers.clear()

    timer = TurnTimer(
        source="voice",
        role="fast",
        speak=True,
        user_chars=4,
        enabled=False,
    )
    timer.mark("round", n=1, ms=10)
    assert timer.finish("ok").startswith("timing")
    assert not (tmp_path / "logs" / "turns.log").exists()


def test_ollama_metrics_logged_and_summed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.turn_telemetry.PROJECT_ROOT", tmp_path)
    import arelis.core.turn_telemetry as mod

    mod._attached = False
    mod.log.handlers.clear()

    timer = TurnTimer(
        source="chat",
        role="fast",
        speak=False,
        user_chars=4,
        enabled=True,
    )
    # Ollama durations are nanoseconds.
    timer.note_ollama_metrics(
        {
            "prompt_eval_count": 1200,
            "prompt_eval_duration": 1_500_000_000,
            "eval_count": 40,
            "eval_duration": 800_000_000,
        },
        round_n=1,
    )
    blurb = timer.finish("ok")
    text = (tmp_path / "logs" / "turns.log").read_text(encoding="utf-8")
    assert "ollama_metrics" in text
    assert "prompt_eval_ms=1500" in text
    assert "eval_ms=800" in text
    assert "round=1" in text
    assert "model_prefill_ms=1500" in text
    assert "model_decode_ms=800" in text
    assert "prefill=" in blurb
    assert "decode=" in blurb


def test_log_span_writes_stt_line(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.core.turn_telemetry.PROJECT_ROOT", tmp_path)
    import arelis.core.turn_telemetry as mod

    mod._attached = False
    mod.log.handlers.clear()
    ensure_turn_log(tmp_path / "logs")
    log_span("stt", ms=340, chars=18, deliver="turn")
    text = (tmp_path / "logs" / "turns.log").read_text(encoding="utf-8")
    assert "stt" in text
    assert "ms=340" in text
    assert "span=" in text
