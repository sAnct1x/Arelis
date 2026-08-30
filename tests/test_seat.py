"""build_seat profiles keep the product differences that used to be copies."""

from __future__ import annotations

from arelis.config import load_config
from arelis.core.seat import bind_workspace, build_seat
from arelis.workspace import WorkspaceRoots


def test_bind_workspace_sets_config_and_stt(tmp_path) -> None:
    config: dict = {"workspace": {"roots": [str(tmp_path)]}, "voice": {}}
    roots = bind_workspace(config)
    assert isinstance(roots, WorkspaceRoots)
    assert config["_workspace"] is roots
    assert config["voice"]["stt"]["initial_prompt"]


def test_job_seat_is_unattended_and_ephemeral() -> None:
    seat = build_seat(load_config(), profile="job")
    assert seat.store is None
    assert seat.memory.sink is None
    assert "send_email" not in seat.tools.names()
    assert "tile" not in seat.tools.names()
    assert "image" in seat.tools.names()


def test_ui_seat_is_glass_and_attended() -> None:
    seat = build_seat(load_config(), profile="ui")
    assert seat.store is not None
    assert seat.memory.sink is seat.store
    assert "tile" in seat.tools.names()
