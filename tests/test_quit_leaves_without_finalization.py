"""After the UI shut down, main leaves with os._exit: finalization took 11 s and crashed."""

from __future__ import annotations

import pytest


def test_ui_exit_skips_interpreter_finalization(monkeypatch) -> None:
    from arelis import main as main_mod
    from arelis.ui import launch

    exits: list[int] = []

    def _fake_exit(code: int) -> None:
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(launch, "UI_EXITED", True)
    monkeypatch.setattr(main_mod.os, "_exit", _fake_exit)
    monkeypatch.setattr("logging.shutdown", lambda: None)
    with pytest.raises(SystemExit):
        main_mod._leave_ui(0)
    assert exits == [0]
