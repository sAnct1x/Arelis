"""Hands session telemetry. Local log + jsonl. No frames, no tokens."""

from __future__ import annotations

from pathlib import Path

from arelis.spatial import hands_log as tel


def test_pytest_is_a_no_op_until_configure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_hands_log.py")
    tel.configure(None)
    tel.emit("session_start", url="https://should-not-write.example/", frame="pixels")
    assert not (tmp_path / "hands.log").exists()


def test_configure_writes_log_and_jsonl_without_secrets(tmp_path: Path) -> None:
    tel.configure(tmp_path)
    try:
        tel.emit(
            "click",
            who="Right",
            x=0.51,
            token="sekrit",
            url="https://hidden.example/still.jpg",
            frame="raw-rgb",
        )
        text = (tmp_path / "hands.log").read_text(encoding="utf-8")
        rows = (tmp_path / "hands.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert "click" in text
        assert "who=Right" in text
        assert "hidden.example" not in text
        assert "sekrit" not in text
        assert "raw-rgb" not in text
        assert len(rows) == 1
        rec = __import__("json").loads(rows[0])
        assert rec["event"] == "click"
        assert rec["who"] == "Right"
        assert rec["token"] == "-"
        assert rec["url"] == "-"
        assert rec["frame"] == "-"
    finally:
        tel.configure(None)
