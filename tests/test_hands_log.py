"""Hands jsonl. Same contract as Reality: no frames, no secrets."""

from __future__ import annotations

import json
from pathlib import Path

from arelis.spatial import hands_log as tel


def test_pytest_is_a_no_op_until_configure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_hands_log.py")
    tel.configure(None)
    tel.emit("click_hit", hit="chat", url="https://should-not-write.example/")
    assert not (tmp_path / "hands.log").exists()
    assert not (tmp_path / "hands.jsonl").exists()


def test_configure_writes_log_and_jsonl_without_secrets(tmp_path: Path) -> None:
    tel.configure(tmp_path)
    try:
        tel.emit(
            "click_hit",
            hit="chat",
            x=0.42,
            y=0.33,
            url="https://hidden.example/still.jpg",
            token="sekrit",
            frame="rgb-bytes-must-not-land",
            image="/tmp/hand.png",
        )
        tel.emit("click_miss", hit="miss", x=0.10, y=0.90)
        text = (tmp_path / "hands.log").read_text(encoding="utf-8")
        rows = (tmp_path / "hands.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert "click_hit" in text
        assert "hit=chat" in text
        assert "hidden.example" not in text
        assert "sekrit" not in text
        assert "rgb-bytes" not in text
        assert len(rows) == 2
        rec = json.loads(rows[0])
        assert rec["event"] == "click_hit"
        assert rec["hit"] == "chat"
        assert rec["url"] == "-"
        assert rec["token"] == "-"
        assert rec["frame"] == "-"
        assert rec["image"] == "-"
        miss = json.loads(rows[1])
        assert miss["event"] == "click_miss"
    finally:
        tel.configure(None)


def test_sample_does_not_spam(tmp_path: Path) -> None:
    tel.configure(tmp_path)
    try:
        tel.sample("pose", n=1, fps=24.0)
        tel.sample("pose", n=1, fps=25.0)
        rows = (tmp_path / "hands.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 1
        assert json.loads(rows[0])["event"] == "pose"
    finally:
        tel.configure(None)
