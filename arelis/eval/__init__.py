"""Foundation eval: score tool routing without guessing from vibes."""

from arelis.eval.conversation import (
    ConversationTurn,
    SoakReport,
    run_conversation_soak,
    soak_registry,
)
from arelis.eval.harness import EvalResult, run_scripted_scenario
from arelis.eval.scenarios import SCENARIOS, Scenario

__all__ = [
    "SCENARIOS",
    "ConversationTurn",
    "EvalResult",
    "Scenario",
    "SoakReport",
    "run_conversation_soak",
    "run_scripted_scenario",
    "soak_registry",
]
