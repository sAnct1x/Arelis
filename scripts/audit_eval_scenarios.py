"""Which foundation scenarios can actually fail for the reason they claim?

``arelis/eval/tool_choice.py`` already records the finding: 49 of the then-59
foundation scenarios emit their own ``tool_calls``, and the board scored a
perfect run with the tool subset, the skill cards, intent preflight and four
force gates each disabled. A board that cannot see the mechanism it guards is
decoration.

This script sorts the current board into three buckets so the number is
maintained rather than remembered:

**tautology** — the script hands the loop exactly the call the scenario then
asserts was made. ``_ScriptedRouter.stream`` never reads ``messages`` or
``tools``, so nothing the scenario says about tool *choice* is under test.

**real** — the assertion does not depend on a handed-over call. These script
the model's *mistake* (a confident claim with no tool behind it) and assert
Arelis corrected it. That is the shape a scenario should have.

**mixed** — hands over the call, but also asserts something downstream that is
genuinely exercised: confirm policy, truncation, tool-result framing.

    python scripts/audit_eval_scenarios.py

Run it after editing the board. The tautology count should only ever go down.

This is a heuristic over scenario *shape*, and it has one blind spot it cannot
close: it reads the script as a set of tool names, not as an ordered
transcript. A nudge scenario like ``search_without_read_gets_nudged`` offers
the right call in a later round that is only reachable if the nudge fires, and
that reads here as handed-over. The authority on whether a scenario can fail is
``scripts/mutate_guards.py``, which answers the question by experiment instead
of by inspection. Use this to find candidates; use that to settle it.
"""

from __future__ import annotations

from typing import Any

from arelis.eval.scenarios import SCENARIOS, Scenario


def scripted_tools(scenario: Scenario) -> list[str]:
    """Tool names the script hands the loop, in order."""
    names: list[str] = []
    for round_ in scenario.script or []:
        for kind, payload in round_:
            if kind != "tool_calls":
                continue
            for call in payload or []:
                function: dict[str, Any] = call.get("function") or {}
                names.append(str(function.get("name") or ""))
    return names


def independent_assertions(scenario: Scenario, handed: list[str]) -> list[str]:
    """Assertions that survive the script handing over the call."""
    found: list[str] = []
    wants = set(scenario.expect_tools or ())
    if scenario.allow_no_tools:
        found.append("refuse-path")
    if scenario.forbid_claim_if_no_tool and not handed:
        found.append("no-tool-claim-gate")
    if scenario.forbid_tools:
        found.append("forbidden-tool-check")
    if scenario.expect_confirm_tools:
        found.append("confirm-policy")
    if scenario.expect_tool_result_contains:
        found.append("tool-result")
    if scenario.expect_truncated is not None:
        found.append("truncation")
    if scenario.expect_model_switch_reason:
        found.append("model-switch")
    if not handed and scenario.expect_tools:
        found.append("loop-injected-call")
    elif wants and not wants.issubset(set(handed)):
        # The script hands over a call, but not the one asserted: the scenario
        # is testing that Arelis redirected away from the model's mistake.
        found.append("redirected-from-wrong-call")
    return found


def classify() -> tuple[
    list[Scenario], list[tuple[Scenario, list[str]]], list[tuple[Scenario, list[str]]]
]:
    tautology: list[Scenario] = []
    real: list[tuple[Scenario, list[str]]] = []
    mixed: list[tuple[Scenario, list[str]]] = []
    for scenario in SCENARIOS:
        handed = scripted_tools(scenario)
        wants = list(scenario.expect_tools or ())
        handed_all = bool(wants) and all(w in handed for w in wants)
        independent = independent_assertions(scenario, handed)
        if not independent:
            # Includes the handed-over case and the rarer one where a scenario
            # asserts nothing an unscripted run would not also satisfy.
            tautology.append(scenario)
        elif handed_all:
            mixed.append((scenario, independent))
        else:
            real.append((scenario, independent))
    return tautology, real, mixed


def main() -> int:
    tautology, real, mixed = classify()
    total = len(SCENARIOS)
    print(f"foundation scenarios: {total}")
    print(f"  tautology (script hands over what is asserted): {len(tautology)}")
    print(f"  mixed     (handed over, but asserts downstream): {len(mixed)}")
    print(f"  real      (assertion survives without the hand): {len(real)}")
    print()
    print("--- TAUTOLOGY: cannot fail for the reason the note claims ---")
    for scenario in tautology:
        print(f"  {scenario.id:38} expects={','.join(scenario.expect_tools) or '-'}")
    print()
    print("--- REAL ---")
    for scenario, why in real:
        print(f"  {scenario.id:38} {'+'.join(why)}")
    print()
    print("--- MIXED ---")
    for scenario, why in mixed:
        print(f"  {scenario.id:38} {'+'.join(why)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
