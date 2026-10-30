"""Switch each guard rail off and see whether the eval board notices.

A test you have never watched fail is not a test. This script makes that
check mechanical: disable one guard rail, re-run the scripted board, and
compare which scenarios pass. A guard you can switch off with the board
still green has **no coverage** — the script calls that a hole and exits
non-zero.

The finding this exists to prevent recurring is recorded at
``arelis/eval/tool_choice.py:3-8``: on 2026-08-14 the whole board scored a
perfect run with the tool subset, the skill cards, intent preflight and the
force gates each disabled. Every guard rail was a hole and the board said
nothing, because 35 of its 68 scenarios hand the loop the tool call they
then assert was made (see ``scripts/audit_eval_scenarios.py``).

    python scripts/mutate_guards.py
    python scripts/mutate_guards.py --guard exactness   # just one

Expect holes until Phase 0.3 inverts the tautologies. The number going down
is the progress metric for that work.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from typing import Any

from arelis.eval.harness import run_all_scripted


@dataclass(frozen=True)
class Mutation:
    """One guard rail, switched off the way production would switch it off."""

    name: str
    overrides: dict[str, Any]
    guards: str
    note: str = ""
    # Why this board structurally cannot see the guard. Set this only with a
    # reason that survives scrutiny: it excuses a guard from the hole count,
    # and an excuse is how a board goes back to measuring nothing. A blind
    # spot that turns out to produce a red is reported as covered instead.
    blind_spot: str = ""


# Ordered loudest-first: the mechanisms the compensation layer leans on most.
MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="tool_subset",
        overrides={"skill_tool_subset": False, "research_tool_subset": False},
        guards="tool_subset.py — the per-turn tool menu",
        blind_spot=(
            "data/default.yaml ships both flags False, so this mutation is a "
            "no-op against a board that now matches the shipped config. There "
            "is no guard here to cover: the full registry is what goes out."
        ),
    ),
    Mutation(
        name="exactness",
        overrides={"exactness": False},
        guards="gates.py FORCE_GATES + evidence.py — master switch",
    ),
    Mutation(
        name="numeric_gate",
        overrides={"numeric_gate": False},
        guards="gates.py — math / symbolic / units / plot / catalog force",
    ),
    Mutation(
        name="evidence_gate",
        overrides={"evidence_gate": False},
        guards="evidence.py + claims.py — quote-first and send-claim checks",
    ),
    Mutation(
        name="research_dual_hit",
        overrides={"research_dual_hit": False},
        guards="dual-source research nudge",
        blind_spot=(
            "Only fires inside research mode, which the scripted path does not "
            "enter: the second source gets fetched either way. Measuring this "
            "needs the live research runner, not this board."
        ),
    ),
    Mutation(
        name="lessons",
        overrides={"lessons": False},
        guards="ACE failure lessons injected from turns.log",
        blind_spot=(
            "A prompt-only guard. `_ScriptedRouter.stream` never reads "
            "`messages`, so nothing that works by changing what the model is "
            "told can move this board — true for lessons, for the preflight "
            "nudge text, and for the compact tool policy. Preflight still "
            "scores reds here because it also seeds `_expected_tools`, which "
            "is behaviour rather than wording. Prompt-only guards belong to "
            "the live tool-choice runner."
        ),
    ),
    Mutation(
        name="everything",
        overrides={
            "skill_tool_subset": False,
            "research_tool_subset": False,
            "exactness": False,
            "numeric_gate": False,
            "evidence_gate": False,
            "research_dual_hit": False,
            "lessons": False,
        },
        guards="the entire ~12,700-line compensation layer at once",
        note="This is the 2026-08-14 run. If the board stays green here, it is measuring nothing.",
    ),
)

# `skill_cards` is deliberately absent: no production code reads it. The
# harness sets it at harness.py:643 and the 2026-08-14 note claims the skill
# cards were disabled, but the switch is wired to nothing. Card *bodies* left
# the prompt when compact_tool_policy landed; `skill_tool_subset` is the only
# live lever. Do not add a mutation for a dead key — it would report a hole
# that is really a no-op, which is the same lie in the other direction.
DEAD_KEYS = (
    "skill_cards",
    "intent_preflight",
    "weather_force_call",
    "sms_force_call",
    "email_force_call",
    "agenda_force_call",
    "image_force_call",
    "vision_force_call",
    "tasks_force_call",
    "goals_force_call",
    "recall_force_call",
    "document_force_call",
    "diagnostics_force_call",
    "inspect_force_call",
)


@dataclass
class Outcome:
    mutation: Mutation
    passed: set[str]
    broke: list[str] = field(default_factory=list)

    @property
    def is_covered(self) -> bool:
        return bool(self.broke)

    @property
    def is_hole(self) -> bool:
        """Silent *and* with no standing reason to be silent."""
        return not self.broke and not self.mutation.blind_spot


async def passing_ids(overrides: dict[str, Any] | None) -> set[str]:
    results = await run_all_scripted(agent_overrides=overrides)
    return {r.scenario_id for r in results if r.ok}


async def run(selected: str | None) -> int:
    print("baseline: running the scripted board with every guard rail on…")
    baseline = await passing_ids(None)
    total = len(await run_all_scripted(agent_overrides=None))
    print(f"  {len(baseline)}/{total} scenarios pass\n")

    mutations = [m for m in MUTATIONS if selected in (None, m.name)]
    if not mutations:
        print(f"no mutation named {selected!r}. known: {', '.join(m.name for m in MUTATIONS)}")
        return 2

    outcomes: list[Outcome] = []
    for mutation in mutations:
        survived = await passing_ids(mutation.overrides)
        broke = sorted(baseline - survived)
        outcome = Outcome(mutation=mutation, passed=survived, broke=broke)
        outcomes.append(outcome)
        if broke:
            mark = f"{len(broke)} red"
        elif mutation.blind_spot:
            mark = "blind spot"
        else:
            mark = "HOLE"
        print(f"  {mutation.name:24} {len(survived):3}/{total}  {mark}")

    covered = [o for o in outcomes if o.is_covered]
    holes = [o for o in outcomes if o.is_hole]
    blind = [o for o in outcomes if not o.is_covered and o.mutation.blind_spot]

    print()
    print("=" * 72)
    print(f"COVERED ({len(covered)}) — switching this off turns the board red")
    print("=" * 72)
    for outcome in covered:
        print(f"\n  {outcome.mutation.name}")
        print(f"    guards: {outcome.mutation.guards}")
        print(f"    caught by: {', '.join(outcome.broke[:6])}")
        if len(outcome.broke) > 6:
            print(f"               … and {len(outcome.broke) - 6} more")

    print()
    print("=" * 72)
    print(f"HOLES ({len(holes)}) — switch it off, board stays green, nothing tests it")
    print("=" * 72)
    if not holes:
        print("\n  none.")
    for outcome in holes:
        print(f"\n  {outcome.mutation.name}")
        print(f"    guards: {outcome.mutation.guards}")
        if outcome.mutation.note:
            print(f"    note:   {outcome.mutation.note}")

    print()
    print("=" * 72)
    print(f"BLIND SPOTS ({len(blind)}) — this board cannot see these, and says why")
    print("=" * 72)
    for outcome in blind:
        print(f"\n  {outcome.mutation.name}")
        print(f"    guards: {outcome.mutation.guards}")
        print(f"    reason: {outcome.mutation.blind_spot}")

    print()
    if DEAD_KEYS:
        print(f"not measured (config key is read by nothing): {', '.join(DEAD_KEYS)}")
    print()
    print(
        f"RESULT: {len(covered)} covered, {len(holes)} holes, "
        f"{len(blind)} blind spots."
    )
    return 1 if holes else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guard", default=None, help="run one mutation by name")
    args = parser.parse_args()
    return asyncio.run(run(args.guard))


if __name__ == "__main__":
    raise SystemExit(main())
