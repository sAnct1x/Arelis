"""Reality plate telemetry. Local log + jsonl. No URLs, no tokens."""

from __future__ import annotations

from pathlib import Path

from arelis.physics import telemetry as tel


def test_pytest_is_a_no_op_until_configure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/test_reality_telemetry.py")
    tel.configure(None)
    tel.emit("earth_enter", n=3, url="https://should-not-write.example/")
    assert not (tmp_path / "reality.log").exists()


def test_configure_writes_log_and_jsonl_without_secrets(tmp_path: Path) -> None:
    tel.configure(tmp_path)
    try:
        tel.emit(
            "earth_band",
            band="city",
            lat=39.7817,
            lon=-89.6501,
            url="https://hidden.example/still.jpg",
            token="sekrit",
            cite="OpenSky /api/states/all",
            stream="rtsp://hidden.example/live",
            rtsp="rtsp://hidden.example/live",
            look="https://hidden.example/still.jpg",
        )
        text = (tmp_path / "reality.log").read_text(encoding="utf-8")
        rows = (tmp_path / "reality.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert "earth_band" in text
        assert "band=city" in text
        assert "hidden.example" not in text
        assert "sekrit" not in text
        assert "still.jpg" not in text
        assert len(rows) == 1
        rec = __import__("json").loads(rows[0])
        assert rec["event"] == "earth_band"
        assert rec["lat"] == 39.78
        assert rec["lon"] == -89.65
        assert rec["url"] == "-"
        assert rec["token"] == "-"
        assert rec["cite"] == "-"
        assert rec["stream"] == "-"
        assert rec["rtsp"] == "-"
        assert rec["look"] == "-"
    finally:
        tel.configure(None)
