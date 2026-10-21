"""The bench attaches a picture the way the chat paperclip does.

A path inside the prompt is text. The attach button stages the file and
publishes those dicts on USER_MESSAGE, which is what the vision tool reads
before the pixels go to the model.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from uuid import UUID

from arelis.attachments import (
    attach_paths,
    matrix_turn_payload,
    staged_for_turn,
)
from arelis.core.events import EventType
from arelis.eval.conversation import ConversationTurn
from arelis.ui.panels.conversation import ConversationStage
from arelis.ui.window_turn import WindowTurn

_ASK = "what color is the circle"
_BARE = "What is 12.5% of 640?"
_PNG_NAME = "circle.png"
# 1x1 red PNG. A fake header makes Qt print a libpng error while building the tile.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _Bus:
    def __init__(self) -> None:
        self.events: list = []

    def publish(self, event: object) -> object:
        self.events.append(event)

        async def _done() -> None:
            return None

        return _done()


class _Roots:
    def grant_external_read(self, source: str) -> None:
        return None


class _Chat:
    def add_user(self, text: str, attachments: list | None = None) -> None:
        return None


class _Window:
    """Enough of the window for WindowTurn._on_submit to publish."""

    _away_resting = False
    _away_timer = None

    def __init__(self) -> None:
        self.bus = _Bus()
        self.loop = object()
        self.workspace_roots = _Roots()
        self.chat = _Chat()

    def _try_physics_verb(self, text: str) -> bool:
        return False

    def _try_tile_speech(self, text: str) -> bool:
        return False

    def _set_busy(self, busy: bool) -> None:
        return None

    def _show_model_loading(self, role: str) -> None:
        return None


def _drop_schedule(coro: object, loop: object) -> None:
    close = getattr(coro, "close", None)
    if callable(close):
        close()


def _capture(window: _Window, text: str, role: str, attachments: list | None) -> dict:
    window.bus.events.clear()
    WindowTurn._on_submit(window, text, role, attachments)
    assert len(window.bus.events) == 1
    event = window.bus.events[0]
    assert event.type == EventType.USER_MESSAGE
    return dict(event.payload)


def _fresh(drops: Path, stage: ConversationStage) -> None:
    stage.attach_bar.clear()
    if drops.exists():
        shutil.rmtree(drops)


def test_driver_attach_matches_attach_button(qt_app, tmp_path: Path, monkeypatch) -> None:
    """Glass and matrix payloads match the paperclip send, not a path in the text."""
    del qt_app
    png = tmp_path / _PNG_NAME
    png.write_bytes(_PNG)
    drops = tmp_path / "drops"
    monkeypatch.setattr("arelis.attachments.DROPS_ROOT", drops)
    monkeypatch.setattr(
        "arelis.attachments.uuid4",
        lambda: UUID("11111111-1111-1111-1111-111111111111"),
    )
    monkeypatch.setattr("arelis.ui.window_turn.sync_idle_mode", lambda window: None)
    monkeypatch.setattr(
        "arelis.ui.window_turn.asyncio.run_coroutine_threadsafe",
        _drop_schedule,
    )

    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import live_matrix_items

    stage = ConversationStage()
    window = _Window()

    bare_turn = ConversationTurn(id="bare", user=_BARE)
    staged, err = staged_for_turn(stage, bare_turn)
    assert (staged, err) == (None, "")
    assert _capture(window, _BARE, "fast", staged) == {"text": _BARE, "role": "fast"}
    assert matrix_turn_payload(_BARE) == {"text": _BARE}

    _fresh(drops, stage)
    stage._stage_paths([png])
    button_atts = list(stage.attach_bar.attachments())
    button = _capture(window, _ASK, "fast", button_atts)

    _fresh(drops, stage)
    turn = ConversationTurn(id="look", user=_ASK, attachments=(str(png),))
    staged, err = staged_for_turn(stage, turn)
    assert err == ""
    driver = _capture(window, turn.user, "fast", staged)

    _fresh(drops, stage)
    item = live_matrix_items.S(
        "attach_probe",
        "vision",
        _ASK,
        ["vision"],
        attachments=(str(png),),
    )
    assert attach_paths(item) == (str(png),)
    headless = matrix_turn_payload(_ASK, attach_paths(item))

    assert driver == button
    assert driver["text"] == _ASK
    assert _PNG_NAME not in driver["text"]
    assert driver["role"] == "fast"
    row = driver["attachments"][0]
    assert row["kind"] == "image"
    assert row["name"] == _PNG_NAME
    assert row["source_path"].endswith(_PNG_NAME)
    assert headless["text"] == _ASK
    assert "role" not in headless
    assert headless["attachments"] == button["attachments"]
