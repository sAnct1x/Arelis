"""_run is the loop. Prepare, one round, and the last answer are methods."""

from __future__ import annotations

import inspect

from arelis.core.agent_loop import AgentLoop


def test_run_only_calls_prepare_round_and_force() -> None:
    src = inspect.getsource(AgentLoop._run)
    assert src.count("\n") < 25
    assert "await self._prepare_turn(" in src
    assert "await self._run_round(" in src
    assert "await self._force_final_answer(" in src
    assert "for round_i in range" in src


def test_prepare_and_round_are_the_bodies() -> None:
    from arelis.core.turn_prepare import prepare_turn
    from arelis.core.turn_round import run_round

    prepare = inspect.getsource(prepare_turn)
    round_src = inspect.getsource(run_round)
    assert "TurnContext" in prepare
    assert "return ctx" in prepare
    assert "return True" in round_src
    assert "return False" in round_src
    assert "await apply_no_call_path(" in round_src
    assert "await dispatch_calls(" in round_src
    assert "from arelis.core.turn_prepare import prepare_turn" in inspect.getsource(
        AgentLoop._prepare_turn
    )
    assert "from arelis.core.turn_round import run_round" in inspect.getsource(
        AgentLoop._run_round
    )
