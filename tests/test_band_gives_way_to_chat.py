"""A narrow window: her band shrinks first so the chat column stays readable."""

from __future__ import annotations

from PySide6.QtCore import QRect

from arelis.ui.persona_stage import BAND_FIT_MIN, CHAT_MIN, persona_region


def test_band_shrinks_before_the_chat_column() -> None:
    # Babbage's 1100x800 Night window left a 461 px stage; the 300 px band left the chat about 50 px.
    stage = QRect(0, 0, 461, 584)
    band = persona_region(stage, mode="band")
    assert band.width() >= BAND_FIT_MIN
    assert stage.width() - band.width() >= min(CHAT_MIN, stage.width() - BAND_FIT_MIN)
    assert band.right() == stage.right() and band.height() == stage.height()


def test_band_keeps_its_share_when_there_is_room() -> None:
    assert persona_region(QRect(0, 0, 1916, 1214), mode="band").width() == 536
