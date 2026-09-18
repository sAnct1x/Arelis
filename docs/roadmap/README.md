# Roadmap

Written 2026-09-16 against commit `e5b0f2f` plus the uncommitted PDF lane.
This is a working checklist, not a vision doc. Steps are numbered so a
sitting can say "I did 3.14" and mean something.

Audit source: a full read of `arelis/` (170k lines) and `tests/` (40k).
Numbers in here were measured on this checkout, not estimated.

## Contents

- [The thesis](#the-thesis)
- [Phase 0 — safety net](#phase-0--safety-net)
- [Phase 1 — close the in-flight PDF lane](#phase-1--close-the-in-flight-pdf-lane)
- [Phase 2 — the schema experiment](#phase-2--the-schema-experiment)
- [Phase 3 — cleanup and dedup](#phase-3--cleanup-and-dedup)
- [Phase 4 — tool depth](#phase-4--tool-depth)
- [Phase 5 — the missing tools](#phase-5--the-missing-tools)
- [Phase 6 — usability](#phase-6--usability)
- [Phase 7 — ship 0.2.8](#phase-7--ship-028)
- [Frozen](#frozen)

---

## The thesis — measured, and wrong

> **Superseded 2026-09-17.** Everything in this section was written before
> anything was measured. `scripts/measure_tool_choice.py` now exists and
> the numbers contradict it. Read the verdict first; the argument below is
> kept because it is a good example of how this codebase got the way it is,
> and because deleting a wrong conclusion hides the fact that it was
> reached confidently.

### The verdict

Thirteen runs against qwen3.5:9b on the 42-case tool-choice corpus, three
seeds per config:

| Config | Seeds 1, 2, 3 | Mean | Spread |
|---|---|---:|---:|
| `skinny`, unguarded | 33, 30, 32 | 31.7 | 3 |
| `full` schema, unguarded | 34, 34, 34 | 34.0 | **0** |
| `skinny` + preflight — **what ships** | 37, 39, 37 | **37.7** | 2 |
| `full` + preflight | 40, 38, 38 | 38.7 | 2 |

- **The guard rails are worth +6.0 and it replicates.** They are the most
  effective thing in the codebase. The 12,700 lines are not a wound.
- **Restoring every description is worth +1.0**, against a noise band of
  ±2 measured by re-seeding a single arm. It is indistinguishable from
  what ships, and costs **2.4× the prefill** (18,735 tokens vs 7,944) on
  every turn, forever, on a 12 GB card.
- Therefore **Phase 2 as written is cancelled.** Do not rewrite
  `compact_prompt.py`.

Two things survive. First, the `full` arm scored 34/34/34 — *zero* spread.
A rich schema makes tool choice deterministic, which is the only real
argument in its favour, and the determinism does not survive the preflight
nudge. Second, per-case analysis shows the full schema reliably fixes
exactly two cases — `weather` and `send_sms` — so those two descriptions
are load-bearing even though the other 41 are not. That is a surgical
edit measured in hundreds of tokens, not eleven thousand.

What replaces Phase 2 is a **hole-by-hole sweep of the guard layer**,
driven by this runner. The first hole is already fixed and pushed
(`6203c8b`): `_WEATHER_WANDER` omitted `user_location`, so hiding the
three search tools on a weather turn pushed the model onto the one tool
nothing redirected. Four words in a frozenset.

The methodological lesson is the one this repo keeps teaching. A year of
sessions each patched the symptom in front of them because none could
measure the cause. An audit reasoning from the same evidence reached the
same kind of confident, wrong conclusion — and would have spent a week
proving it.

### The original argument, for the record

Arelis describes 41 tools to a 9B model in a median of **43 characters
each**, with **zero descriptions on any of its 292 parameters**, and then
spends roughly **12,700 lines of Python regex** correcting the wrong
guesses that follow.

That is not an accident. `arelis/core/compact_prompt.py` strips parameter
descriptions on purpose, and `arelis/core/tool_subset.py:11-31` documents
the measurement that justified it: a tools array that changes shape per
turn invalidates Ollama's prefix cache and costs five times the
steady-state prefill. So the array was frozen and shrunk, descriptions
were replaced by a telegraph table, and the model's resulting confusion
was absorbed in Python.

The compensation layer, measured:

| Module | Lines | Compiled regexes |
|---|---:|---:|
| `core/skills.py` | 1,731 | — |
| `core/claims.py` | 1,399 | 102 |
| `core/intent_catalog.py` | 1,339 | 115 |
| `core/preflight.py` | 1,381 | — |
| `core/no_call_steps.py` | 844 | — |
| `core/plan_nudge.py` | 736 | — |
| `core/evidence.py` + `gates.py` + `call_redirects.py` + `same_call.py` | 1,327 | — |
| `core/sms_complete.py` + `email_complete.py` + `agenda_complete.py` | 3,935 | 84 |
| **Total** | **~12,692** | **300+** |

Against a tool surface of ~4,900 tokens.

Two consequences drive the phase order below.

**First**, this is why the top two complaints are "picks the wrong tool"
and "tools are too shallow." Every regex family is a patch for one
specific misroute someone hit in a live session. The layer works — it is
genuinely battle-tested — but it only covers phrasings that have already
failed once, in front of you.

**Second**, and this is the scheduling constraint: you cannot safely
delete any of it without a regression net, and **there is no net** —
which is a correction to this document's first draft, made the same day.

The first draft said the net existed and merely needed plugging in:
`arelis/eval/` holds 68 scripted scenarios, 18 skill-retrieval cases and
42 tool-choice cases, deterministic and Ollama-free, none of them wired
into pytest or CI. Plugging them in looked like a day of work.

Then we read them. `scripts/audit_eval_scenarios.py` sorts the board:

| Bucket | Count | What it means |
|---|---:|---|
| Tautology | **35** | The script hands the loop the call the scenario asserts was made |
| Mixed | 19 | Hands over the call, but checks confirm policy / truncation / result framing |
| Real | 14 | Assertion survives without the handout |

`_ScriptedRouter.stream()` never reads `messages` or `tools`. It replays
a hardcoded script. So `weather_oneshot` — annotated "Must call weather,
not scrape AccuWeather" — scripts a weather call and asserts a weather
call. It cannot produce a scrape. It cannot fail.

This was already known here. `arelis/eval/tool_choice.py:3-8`, written
2026-08-14, records the experiment: the board scored a **perfect run with
the tool subset, the skill cards, intent preflight and all four force
gates disabled**. That module is the honest replacement — 42 cases, real
schemas, defensible-alternatives scoring — and it is a scorer with **no
runner**, so it has never produced a number.

The 14 real scenarios show what the fix looks like. Every one of them
scripts the model's *mistake* and asserts Arelis corrected it. The
tautologies all do the inverse. Phase 0 inverts them.

Worth saying plainly: this pathology is confined to the eval board.
`scripts/audit_test_assertions.py` scans the 1,925-function unit suite
and flags 0.9% — 4 with no assertion, 13 with only truthiness. Files like
`tests/test_preflight.py` are the good kind, asserting on real
`detect_intents` output *and on what must not fire* ("text me later" is
not an SMS). The unit tests are a net. The agent-behaviour board is not.

So Phase 0 is not optional throat-clearing, and it is bigger than the
first draft thought. It is the thing that makes the cleanup phase
survivable.

### What this roadmap is not doing

Earth / Reality / solar is **frozen** — see [Frozen](#frozen). It is
~24k lines, ships in no installer, and is the single largest source of
"we could work on that instead." We are not working on that instead.

---

## Phase 0 — safety net

Nothing else starts until this is green. Every step here is offline and
fast; none of it needs Ollama, a GPU, or the GUI.

> **Revised 2026-09-16.** The first draft of this phase said "wire the 68
> foundation scenarios into CI as the regression net." That was wrong, and
> wrong in the most expensive direction: it would have installed a green
> light over a board that cannot see the thing it claims to guard.
>
> `arelis/eval/tool_choice.py:3-8` already records the finding, measured
> 2026-08-14: the foundation board scored a **perfect run with the tool
> subset, the skill cards, intent preflight and all four force gates
> disabled**. `scripts/audit_eval_scenarios.py` re-measures it on today's
> board — **35 of 68 scenarios are pure tautology**. The scenario hands
> `_ScriptedRouter` the exact tool call it then asserts was made, and
> `_ScriptedRouter.stream()` never reads `messages` or `tools` at all.
> `weather_oneshot` is annotated "Must call weather, not scrape
> AccuWeather" and scripts a weather call. It cannot produce a scrape.
>
> The 14 scenarios that *are* real share one shape: **the script hands
> over the model's mistake and the assertion is that Arelis corrected
> it.** That is the shape. Phase 0 converts the rest to it.
>
> **Closed 2026-09-17.** 79/79 board, 12 holes → 0, three blind spots each
> with a written reason. Two real bugs fell out of the work: the SMS body
> lock was disabled for anyone not in your contacts (0.3b), and the stub
> mirror for `vision` had drifted from the tool the PDF lane is currently
> changing (0.1). Both were caught by tests that already existed or by the
> first run of a test that should have — which is the argument for this
> phase in one sentence.

### The rule this phase establishes

**A test is not trusted until it has been watched failing for the reason
it exists.** Writing the assertion is half the work; the other half is
breaking the thing on purpose and confirming the red. Steps 0.5 and 0.6
make that mechanical rather than a good intention.

- [x] **0.1** Write `tests/test_eval_stub_schemas.py`. `harness.py:39-40`
  already names this file. It should assert that every stub tool in
  `foundation_registry` (`harness.py:538-576`) matches the real registry's
  name, required args, and enum values. Without it, the 68 scenarios can
  pass against schemas that no longer exist.
  **Done — and it found drift on the first run.** The in-flight PDF lane
  gave `vision` a `paths` parameter and dropped `path` from its required
  list; the stub mirror still required `path`, so a scenario calling
  `vision(paths=[…])` would have been rejected offline while working live.
  Two notes for anyone extending it: the registry has to be built
  `attended=True` *with* a router or `vision` and `camera` read as missing,
  and conftest's isolated `ARELIS_DATA_DIR` means the four
  credential-gated tools never register under pytest — they are named in
  `CREDENTIAL_GATED` rather than skipped quietly.
- [x] **0.2** Write the tool-choice coherence checks. Assert every
  tool in `tool_choice.case_tools()` exists in the real registry. The
  module docstring names this exact failure — "a case naming a tool the
  registry no longer offers is a case that can never pass". Do **not**
  write a test that calls `score({})` and asserts 42 misses; that is
  another tautology.
  **Done**, in `tests/test_eval_board.py` alongside the board itself
  rather than a file of its own. Currently coherent: no case names a
  missing tool, no case is unanswerable, no utterance is duplicated.
- [x] **0.3** Invert the tautologies, worked in the order the hole table
  below gives. For each one the script hands over the **wrong** call and
  the assertion becomes that Arelis rewrote or blocked it.
  **Done, and the strategy changed once the measurement was available.**
  Rewriting all 35 blind was the plan; it is the wrong trade. What matters
  is guard *coverage*, which `mutate_guards.py` measures directly, so the
  work became: add inversions aimed at measured holes, and rewrite only
  the tautologies whose notes actively lie about what they test
  (`weather_oneshot` was annotated "Must call weather, not scrape
  AccuWeather" and scripted a weather call). Twelve inversions took the
  hole count from 12 to 0. The remaining tautologies are plumbing checks
  and are now labelled as such instead of pretending.
- [x] **0.3b** Fix the standing red. **`sms_body_matches_draft` was not a
  tautology and not a broken test — it was a real bug the board caught and
  nobody read.** It scripts the correct tool with a deliberately wrong
  body and asserts the draft body is locked. The lock in
  `sms_complete.fill_send_sms_args` was gated on `draft.complete`, which
  means "every recipient has an address" — so texting someone *not in your
  contacts* let the model rewrite the message, and the confirm card showed
  the rewrite rather than what would send. Body integrity and recipient
  resolution are independent questions; the body is the user's own words
  in both the `current` and `history` draft paths. Fixed, with three unit
  tests in `test_sms_complete.py` watched failing first.
- [x] **0.4** Wire `run_all_scripted()` into pytest — **after** 0.3, not
  before. Assert an exact pass count, not a threshold; a threshold hides
  which one broke. **Done** in `tests/test_eval_board.py`, plus checks
  that no scenario is unscripted, no id is duplicated, and nothing both
  expects and forbids the same tool. Whole file runs in ~2s.
- [x] **0.5** Add `scripts/mutate_guards.py`: disable one guard rail and
  re-run the board. Every guard must produce at least one named red. A
  guard that can be switched off with the board still green has no test,
  and the script prints it as a hole. **Done — see the baseline below.**
- [x] **0.6** Wire 0.5 into CI as a weekly job, not per-push — it is slow
  and its job is to catch the net rotting, not to gate a diff.
  **Done:** `.github/workflows/guard-coverage.yml`, Mondays 07:00 UTC plus
  manual dispatch, uploading the report as an artifact.
- [x] **0.7** Cover `run_retrieval_board()` (`skill_retrieval.py:265-298`).
  18 cases, pure function, no I/O. **Done** in `tests/test_eval_board.py`.
  Carrying 0.5's caveat honestly: `mutate_guards.py` cannot reach this
  board, so it has *not* been watched failing. Treat it as unproven until
  it has been.
- [ ] **0.8** Put the pass-rate floors in one module
  (`tests/eval_floors.py`) so raising a floor after an improvement is a
  one-line diff with a date, and a drop is one named failing assert.
  Not done — with the counts pinned in two files it is not yet worth the
  indirection. Revisit when the live runner (0.9) adds a third.
- [ ] **0.9** Build the missing runner for `CHOICE_CASES`. The corpus and
  the scorer exist; nothing feeds them, so the 42 cases have never
  produced a number. This one needs live Ollama, so it is a nightly Tier 2
  job rather than a CI gate — but it is the only measurement in the repo
  that answers "does the model pick the right tool," which is the metric
  Phase 2 exists to move. Record the first run as the baseline.
- [x] **0.10** Fix the ruff errors in the uncommitted PDF lane. **Done**
  via `ruff check --fix`; the tree is clean.
- [x] **0.11** Add `.tmp_pdfium/` to ruff's `extend-exclude` in
  `pyproject.toml`. Previously `ruff check .` reported 1,970 errors and
  1,964 of them were a vendored wheel, which made the command useless as a
  signal. **Done** — `ruff check .` is now clean and means something.
- [x] **0.12** Install `pytest-timeout` so `timeout` and `timeout_method`
  in `pyproject.toml` stop warning as unknown config. CI had it; local did
  not, so local and CI disagreed about whether a hung test fails. **Done.**
- [x] **0.13** Promote the schema measurement into
  `scripts/measure_tool_schema.py`. **Done**, and it turned up the finding
  that reshapes Phase 2 — see below.
- [x] **0.14** Write `tests/test_tool_schema_quality.py` as a ratchet.
  **Done.** Pins tool count, schema token budget, minimum and median
  description length, `action` enums, and both halves of the strip: that
  every source description still exists, and that none of them reach the
  model. When Phase 2 lands, the last assertion inverts rather than
  loosens.
- [x] **0.15** Add an `eval` job to `.github/workflows/ci.yml`, blocking,
  running only the new offline test files. Keep it a separate job so a
  routing regression reads as "eval failed," not as one red dot in a
  2,000-test run. **Done**, and pinned by `tests/test_ci_gate.py` so it
  cannot be dropped or quietly turned into `continue-on-error`.
- [x] **0.16** Triage the hits from `scripts/audit_test_assertions.py`.
  **Done, and half the finding was my own instrument being wrong.** Of the
  4 "no assertion" hits, 2 were false positives: one raises
  `AssertionError` directly, one delegates to an `_assert_routes_*` helper.
  The script now recognises both, because an audit tool that cries wolf
  gets ignored. The other 2 were genuine "did not crash" smoke tests and
  are now strengthened — `emit_nowait` also asserts a bound bus *receives*
  the event, so deleting the function body fails the test.
  No-assert is now 0. **13 weak-assert hits remain and are deliberately
  not touched:** 5 are in the frozen Earth/physics and rooms lanes, and
  the rest need individual reads. Listed by the script on every run.

**Exit criteria:** the inverted board passes, runs in under 30 seconds,
runs in CI on every push — and `scripts/mutate_guards.py` reports **zero
holes**, meaning every guard rail in the compensation layer has at least
one test that goes red when you switch it off. The pass count is not the
exit criterion; the mutation result is.

**Status: met.** 79/79 board, ~2s under pytest, blocking in CI, and
`mutate_guards.py` reports **16 covered, 0 holes, 3 blind spots** with a
written reason each. Full suite 2,024 passed.

### Measured guard coverage

`python scripts/mutate_guards.py`. Baseline 2026-09-16 on the left, after
Phase 0 on the right. **12 holes → 0.**

| Guard | Before | After | Covered by |
|---|---|---|---|
| `exactness` (master) | 16 red | 16 red | refuse-path family |
| `numeric_gate` | 9 red | 9 red | units / catalog refusals |
| `evidence_gate` | 7 red | 7 red | claim-warrant family |
| `tasks_force_call` | 1 red | 2 red | + `tasks_wander_is_redirected` |
| `goals_force_call` | 1 red | 2 red | + `goals_wander_is_redirected` |
| `intent_preflight` | **HOLE** | 4 red | the redirect inversions |
| `weather_force_call` | **HOLE** | 2 red | `weather_oneshot`, `weather_wander_is_redirected` |
| `sms_force_call` | **HOLE** | 1 red | `sms_force_when_model_answers_instead` |
| `email_force_call` | **HOLE** | 1 red | `email_force_when_model_answers_instead` |
| `agenda_force_call` | **HOLE** | 1 red | `agenda_force_when_model_invents` |
| `vision_force_call` | **HOLE** | 1 red | `vision_force_when_model_guesses` |
| `image_force_call` | **HOLE** | 1 red | `image_force_when_model_pretends` |
| `scrape_after_search` | **HOLE** | 1 red | `search_without_read_gets_nudged` |
| `browser_after_js_shell` | **HOLE** | 1 red | `js_shell_sends_her_to_the_browser` |
| `plan_progress` | **HOLE** | 1 red | `plan_step_is_not_dropped` |
| `tool_subset` | covered | *blind spot* | shipped default is already off |
| `research_dual_hit` | **HOLE** | *blind spot* | needs research mode |
| `lessons` | **HOLE** | *blind spot* | prompt-only; see below |
| `recall_force_call` | *no guard* | 1 red | `recall_ask_does_not_end_in_a_shrug` |
| `inspect_force_call` | *no guard* | 2 red | source ask: redirect + no-call |
| `document_force_call` | *no guard* | 1 red | `a_pdf_ask_ends_in_a_file` |
| `diagnostics_force_call` | *no guard* | 1 red | `a_test_result_is_never_asserted_from_memory` |
| *everything at once* | 45/68 | 46/79, 33 red | — |

**The three remaining are blind spots, not holes, and the distinction is
load-bearing.** A hole is a guard nothing tests. A blind spot is a guard
this board structurally cannot see, recorded with a reason that has to
survive scrutiny — because an unexamined excuse is how a board goes back
to measuring nothing. `mutate_guards.py` exits non-zero on holes and
prints blind spots separately with their justification.

- `tool_subset` — `data/default.yaml` ships both flags off, so after 0.18
  the mutation is a no-op. There is no guard here: the full registry is
  what goes out.
- `research_dual_hit` — only fires inside research mode, which the
  scripted path never enters. Belongs to the live runner (0.9).
- `lessons` — **prompt-only, and this generalises.**
  `_ScriptedRouter.stream` never reads `messages`, so *nothing that works
  by changing what the model is told* can move this board: not lessons,
  not the preflight nudge wording, not the compact tool policy. Preflight
  still scores 4 reds because it also seeds `_expected_tools`, which is
  behaviour rather than wording. This is the honest ceiling of offline
  scripted evaluation and the strongest argument for 0.9.

Three things the baseline established that were previously guesswork.

**The covered guards were covered almost entirely by the refuse-path
scenarios** — `arxiv_refuses_without_catalog`, `git_claim_needs_warrant`,
`constant_refuses_without_units`. The ones that script the model's
mistake. The tautologies contributed essentially nothing, which is the
thesis confirmed by mutation rather than by reading.

**Every intent force gate except tasks and goals was a hole**, and those
two only by luck — `tasks_claim_needs_warrant` and
`goals_claim_needs_warrant` happen to be refuse-path scenarios. The
`sms_immediate` / `weather_oneshot` / `agenda_today` family covered none
of the machinery they are named after.

**`skill_cards` was a dead config key.** Nothing read it. The 2026-08-14
note claims the run disabled the skill cards, but the switch was wired to
nothing, so that arm of the experiment never happened.

- [x] **0.17** Delete the `skill_cards` key from `harness.py`. **Done.**
- [x] **0.18** Reconcile harness defaults with shipped defaults. The
  harness set `skill_tool_subset: True` and `research_tool_subset: True`;
  `data/default.yaml` ships both `False`. The board was grading a
  configuration you do not run. **Done — and it immediately changed an
  answer.** `scrape_injection_still_needs_allow` asserted that a page
  telling Arelis to send a text gets stopped at the Allow card. Under the
  *shipped* config the injected `send_sms` never reaches the tool at all,
  and she says so: *"That text needs your Allow — the page asked for it,
  you did not."* The real defence is stronger than the one the board was
  checking. The scenario now asserts that, using the new `forbid_tools`
  field.

### Sweep, 2026-09-17 — three more holes, and a way to stop finding them

Coverage reached **19 covered, 0 holes, 3 blind spots** here (the same three
above), then **20** with `diagnostics` in the following section. The board
gained the `recall`, `inspect`, `document` and `diagnostics` guards it never
had.

`inspect_force_call` was the largest of the three, and the wiring says why
better than any description:

    INSPECT.expected_tools == ("workspace",)
    _HIDE_WANDER_FOR       == _DAILY_WANDER | _LOCAL_STORE | _SEE_TOOLS
                              | {"browser"}

`workspace` is in none of those. So on *"where is the Drive strip?"*
preflight did its whole job — fired the intent, mapped the ask to
`arelis/ui/panels/drive.py`, wrote a nudge naming that file — and
`web_search`, `scrape`, `web_fetch` and `browser` all stayed on the menu
anyway. Take one and she describes her own UI from whatever the web says
about "drive strip". `try_inspect` could not help: it is the *no-call*
floor and a call was made. Fixed in `dc672f5` as
`redirect_inspect_wander`, registered last for the same reason
`try_inspect` is last — *"show me the Drive strip"* is a tile ask and a
source ask at once, and the tile redirect has to keep winning it.

**Why not just add `workspace` to `_HIDE_WANDER_FOR`.** Worth recording,
because it is the obvious move and it is wrong. `_hide_daily_wander` only
sees expected tool *names*, so it cannot tell an inspect turn from *"search
the web for X and save it to notes.md"* — a turn where `workspace` is
expected and the web call is correct. Hiding there trades this bug for a
worse one. Gating on the text is what every other specific redirect in
that table already does, and that turn is now a test.

**A general check came out of this, which matters more than any one fix.**
`6203c8b` (the `user_location` / `_WEATHER_WANDER` hole) and this one are
the same bug class: what is *offered* lives in `agent_loop`, what is
*rewritten when called anyway* lives in `call_redirects`, and nothing made
them agree. So `tests/test_wander_sets_agree.py` now compares them
directly — and found a third instance on the first run.
`redirect_local_store` rewrites `user_location` on a tasks / goals /
memory / contacts turn, so it is known wander there, and
`_hide_daily_wander` offered it regardless; the model could take it and
the redirect then had to undo a round that never needed to happen. Fixed
in `cd41d24`. Milder than `6203c8b`, where the tool was hidden nowhere
*and* redirected nowhere and so failed silently, but the same drift from
the same cause. The next time one side gains a tool and the other does
not, it is a failing test name instead of a live misroute.

**The `document` gate was real and unmeasured, which is its own category.**
Worth separating from the holes above, because the roadmap had this filed as
a redirect hole and it is not one. *"Create a pdf about the dirac equation"*
fires the `document` intent correctly and arms `needs_document` on all six
phrasings, and searching the web first is *legitimate* here — she needs
content to put in the file — so blocking the search would have been the wrong
fix. The gap only surfaced on writing the board's first `document` scenario,
of which there were none: `apply_force_gates` only **nudges**. It appends the
notice, retries once, and a nudge is a request the model can decline. Every
other intent of this weight has an inject behind the nudge; this one had
nothing, so declining cost nothing and the turn ended with the research in
the chat log and no file. The tool's own description says *"do not dump the
document into chat"*, which describes the failure it was losing to.

`try_document` (`38f1651`) converts what she already wrote — the injected
body is her prose **verbatim**, which is the whole safety argument: she
produced the content and put it in the wrong container, so nothing is
invented. A guessed document body would be worse than no document, hence a
120-character floor rather than an inject on an empty answer; *"Sure, I'll
put that together"* is not a document, and an empty answer is the nudge's
job. Coverage is now **19 covered, 0 holes, 3 blind spots**.

### The `ForceGate` table, swept — 2026-09-17

The `document` finding raised a question worth more than the fix: if
`apply_force_gates` only nudges, **which of the other rows also have nothing
behind the nudge?** There are seven — `math`, `symbolic`, `units`, `plot`,
`document`, `diagnostics`, `catalog` — and only `catalog` had an inject, and
that one only fires when `content` is *empty*, which is the same blind spot
`document` had. So the sweep was worth doing, and it found two more things of
completely different kinds.

**`diagnostics` was the worst thing found in this whole audit.** Scripting a
model that keeps answering in prose produced:

    "Yes, the tests pass — the suite is green."

with **no tool call at all**. That is pain #1 in one line: not a refusal, not
a slow answer, but a confident claim about the health of the codebase that
the user will act on, invented whole. And it had two independent causes.

The detector was the larger one. `_DIAGNOSTICS_ASK` matched the literal
phrase `run diagnostics` and nothing else, so every one of

    run the tests · run pytest · run the test suite · do the tests pass?

armed **nothing anywhere** — no intent, no nudge, no `needs_diagnostics`, no
`_expected_tools`. Nobody says "run diagnostics". This is the same bug class
as the `_TASKS_UTTERANCE` day-planning gap (*"what do I have **to do**
today"* needed the literal token `task`): a regex written for the phrasing a
developer types rather than the one a person says. Both were found the same
way — by writing down how the ask actually sounds — and that is now the
cheapest audit move available for the rest of the intent catalog.

Second, there was no inject behind the nudge, so declining it cost nothing.
`try_diagnostics` (`19273c2`) is the easiest one in `no_call_steps.py`
because the tool takes no meaningful arguments — `suite` is an enum of one —
so there is nothing to synthesise and no way for the injected call to be
subtly wrong. Running the suite is also exactly what was asked for.
`detect_diagnostics_ask` vetoes *"how do I run the tests"*, which wants the
command; that veto lives in `claims.py` rather than the catalog because
Python has no variable-length lookbehind, and because this function drives
the expensive half while the preflight nudge is declinable anyway.
Coverage: **20 covered, 0 holes**.

**`plot` was not a guard hole at all, and that is the more useful finding.**
The board said *"plot the sine wave from 0 to 2pi"* ended with no tool call,
which looked like the third missing inject in a row. Reading the schema
first is what caught it:

| source | shape |
|---|---|
| a table | `path` + `x` / `y` column names |
| a tiny series | `xs` / `ys` as **literal comma-separated numbers** |
| a formula | *(did not exist)* |

…with the description ending *"This is not Python: do not pass code or
matplotlib"*. So there was no argument shape that draws `sin(x)`. The only
way to satisfy the single most obvious chart request there is was for the
model to hand-type a few hundred sine values into `ys=` — wrong, and the
exact invent-the-data failure the tool exists to prevent. No nudge can fix
that, and an inject would have had to fabricate the numbers. The tool was
too shallow to finish the job, which is pain #4, not pain #3. The
`compact_prompt` line for `python` — *"print xs,ys then plot with out="* —
records the two-tool dance that was the workaround.

`expr` + `xmin` / `xmax` (`7a9ac10`) does it in one call. Two decisions worth
keeping:

- The evaluator **reuses `cas.parse_cas_expr`** instead of growing a second
  expression parser. That is the hardened one: AST whitelist, then parse into
  a locked namespace with empty builtins. Proven load-bearing by mutation —
  swapping in bare `sympify` made `__import__("os").system(...)` *actually
  execute*, so this field would have been remote code execution behind a
  chart request if it had been written the obvious way. `plot` is reachable
  from any turn.
- Range endpoints take `2pi` and `pi/2`, because *"0 to 2pi"* is the ask and
  demanding `6.283185` pushes the rounding onto the model, which is where
  wrong numbers come from. The implicit-`*` insertion is scoped to the range
  only — the expression body stays under exactly `cas`'s rules — and carries
  two lookaheads so `1e3` does not become `e*3`.

It also **adds the first test that runs `plot.run` at all.** Everything else
in the suite touching `plot` checked copy, policy or intent routing; a tool
whose entire job is writing a PNG had no test that it writes one, which is
how a missing argument shape survived this long. Worth assuming the same is
true elsewhere.

**No scenario was added for `plot`, on purpose.** What is left to measure is
*"the model now reaches for `expr`"*, and that is a prompt-only guard —
`_ScriptedRouter` replays fixed rounds and never reads `messages`, so nothing
that works by changing what the model is told can move the scripted board.
`mutate_guards.py` already says this about `lessons` and the compact tool
policy. `test_every_scenario_can_actually_run` correctly rejected the
unscripted version ("a scenario nothing executes is a comment that looks like
a test"), and weakening that guard to house this one would have been a bad
trade.

**`math` / `symbolic` / `units` are deliberately left nudge-only.** There a
refusal is an acceptable outcome — *"I need to compute that"* is annoying but
not wrong, unlike an invented number — and
`constant_refuses_without_units` / `convert_forces_units` already measure it.

### Weather, the pain reported by name — 2026-09-17

*"Getting the weather for anywhere I want, whenever I want has been the
craziest challenge, and it's the most available information."* Two separate
bugs, and the first is **pain #1, not pain #4.**

**Anywhere.** `geocode_place` asked Open-Meteo for `count=1` and returned a
bare `(lat, lon)`, discarding the resolved name, region and country. The tool
then printed:

    Place: {asked}

…the user's *own string*, echoed back. So *"weather in Springfield"* resolved
to whichever Springfield ranked first out of the thirty-odd that exist, and the
output read `Place: Springfield` either way. **No layer had any signal that
the forecast was for the wrong one.** A wrong answer the user cannot see is
strictly worse than a refusal, and this one arrives with four decimal places
of false precision attached.

The module docstring already had the exact fear written down — *"a confident
forecast for somewhere the user is not"* — pointed at the wrong failure. It
guarded against the **model** inventing coordinates while the **tool** quietly
picked the wrong city. Worth remembering as a pattern: a comment describing a
risk is not evidence the risk is handled, and the guard may be aimed one layer
away from where the bug lives.

`resolve_place` (`6c24b42`) keeps the label and reports it, and asks for
several candidates instead of one — which is what makes ambiguity *detectable*,
since `count=1` cannot tell "the only Springfield" from "the first of thirty".
When the name matched more than one place the answer says so, once, as a fact
rather than a question. An unambiguous name says nothing extra, because a
disambiguation note on every forecast is noise that gets ignored.
`geocode_place` stays as the narrow face of it for the briefing and profile
paths, which have nowhere to show a label.

**Whenever.** `days` was the only time argument, and it cannot answer either
ordinary question:

| ask | why `days` cannot |
|---|---|
| *"will it rain at three?"* | a daily row carries `precipitation_probability_max` — the maximum over the **whole day**, which says nothing about three o'clock |
| *"what was it yesterday?"* | forecast rows start **today**; no parameter, no fallback, and nothing in the failure text to hint at one |

Both were one query parameter away (`hourly=`, `past_days=`), the same shape as
the rest of this section. `days` was also capped at 7 while the API serves 16,
so "in two weeks" was unreachable for no reason.

`hours` trims from *now* rather than from midnight — Open-Meteo returns whole
days, and with `past_days` set the series starts yesterday, so without the trim
"the next 6 hours" means "6 hours starting at 00:00". The cursor compares ISO
strings rather than parsing dates, so a format change degrades to "start at the
beginning" instead of raising mid-turn.

**Adding the parameters was only half the fix, and this is the part worth
carrying forward.** The injected call is built by `draft_weather_args`, not by
the model, so a turn reaching `weather` through the force gate still asked for
daily rows — then answered *"will it rain at three"* from a daily maximum. The
same confident guess as before, with the fix sitting there unused.
`weather_wants_hourly` (`6a9898b`) reads the markers people use and returns a
window: 12 hours for today, 36 when the ask names tomorrow *and* a time of day,
since that has to reach past midnight. `fill_weather_args` only ever **widens** —
a model that asked for 24 hours knows more than the regex does. Plain daily
asks pay nothing, which is pinned, because hourly roughly doubles the response.

**`test_no_personal_data` caught this work twice, and both catches were
right.** First a US state other than the declared fixture (the second
Springfield), then the operator's own **country name**, spelled out in a
docstring — 13 characters that are a field in their profile, and which this
paragraph therefore also cannot write. Note for anyone writing weather fixtures:
use the fixture place, keep coordinates to one decimal unless they are the
sanctioned pair, and reach for a foreign city when a case needs somewhere to be
wrong about. Also worth knowing: `_readable_tracked()` only scans **tracked**
files, so a new test file looks clean until it is staged. Run the guard after
`git add`, not before.

The general lesson matches the one at the top of Phase 4: check whether the
guard exists before assuming the behaviour is unguarded, and check whether it
*injects* or only *asks*. A nudge-only guard against a 9B is a suggestion.

### One thing the board gained

`Scenario.forbid_tools` — the board had no way to say "and it did not
wander to scrape". Every assertion was positive, which is half the reason
a scenario could hand over the right call and assert only that the right
call happened. An inverted scenario needs both halves: the redirect
landed, *and* the thing it redirected away from never ran.

---

## Phase 1 — close the in-flight PDF lane

Eight days of uncommitted work that reads handwritten and scanned PDFs.
The feature works and its 62 tests pass. It has four loose ends and
cannot ship as-is.

- [ ] **1.1** Declare `pypdfium2` in `pyproject.toml` core dependencies.
  `pdf_pages.raster_pages()` (`tools/pdf_pages.py:160-164`) imports it,
  catches `ImportError`, and returns `[]`. On the shipped installer that
  means a scanned PDF with no embedded JPEGs reads as **nothing at all,
  silently** — the exact failure class commit `e5b0f2f` was written to
  kill.
- [ ] **1.2** Regenerate `win-installer/requirements-win-amd64-cp314.txt`
  via `win-installer/lock.py` so the hash-pinned installer actually
  carries it. CI's `lock` job will fail until this is done, which is the
  system working.
- [ ] **1.3** Make the missing-rasterizer case loud. `raster_pages` should
  distinguish "no pages needed rendering" from "I cannot render," and
  `doc_extract` should surface the second as an actionable message.
- [ ] **1.4** Pick one of the two ink designs and delete the other. The
  production path is `doc_extract` → ink listing → `turn_round.py:393`
  `ink_vision_walk` → `vision` walks pages one at a time. The other path
  reads pages *inside* the tool via
  `DocExtractTool(look_pages=…, ocr_inspect=…, page_dir=…)`, and only
  tests ever inject it — `build_tool_registry` never does, and the
  registry carries a comment at `tools/__init__.py:340-343` explaining why
  the in-tool look was rejected. Keep the walk; drop the injection
  parameters and `_look_if_ink`.
- [ ] **1.5** Delete `arelis/tools/pdf_look.py`. Nothing imports
  `look_page_images`. It was superseded by `vision._look_pages`.
  **Re-confirmed 2026-09-17:** it is the last module the "no test file names
  this" query returns, and a grep for both the module and the function finds
  only this line. Left in place because deleting needs your say-so. Worth
  reading before it goes, as a record of how prose rots: the docstring says
  *"a few VL batches. One extract, not 17 looks"* while `_CHAT_BATCH = 1`
  three lines below makes a 17-page PDF exactly 17 looks. The comment next to
  the constant explains why (a 5-page batch hung the 9B); the docstring above
  it was never updated. Same shape as every claim the sweep found — true when
  written, false after the fix, and nothing failed when it stopped being true.
- [ ] **1.6** Delete `ink_vision_calls` from `tools/pdf_pages.py:90-116`.
  Also dead — `ink_vision_walk` is what `turn_round` calls.
- [ ] **1.7** Get `.tmp_pdfium/` and `physhw/` out of the working tree.
  Move one small ink PDF into `tests/fixtures/` as a real fixture so the
  lane has a committed reproduction.
- [ ] **1.8** Add a test for the **raster** path. Today's suite covers
  embedded-image PDFs, because `build_jpeg_page_pdf_bytes`
  (`pdf_pages.py:214`) constructs exactly that shape. The pypdfium2 branch
  — the one that was silently broken — has no coverage.
- [ ] **1.9** Update `docs/whats-new.md` and the `doc_extract` row in
  `docs/architecture.md`.
- [ ] **1.10** Commit.

---

## Phase 2 — the schema experiment ~~(run it)~~ CANCELLED

> **Closed 2026-09-17. The experiment ran and the answer was no.**
>
> With guard rails on, the unstripped schema is worth **+1.0 out of 42**
> against a **±2** noise band, at **2.4× the prefill**. See "The verdict"
> at the top of this file for the full table. The hypothesis below was
> reasonable and it was wrong; keeping it is cheaper than pretending the
> roadmap was right the first time.
>
> **What to do instead:** the two surgical edits the per-case analysis
> justifies, then the guard-rail hole sweep.
>
> - `weather` and `send_sms` are the only two tools whose real description
>   reliably changes the pick (missed 7/13 and 4/13, in `skinny` arms
>   only). Their `_SHORT_DESC` lines now carry the one sentence each was
>   dropping — "defaults to the user's own place" and "do not look up
>   contacts first". Hundreds of tokens, not eleven thousand.
> - Everything else in this phase is superseded by the hole sweep. Guards
>   are worth +6.0; they just have gaps, and
>   `scripts/measure_tool_choice.py` plus `scripts/analyze_tool_choice.py`
>   are how you find them.
>
> **Read the per-case output, not the score.** Re-seeding one arm moved it
> by two picks, which is the entire size of the effect this phase was
> built to chase. `analyze_tool_choice.py` sorts by how many runs a case
> fails and that is the number worth acting on — with one caveat it
> learned the hard way: score *families*, not cases. Six workspace
> introspection asks each failing 50-70% read as noise individually and
> are obviously one defect together.

The original hypothesis follows.

Do not skip to Phase 3. This measurement decides how much of Phase 3
there is.

The original subsetting measurement asked "does a tools array that
*changes shape* per turn cost more?" and correctly answered yes. It never
asked "how big can a *constant* array be before the seed hurts?" A
constant prefix is prefilled once at startup by `seed_prefix_cache`
(`llm/startup.py:260-294`) and reused every turn after. Growing it should
cost startup seconds, not per-turn seconds.

If that holds, real tool descriptions are nearly free, and a large share
of the 12,700-line heuristic layer becomes deletable.

> **Reframed 2026-09-17, and this is the cheapest finding in the audit.**
> `scripts/measure_tool_schema.py` reports **253 of 253 parameters
> documented in the source schemas, and 0 reaching the model** (43 tools /
> 280 parameters against a real profile; 38 / 253 under pytest's isolated
> data root — both deterministic).
>
> The descriptions are not missing. Somebody wrote every single one, and
> `compact_prompt.skinny_parameters` deletes all of them on the way out.
>
> That changes what Phase 2 costs. Steps 2.5 and 2.7 were scoped as a
> documentation project — write 280 descriptions across 41 tools, weeks of
> work before the first measurement. The real experiment is **an edit to
> one function**, then re-run the boards. Write-new-descriptions becomes a
> polish pass *after* the measurement says it is worth having, not a
> prerequisite to finding out.
>
> `tests/test_tool_schema_quality.py` pins both halves: the source
> descriptions still exist (so nobody deletes them as dead weight) and
> none of them currently reach the model (so the day that changes, the
> test says so). Run 2.1–2.4 first regardless — the decision gate is still
> the decision gate.

- [ ] **2.1** Extend `scripts/measure_tool_surface_prefill.py` with a
  third arm: constant full surface at 2×, 3×, and 4× the current schema
  size (pad with realistic descriptions). Report `prompt_eval_count` per
  turn for each.
- [ ] **2.2** Measure cold seed time for each size via
  `scripts/verify_prefix_warmup.py`. The number that matters is
  time-to-first-reply on a cold boot, currently ~0.9s after a ~14s seed.
- [ ] **2.3** Write the result into `docs/models.md` next to the existing
  table, whichever way it goes. If a 15k-token constant prefix costs 40s
  once at startup and 3s per turn, that is the answer and it should be
  written down so it is not re-litigated.
- [ ] **2.4** **Decision gate.** If per-turn prefill stays flat: proceed
  to 2.5. If it does not: skip to Phase 3 and treat the heuristic layer as
  permanent, cleaning it up rather than shrinking it.
- [ ] **2.5** **Stop stripping first.** Change
  `compact_prompt.skinny_parameters` to keep the descriptions that already
  exist, and re-measure. This is the whole experiment in one diff, and it
  needs no new prose written. Invert the last assertion in
  `tests/test_tool_schema_quality.py` and record the prefill cost next to
  it.
- [ ] **2.6** Re-run the Phase 0 boards, then the tool-choice board (42
  cases) — that is the metric this whole phase exists to move. Compare
  against the 0.9 baseline.
- [ ] **2.7** Only now, and only if 2.6 moved: improve the descriptions
  that exist, highest-traffic tools first — `workspace`, `web_search`,
  `scrape`, `weather`, `send_sms`, `send_email`, `agenda`, `vision`,
  `doc_extract`, `browser`. Give every `action` enum a one-line gloss.
  Note the shape of the problem from `measure_tool_schema.py`: `browser`
  carries 37 parameters and `image_edit` 22, so the top few tools are most
  of the surface.
- [ ] **2.8** Now start removing the prosthetic. For each regex family in
  `intent_catalog.py` and `claims.py`, disable it behind a config flag,
  run the boards, and delete it if the boards hold. Order by size:
  `claims.py` agenda/tasks/goals/git detectors first, since they duplicate
  `intent_catalog` patterns that `claims` could just call.
- [ ] **2.9** Shrink `COMPACT_TOOL_POLICY` (`compact_prompt.py:61-78`) as
  schema descriptions absorb its content. It currently re-states per-tool
  guidance the schema should carry.
- [ ] **2.10** Tighten `tests/test_tool_schema_quality.py` from Phase 0
  into a real floor.

---

## Phase 3 — cleanup and dedup

You asked for a dedicated cleanup phase. This is it. Every item is a
concrete, cited duplication or hazard, not a vibe.

**What this phase has actually been worth, so far.** Every item in 3a was
written up as tidying. Three of the four were, and each of the other two
was covering something that produces a wrong answer: 3.3 hid a silent
substitution of one image for another off Windows, and 3.14 hid raw JSON
becoming her voice in conversation history. The pattern is consistent
enough to state plainly — *duplication is where defects hide, because the
fix lands in one copy.* It is also worth noting the roadmap itself has
been wrong about the specifics four times now (4.5 on both halves, 3.1 on
the count, 3.3 on the premise, 3.4 on the shape). Verify before fixing.

### 3a — exact duplication

- [x] **3.1** ~~byte-identical in two files~~ — **four**:
  `orchestrator.py`, `orchestrator_turns.py`, `orchestrator_confirm.py`,
  `orchestrator_slash.py`. Only `orchestrator_turns` referenced any of
  them; the other three defined all four and used none. `TOOL_CMD` is the
  list of tools a typed slash command may run *without* a confirm card,
  and the long comment on why `send_email`/`send_sms` are absent sat next
  to three copies nobody read. Now `core/orchestrator_shared.py`.
- [x] **3.2** Not one constant — a four-constant block in the same four
  window mixins, and no two of them read the same member. Now
  `ui/window_const.py`.
- [x] **3.3** **Premise was wrong.** `attachments.py` and `look.py` have
  no path-mention regex; `look.py` already imports `path_from_text` from
  `image_refs`. Two modules, and the gap between them was a defect:
  `image_refs` had no POSIX-absolute branch, so off Windows a named
  `/tmp/x/arelis_1234.png` was not seen as a path at all and the caller
  fell through to "newest file in outputs/images" — she looked at a
  *different picture* than the one named, silently. Both also matched
  inside URLs (`https://…/documents/report.pdf` → local
  `documents/report.pdf`; the image one started its match at the `s` in
  `https`). Shared fragments now in `core/path_refs.py`.
- [x] **3.4** Two phases, not one function twice — which is *why* the
  drift was invisible. In `turn_prepare` the halves sit 130 lines apart
  because everything between them decides `loop._expected_tools`. The
  escalate copy never passed `extra_skill_ids`, so a room's skills were
  in reach on round one and gone on round two. Latent, not live:
  `filter_tool_names` ignores that argument unless a subset flag is on
  and both ship off — but load-bearing in 64 of 192 probed combinations
  once one is. Now `core/tool_surface.py`.

### 3b — the three `*_complete` modules

3,935 lines across `sms_complete.py`, `email_complete.py`,
`agenda_complete.py`. Literal shared code is tiny (~2%); **structural**
duplication is near-total — every one has a draft dataclass, a parse
function, a history-merge, an args-lock, a preflight nudge, and a force
notice, in that order.

Do **not** merge the parsers. The 84 compiled regexes are STT-mishear
scars and they are domain-specific on purpose.

**This was the worst lane in the audit.** Three bugs, two of them in code
that sends email to a named human. The structural-duplication read above
was right, and the reason it mattered is that the three modules were each
expressing the same rule *differently*, so the odd one out was the bug.

- [x] **3.5** ~~~48 guards~~ — **18**. But the dependency was exactly as
  described, and it was the real complaint: `is_tiny_prompt_ask`, which
  runs every turn to decide a turn needs *no tools*, imported the SMS
  draft reconstructor to recognise "hey". 17 generic guards plus
  `soften_caps` are now `core/utterance_guards.py`; `sms_complete` went
  1,154 → 970 lines and re-exports every moved name, because thirteen
  other modules import them through it.
- [x] **3.6** **Wrong about `_PROCEED_ASK`** — it is in SMS and agenda,
  and email had no such pattern at all. The drift in `_SEND_CONFIRM` was
  **one comma**: email allowed `(?:\s+please)?` where the others allowed
  `(?:\s*,?\s*please)?`, so *"yes, please" confirmed a text and a calendar
  event and did nothing to an email.* No error, nothing in the log, the
  user just says it and waits. Extracting it also surfaced that the
  pattern was doing two jobs — a content-free "yes" (which could be
  answering anything, or be Whisper noise) and "send the text" (which
  names the act) — and all three had a different idea of whether those
  need a preceding offer. They are built separately now and combined at
  the call sites. Verified with a 53-utterance corpus diff: 4 rows
  changed, all intended, 49 byte-identical.
- [x] **3.7** **Claim wrong, and the difference *was* the bug.** Not "80
  lines three times": agenda's walk was 18 lines, email's was split across
  helpers using another mechanism, SMS's was ~105 across three walks. What
  each was trying to express was one rule — has the user moved on? — and
  they disagreed. **Email had no stop condition at all.** A stray "yes"
  five unrelated exchanges after a draft returned it complete, addressed,
  body intact, to the force gate, and the Allow card described it
  perfectly correctly, because the address and body genuinely are the ones
  the user dictated — just not now. "Never mind, what's the weather" did
  not stop it. Only the shared stop condition moved, into
  `core/history_revival.py`; SMS's richer walk stays hand-written with a
  comment saying why, because flattening its two extra exits meant four
  callbacks and a sentinel in the function that decides what text messages
  get sent.
- [x] **3.8** **Path wrong** (`arelis/tools/contacts.py` does not exist),
  **substance worse than stated.** Spoken "Sam Brightley" reached email as
  `brightley@example.com`; spoken "Sam **Brightly**" reached it as
  `owner@example.com` — the user's own inbox. One letter. SMS had two
  guards email lacked: a two-edit last-name tolerance, and a refusal to
  let a multi-token name degrade into a bare first-name match. Email had
  neither, so the typo missed every exact tier, became "sam", and matched
  the owner's own card. Nothing failed, because `EmailDraft.complete` only
  asks whether *an* address came back. Verified independently against
  `HEAD` before accepting the fix. Now `core/contact_match.find_contact`,
  shared. A third thing fell out: `resolve_sms_alias` carried a comment
  promising it prefers a real contact over the owner's card and **it did
  not** — `match_contact_label` matched on substring and returned `me`
  first, so the code implementing the promise was unreachable. "Text Sam"
  texted you.
- [x] **3.9** Claim accurate, and agenda's zero coverage is exactly where
  the defects were. Seven, including: the history revival **had never run
  in a live session** (it did not slice off the current turn, so it broke
  on iteration one, every time); "Dentist tomorrow" reached the tool as
  the literal string `tomorrow` and was rejected; and
  `draft_agenda_delete_args` stamped today's date on "delete the standup
  tomorrow at 9am", which for a recurring event **deletes the wrong
  instance**. 45 tests, 17 mutants, 17 caught.

**Carried forward from this lane.** `contacts.match_contact_label` is too
loose for spoken names — `cand in name` means a one-letter query matches
anyone whose name contains that letter. It was written for Google Messages
notification titles, where that is correct. Pinned as-found in a test that
explains it, rather than changed out of lane.

### 3c — silent failure surface

460 bare `except Exception:` and 222 `except: pass` across `arelis/`.
Not all are wrong — fail-soft is often correct in a desktop app. These
specific ones can produce a wrong answer rather than an error:

**Two of the four named items were already fixed.** Worth stating, because
the count at the top of this section (460 + 222) is what made the lane look
alarming, and a raw count of `except Exception` is not a defect count. The
ones that were real were real, and they were the quiet ones.

- [x] **3.10** **Half wrong.** The *probe* failure at `router.py:314-318`
  already logged at `warning`. The **import** guard one line above did
  not, so if `arelis.llm.vram` failed to load — the exact case where the
  guard is most likely broken — the host VRAM guard vanished with no
  trace and heavy loads proceeded onto a full card. Now warns.
- [x] **3.11** Confirmed. `capabilities()` fell back to `log.info`, which
  is below the default level, so a vision-capable chat model got treated
  as blind and paid a VL detour with nothing in the log saying why. Now
  warns, and says that vision support is *unknown* rather than absent.
- [x] **3.12** **Wrong.** Every embed batch failure already calls
  `log.exception` — traceback and all — and the rows are not marked, so
  the next flush retries them. This is fail-soft working as designed.
  No change.
- [x] **3.13** Confirmed. A malformed `lessons.yaml` became `{}` in
  silence, so hand-edited lessons vanished and the only symptom was the
  model behaving like the edit never happened. Now warns with the path
  and says built-in lessons are being used.
- [x] **3.14** Confirmed, and it is the *default* path rather than an
  edge: `chat_followup_from_tool` special-cases seven tools and ends in
  `return cleaned`, so 36 of the ~43 registered tools paste verbatim and
  anything new joins them by accident. The harm is downstream —
  `_finish` writes that text to memory as an assistant turn, so the model
  reads its own pasted JSON back as an example of how she writes.
  `tool_passthrough_note` marks the memory turn (bubble unchanged);
  `_is_json_body` stops an API body becoming the answer, which `web_fetch`
  needed after it grew POST/PUT/PATCH/DELETE — a probe put
  `{"access_token": "sk-live-…"}` in the bubble verbatim. Five mutants
  run; **two survived the first draft of the tests** (the helper was
  covered, both layers of wiring were not), so the file now drives the
  real `_finish` and a whole empty-after-tool turn.
- [x] **3.15** ~~460 bare `except Exception:` and 222 `except: pass`~~ —
  **679 broad handlers and not one bare `except:`** in the whole package.
  The convention shipped as stated, with two additions the measurement
  forced. `log.info` cannot satisfy it, because 3.11 is precisely the bug
  where a fallback logged below the default level and stayed invisible for
  months. And a handler that *surfaces* the bound exception — into a return
  value, an event, the UI — already tells someone, so it passes without a
  comment; requiring one there would have meant 100 comments saying "this
  returns the error".

  **400 handlers still fail the rule**, so `tests/test_broad_except.py` is a
  ratchet over a per-file baseline rather than a sweep. Per-file *counts*,
  not line numbers: a line-keyed baseline goes stale on any edit above the
  handler and trains people to regenerate it without reading it. Two thirds
  of the baseline is `ui/` and `earth/`, which are frozen, so this asks
  nobody to go clean them.

  The third test hands the detector nine hand-written snippets, for the
  same reason the mypy gate does: a checker whose normal state is "pass"
  cannot tell you it has gone blind. Five mutants — a new silent handler in
  a real module, an inflated baseline, a blinded comment check, `log.info`
  accepted, and bare `except:` dropped from the broad set — all caught. The
  stale-baseline test turned out to be the canary for the other two: a
  detector that breaks blind finds *fewer* sites than the baseline allows,
  which reads as a clean tree to the new-violations test and as a loud
  failure here.

### 3d — god functions

Done. The roadmap's line numbers were stale again: `prepare_turn` was
529 lines starting at 72, not ~580 starting at 76. The rest of the
claims held in spirit and were wrong in the details that matter.

- [x] **3.16 / 3.17** `SimpleNamespace` is now `RoundScratch` in
  `turn_scratch.py` (`slots=True`, keyword-only). A misspelled field
  raises instead of becoming a silently dropped write — that is the
  whole reason it is a dataclass. `apply_no_call_path` and
  `dispatch_calls` write through the object; the 39-line copy-back
  `finally` is gone from both coordinators.

  A leftover hole survived the first pass: `run_round` still snapshotted
  the surface into locals and wrote *those* back in its own `finally`.
  `_drop_wander` lands on the scratch. If the tool then explodes,
  `dispatch_calls` never returns, and the snapshot from the start of
  the round put `web_search` back on `ctx`. The explode-on-`r` test
  did not catch it — it never went through `run_round`. Write-back now
  reads `r` when it exists. Mutating that to ignore `r` fails both the
  raise-path test and the happy-path "next round sees the narrow
  surface" test.

  `role` and `model` were on the SimpleNamespace and no step ever read
  either. They stay locals on `run_round`.

  The roadmap's `finally` description was incomplete: both coordinators
  also had four hand-maintained mid-body flush/re-read lists, so six
  field lists per pipeline had to stay in step. They were in sync at
  HEAD — no live bug — but adding one local a callee reads and
  forgetting the flush was silent. Writing through `r` deletes that
  class of defect. Two test holes in the first pass (fanout
  `fill_round_calls`, execute-path JS-shell widen) were the same
  helper-not-caller miss as 3.14.

  `execute_call` still annotated `r: SimpleNamespace` after the
  rewrite, which is a live `arg-type` at the dispatch call site.
  `no_call_steps` / `no_call_finish` / `call_redirects` annotated
  `r: Any`, so `slots=True` bought them nothing. All four now take
  `RoundScratch`.
- [x] **3.18** `prepare_turn` is 224 lines, split around the real
  prompt seams into `prompt_sections.py`. Five cases — plain,
  rich-spoken, weather, current-web, SMS — are byte-identical to
  `HEAD`, independently re-captured by stubbing at both ends of every
  `from x import y` (the lane's own probe stubbed only
  `prompt_sections`, a module HEAD does not have, so it could not have
  produced a "before"). The first draft of that check baked a live
  wall clock into the capture and agreed only because both runs landed
  in the same minute. `tests/test_prompt_golden.py` is the permanent
  form: a stub that does not bind fails `test_every_stub_took` rather
  than going green until tomorrow morning, and a one-line reorder of
  PROFILE/CONTACTS fails the golden.

  An existing fail-open was left alone during the split because byte
  identity was mandatory, then made audible: a room whose `tools:`
  names nothing installed still gets the full registry (rooms lean
  rather than cage — `rooms.py` argues the point), but it now logs a
  warning instead of printing "limited to tools: …" and then offering
  everything. `cap_to_room` in `tool_surface.py`. Three mutants: silent
  fail-open, silent partial typo, cage never narrows — all caught.
- [x] **3.19** `_construct_shell` is seven named phases with
  `assert hasattr(...)` guards naming what each one reads. The lane's
  original test was four `hasattr` checks after a construction that
  would already have crashed, plus an unused import, and it did not
  pass ruff. Rewritten: every edge in the dependency table is
  parametrized, skip the needed phase, construction dies. Four
  mutations — docks before instruments, instruments before the chat
  stage, signals before secondary windows, timers dropped — each fail
  two tests and leave the rest green. Nothing in this repo launches
  with `-O`, and `assert` is already used in shipped code
  (`browser/actions.py` has 21), so the guards are not decoration.

### 3e — types

~~1,391~~ **1,550** mypy errors across `arelis/`, advisory in CI.
`arelis/guard/` is already clean, and `NOTES.md:30-31` has the order.

- [x] **3.20** Done for `arelis/guard/`, `arelis/memory/`, and
  `arelis/llm/` — 19 files. The mechanism matters more
  than the package: the gated list is one path per line in
  `tests/mypy_strict_packages.txt`, read by both a blocking CI step and
  `tests/test_mypy_gate.py`, so adding a package gates it in CI and
  locally in the same one-line change. Removing `continue-on-error` from
  the `types` job was required — it would have swallowed the new step —
  which means the two mypy steps now have *opposite* error handling, and
  `test_ci_gate.py` pins that so neither can drift into the other's job.
  Proven by injecting a return-type error into `arelis/guard/watch.py` and
  again into `arelis/memory/indexer.py`: exit 1 both times. The local test
  also hands mypy a file it knows is wrong, because a gate is only ever
  observed passing otherwise — a permissive flag or config key would leave
  it green on broken code, and that mutant is run.
- [x] **3.21** `arelis/tools/base.py` is at **0**. The one error was
  the method named `list` shadowing the builtin, so every `list[...]`
  annotation in the class was "not valid as a type". `builtins.list`
  on those three annotations. Re-measured before touching it: presence
  is still 15, eval still 19, `arelis/tools` as a package is 136 —
  do not gate the package.
- [x] **3.22** `arelis/tools/base.py` is on the blocking list. Next
  cheap packages are still `presence` (15) and `eval` (19). Never
  attempt the 689-error `arelis/ui` pile as one task. Five of the
  presence errors are the same `list`-method shadow as base.py.

---

## Phase 4 — tool depth

Pain #2: "she can start a task but not finish it." Ordered by how often
you would hit it.

### Landed 2026-09-17 — the first five verbs

A pattern showed up on all five and is worth stating before the list: in
every case **the safety plumbing was already written for a verb that never
arrived.** `WORKSPACE_WRITE_ACTIONS` and `DELETE_ACTIONS["workspace"]` have
carried `delete`/`remove` since they were written. `save_job_from_payload`
already create-or-replaces and is what the calendar jobs tab calls. The
store has had `list_facts` / `list_preferences` / `list_episodes` all along.
Somebody built the gate and the door was never cut. When picking the next
item off this list, check the policy table and the store first — the work is
often smaller than the entry implies.

| gap | verb | commit |
| --- | --- | --- |
| `memory` was write-only — nothing could answer *"what do you remember about me?"* | `list` | `00c9722` |
| `tasks` had no edit; fixing a typo meant `remove`+`add`, losing the id and goal link | `update` | `00c9722` |
| `workspace` could not rearrange files (**4.1**) | `delete` `move` `rename` `copy` | `9084748` |
| `schedule` could not be rescheduled; moving a time meant delete+recreate, losing `last_run` | `update` | `f4fbb53` |
| `git_info` was read-only (**4.3**) | `stage` `commit` | `4043bcf` |
| `inbox` named attachments and threw the bytes away, so any attachment task stopped a step short | `download` | `aa5029d` |
| `clipboard` was advertised as read/write and had no action at all (**4.4**) | `write` | `e866aff` |
| `plot` could not draw a formula — only a table or numbers typed out by hand | `expr` `xmin` `xmax` | `7a9ac10` |
| `workspace` had no recursive search, so a tree walk was the only route — and `same_call` blocks that (**4.2**) | `grep` `find` | `91386bf` |
| `weather` never said *which* place it forecast, and had no time of day and no past | resolved label, `hours`, `past_days` | `6c24b42` `6a9898b` |

Three of these were watched failing under **mutation**, not just watched
passing:

- Swapping `resolve(for_write=True)` for `resolve_read` in the workspace
  delete makes her delete a file outside the roots that was only granted
  for *reading*. `test_a_read_grant_is_not_a_licence_to_delete` catches it.
- Adding `push` and `reset` to `git_info._WRITE_ACTIONS` turns
  `test_the_dangerous_verbs_stay_refused` red on exactly those two.
- Dropping the sanitising lines from `inbox.safe_attachment_name` turns 11
  tests red, including the one asserting nothing landed outside the data
  root.

`inbox download` is worth a note because the download was the easy half. The
filename is chosen by whoever sent the mail and arrives before anyone has
decided to trust them, and `filename="../../../../.ssh/authorized_keys"` is a
valid header — so it is treated as hostile text and never as a path. It is
also gated `WRITE_LOCAL` rather than `WRITE_EXTERNAL`: it writes a file so it
wants Allow, but it touches nothing on the server (BODY.PEEK, readonly select,
so fetching a file still does not mark the mail read) and an unattended job
must be able to save today's invoice. Three failure modes that would otherwise
have reported success are also covered: two parts declaring the same filename
no longer overwrite each other, a message with no attachments refuses instead
of returning a cheerful empty download, and the size limit is checked across
every part before anything is written so an oversized file cannot leave half a
download behind.

`git_info` is deliberately **stage + commit and nothing further** — that is
the finished scope, not a first increment. Those two are additive and
recoverable; push, reset, clean, checkout, rebase and history rewrite cannot
be walked back from inside a chat turn. 4.3's "branch, stash, blame, show"
are still open, but the *write* half of it is closed as narrowly as it will
get.

Each new verb also joined the tool-choice corpus, so the path is measured
rather than assumed.

- [x] **4.0** A recall ask that the model answers with a web search ended
  in a refusal instead of a recall. **Done `cc2d528`.** Both documented
  near-misses were avoided: the fix went into `no_call_steps` beside the
  goals and tasks injects, not into `redirect_local_store` (which never
  sees the call) and not through `local_store_inject_args` (no `recall`
  branch, wrong shape). The new part is `recall_query`, which strips the
  trigger phrase, the addressee, the article and the time reference so the
  tool gets `"Sherpa work"` rather than the whole sentence — searching for
  `"what did i say about"` ranks nothing. An empty result is meaningful and
  skips the inject: `"do you remember?"` names nothing to look for, and a
  blank query is a tool error. `recall_force_call` is now measured, caught
  by `recall_ask_does_not_end_in_a_shrug`.

  The companion gap is closed too, in `eba6593`. `"What do I have to do
  today?"` matched **no** rule anywhere — `detect_intents` returned `[]`
  *and* `looks_like_tasks_utterance` was False — because `_TASKS_UTTERANCE`
  requires the literal token "task", "todo" or "checklist", and "what do I
  have **to do** today" is two words. Every phrasing a person actually uses
  fell through a regex written for the phrasings a developer types; same
  for "what do I need to do today", "anything I need to do today", "what's
  on my plate". Fixed as a separate start-anchored pattern rather than by
  widening the existing alternation, because that regex lives in
  `sms_complete` to tell a to-do ask from an SMS body, and "text my wife
  and tell her I have to do the shopping today" carries the same words
  mid-sentence. Still deliberately unmatched: `"what's going on today?"`,
  where the corpus accepts agenda, inbox or tasks — that is a fair
  description of the ambiguity, so forcing one would be guessing.
- [x] **4.1** `workspace` has **no delete, rename, or move**
  (`tools/code_workspace.py:35`) even though `tools/policy.py:45,127`
  already defines the confirm rules for delete. Finish the CRUD.
  **Done `9084748`.** No recursive delete — a non-empty directory is
  refused and says why. Emptying a tree is the one mistake with no undo,
  so the model does not get a verb for it.
- [x] **4.2** `workspace` had no recursive search. "Find where X is
  defined" was impossible without listing every folder, which the same-call
  guard then blocks. **Done `91386bf`: `grep` (contents, returns
  `path:line`) and `find` (names).** Worth keeping the framing from the
  original entry, because it generalises: `same_call` was *correctly*
  blocking a tree walk that looked like a stuck loop, so the guard layer was
  fighting a missing capability rather than a misbehaving model. Where a
  guard and a gap disagree, check whether the capability exists before
  loosening the guard. Both guards here were watched failing under
  mutation — `resolve_read` containment (a plain path join let `path="../.."`
  read outside the roots) and the `os.walk` prune (without it `node_modules`
  lands next to the real answer). Follow-on now unlocked:
  `inspect_read_path` falls back to `docs/architecture.md` for an unmapped
  source ask, and could grep instead.
- [~] **4.3** `git_info` is read-only (`status`/`diff`/`log`). No commit,
  branch, stash, blame, or show. Add writes behind the confirm card.
  **Writes done `4043bcf`: `stage` + `commit`, and that is the final
  scope.** `branch` / `stash` / `blame` / `show` are still open, and are
  reads — take them when something needs them. Do not widen
  `_WRITE_ACTIONS`; a test fails on purpose if you do.
- [x] **4.4** `clipboard` was **read-only** while `compact_prompt.py:21`
  told the model it could "read / write" — a routing bug by construction.
  **Done `e866aff`, by implementing the write rather than retracting the
  claim,** because the hard part was already there:
  `_write_windows_clipboard` had been in the module the whole time under a
  docstring reading *"used by tests and the live pass, not a tool action"*.
  The most literal instance yet of the pattern at the top of this section.
  Two things it had to get right. A write calls `EmptyClipboard`, so it
  destroys what was copied — it stays behind Allow like the read, but for a
  different reason (reading is a privacy question, writing is a loss
  question), and an empty `text` is refused rather than executed. And the
  Allow card now names the right action: it read *"read the clipboard"* for
  both, which asks for the wrong consent and understates the cost.
- [x] **4.5** `calculator` takes one expression with no variables and no
  units (`tools/calculator.py:66-67`). Give it a variable scratchpad.
  **Done `6ee6e22` / `b371959`, and both halves of the original note turned
  out to be wrong.** Variables are the `python` tool's job and the
  description already said so; adding them here would be a third evaluator
  to keep safe. Units already have a tool — `tools/units.py`, pint-backed —
  so the gap was that `5 miles in km` said "invalid syntax" instead of
  naming it. What the line missed is that the tool was **wrong about
  arithmetic**, which is the one thing it exists for. See the section below.
- [~] **4.6** `plot` does line, scatter, residuals only. Add histogram,
  bar, and subplots — the three a homework or data question actually asks
  for. **A worse gap was found first and closed in `7a9ac10`:** there was
  no way to plot a *formula* at all, only a table or numbers the model
  typed out by hand, so `sin(x)` was unreachable. `expr` + `xmin` / `xmax`
  now covers it, reusing `cas.parse_cas_expr` for the parse — see the
  ForceGate sweep section for why bare `sympify` would have been RCE.
  Histogram / bar / subplots are still open. Note when taking them that
  `7a9ac10` added the **first** test that runs `plot.run` at all.
- [x] **4.7** `web_fetch` is GET-only with no headers, no POST, no auth
  (`tools/web.py:28-32`). Any real API integration is impossible.
  **Done `5244834`.** `method`, `headers` and `body`, with the gate wired
  before the capability: a non-GET is `action_is_write` and answers to the
  same confirm toggle as a file write, and `DELETE` is `action_is_destructive`
  so it still pauses on the filament face where a spoken ask is otherwise the
  grant. Three things had to be right beyond "it sends a POST" — see below.
- [x] **4.8** `analyze` does summary/head/describe. No filtering, no
  grouping, no joins. Add a query action. **Done `fbb7bd6`,** with a
  hand-written condition parser rather than `DataFrame.query()`.
- [ ] **4.9** `inbox` cannot compose or draft. `send_email` is one-shot.
  Add a draft action so a reply can be reviewed before the Allow card.
- [ ] **4.10** `tasks` and `goals` have no priority, recurrence, or
  subtasks.
- [ ] **4.11** `doc_extract` handles PDF only — no DOCX, no PPTX, no PDF
  form fields, no table structure.
- [ ] **4.12** `diagnostics` runs the entire pytest suite or nothing. Add
  a target argument.
- [ ] **4.13** `recall` cannot trigger a reindex, and the indexer only
  runs between turns. Expose an index action so "I just added 40 PDFs"
  has an answer.

### The tools no test file named — 2026-09-17

Cheapest audit query of the day: for each module in `arelis/tools/`, ask
whether any file under `tests/` so much as mentions its name. Three came
back — `html_text`, `image_io`, and `python_exec`.

`python_exec` is the tool that **executes code the model writes**, and it
had no tests at all. It was not unguarded: an AST whitelist, an import
allowlist, a forbidden-call list, a locked `__builtins__`, a documented
10s timeout. None of it had ever been run against an attacker. Four
defects, found by probing rather than reading:

| defect | what it was |
| --- | --- |
| `sympy.sympify` | `eval` with a friendlier name. Asking it for `__import__('os').name` returned the platform string — arbitrary import, one step from running a command. Invisible to the AST gate because the payload is a *string constant* and the gate reads `Attribute` and `Name` nodes. |
| `operator.attrgetter` | Same blind spot. A dunder spelled inside a string walked past the underscore rule. |
| `numpy.savetxt` | Wrote a real file to the repo root, with the docstring promising "files stay out". |
| the timeout | **Never worked.** The pool sat in a `with`, so `__exit__` called `shutdown(wait=True)` and joined the runaway thread forever. `while True: pass` hung the assistant permanently while the description advertised "Timeout 10s". |

The last one is the important one for daily use. The others are a
security story; that one is the user's own worst pain, shipped.

**The denylist lesson, learned twice in one afternoon.** The first fix
added a denylist of attribute names meaning "evaluate this" or "touch the
disk". It had `savetxt` and `save` on it. `scipy.io.savemat`,
`scipy.io.wavfile.write` and `from scipy.io import savemat` all still
wrote real artifacts. Fix those three names and the next library brings
its own — a denylist of names is permanently one import behind.

So the promise is now kept by `sys.addaudithook`, which fires on the
**operation** — the `open`, the `Popen`, the `connect` — whatever function
was spelled to reach it. Verified against `scipy.io.hb_write`, a write
path deliberately left off the name list: refused at `open(..., 'w')`,
nothing written. Turning the entire name denylist off leaves every write
test passing on the hook alone.

Two things worth remembering about that hook:

- It is process-wide and **cannot be uninstalled**, so it reads
  thread-local state and returns immediately on every thread that is not
  running a cell. Full suite passes with it installed.
- `os.putenv` was on the blocked list for exactly one probe run.
  `import scipy.sparse` sets environment variables while loading, so the
  cell was refused before it ran a line of its own. A false positive in a
  permanent hook is expensive; the list is now operations with no honest
  use, not operations that merely sound alarming.

One asymmetry is left, named in a test rather than implied: writes are
structural, reads are not. Blocking read-mode `open` would stop the import
machinery, and a cell that cannot `import sympy` is not a tool.

`image_io` came out clean — `resolve_image` already refused an absolute
path outside the roots, a climb out of the workspace, and a climb out of
the data root. Pinned anyway, because crossing that boundary is silent: it
does not raise in anyone's face, it reads a file and hands it to a model.

### The claim sweep — 2026-09-17

The pattern behind all of the above is general enough to be worth its own
pass: **prose states a protection the code does not implement.** Not lies
— intentions that drifted, or were true of one path. Every tool's
docstring, class `description`, and inline comments were re-read against
the code that implements them.

Four more, all verified by probe or measurement before being believed:

| where | claim | reality |
| --- | --- | --- |
| `cas.py:5` | "runs the named action under a timeout" | Three actions of twelve. |
| `safety.py:10` | "redaction runs on every tool output before it reaches the model, the UI, or a confirm card" | Two of those three were false. |
| `python_exec.py:5` | "files stay out" | `scipy.io` wrote three files. |
| `clipboard.py` | "Always asks for Allow first" | Not on the voice face. |

**The CAS one is a hang, and it is the worst of them.** `integrate`,
`dsolve` and `sum` got a killable child process. `solve`, `diff`,
`simplify`, `factor`, `expand`, `limit`, `series`, `gradient` and
`directional` ran unbounded on the calling thread. Measured on this
machine, each of these was still running after twenty seconds:

    solve(x**40 - x**17 + 3*x**5 - 1, x)
    simplify(sum(sin(x**k)/cos(x**(k+1)) for k in 1..13))
    series(exp(sin(tan(x))), x, 0, 40)

None is an exotic input for someone doing physics homework — and there is
a `physhw/` folder in this repo. The glass stops answering and Stop does
nothing. Reverting the fix hangs *pytest itself*, which is how the test
was confirmed to catch it rather than merely accompany it.

The fix had to not cost latency, because avoiding a 2s process spawn on
every quadratic is the entire reason those actions stay in-process. Hence
a **call-only** tracer: returning `None` from the trace function disables
per-line tracing, where the expense lives, and SymPy is call-heavy enough
that the deadline still lands. Benchmarked before it was written —
`diff`, `solve` on a quadratic and a small `simplify` were all at or under
their untraced times — and a test pins that bargain so a later change
cannot quietly trade the hang back for a tax.

**The redaction one is a leak by the one route nobody reads.**
`turn_execute` calls `ledger.record_tool` with the raw `result.output`,
about sixty lines before it computes `redact_secrets` for the model.
Warrant spans are not a dead end: `quote_lines()` feeds them back into the
conversation on the quote-first nudge. So a credential printed by a tool
reached model context by the single path that skipped the scrubber.
Separately, `TOOL_RESULT` published a redacted `output` beside a verbatim
`data`, and the python tool puts its whole cell output in `data["result"]`.

Both fixed at the boundary rather than the call site — inside `add()`,
which every warrant passes through, and by walking `data` before it is
published — so the tool added next month is covered without anyone
remembering this page.

**The clipboard one is the fix that was not a code change.** In voice /
filament mode `evaluate_confirm` pauses for `run_script` and destructive
actions only; a clipboard read is neither. That is deliberate on that face
— saying the ask is the grant — and `.cursor/rules` says `policy.py` stays
destructive-only on voice and must not be widened. So the wording moved,
not the gate. Worth recording as its own outcome: *the honest resolution
of a prose-vs-code gap is sometimes to fix the prose*, and deciding which
requires knowing whose lane the gate is in.

### SMS, the other pain reported by name — 2026-09-17

> "the SMS has had an issue with the mobile side because of our approach"

The approach: the phone is the radio, the PC is the brain. No Twilio, no
carrier gateway. Outbound is LAN HTTP to a companion app that calls
`SmsManager`. Inbound rides a **notification listener** on Google Messages
— which is the only path that sees RCS, and also the one that Doze, a muted
conversation, or battery optimisation can stop dead without surfacing an
error anywhere. On the companion path there is no PC-side fallback:
`supports_inbox_poll` returns `False` unless an SMSGate inbox URL is
configured as well.

That is a defensible architecture. The defect was what the assistant said
when it failed.

An empty ring buffer had two meanings — nobody texted, or we are deaf — and
`inbound_sms` answered both with *"No inbound texts recorded this session"*,
`ok=True`, `count: 0`. Asked "did Robin text back?", a model reads that as a
clean no and says so. **That is complaint #1 arriving inside the feature
named in complaint #4**, which is a decent explanation for why the whole
area has felt untrustworthy rather than merely flaky.

Nothing on the PC can prove the listener is alive — it only posts when a
message arrives. What can be proven is weaker and sufficient: whether the
phone has reached this machine *at all*. `CompanionPresence` records a
timestamp on any authenticated request, so every status poll, sync and
contacts push counts as evidence. A failed token deliberately does not:
anyone on the LAN can knock, and a stranger's knock is not the phone.

Three answers where there was one:

| state | answer |
| --- | --- |
| never heard from | `ok=False`, "I cannot tell", and the three real causes by name so the user has somewhere to go |
| heard from recently | an honest no — still carrying the muted/Doze caveat, because a phone answering polls proves nothing about the listener |
| heard from hours ago | says how long, and lets the user judge |

Texts already in the buffer always list, whatever presence says. The SMSGate
fallback never goes through the ingest handler, and a message that arrived
is its own proof.

**Still open on the mobile side**, from the companion audit and confirmed in
code — none fixable from Python, all needing a device or a gradle wrapper:

- [ ] `RadioService.startRadio` does `wifiIpv4(this) ?: return`. On
  cellular-only the radio silently never starts and outbound just times out.
- [ ] `MainActivity.onPause` stops the 3s poll, so a backgrounded phone
  never sees an Allow card until it is reopened.
- [ ] No `gradlew` in the tree, while the README documents
  `./gradlew :app:testDebugUnitTest`. No CI for the JVM tests, and no test
  at all for `RadioServer` or the notification listener — the two pieces
  that carry every message.
- [ ] `format_held_inbound_flush` has no call sites; `events.py` describes a
  batched chat note that nothing produces. Either wire it or delete it.

#### What generalises

- **"No test names this module" is a five-minute query and it found the
  worst defects of the day.** Coverage percentages would not have: every
  one of these files was *reachable* from other tests.
- **A guard that has never been attacked is a guard with unknown value.**
  Every check in `python_exec` looked right. Three were bypassable and one
  was inert.
- **A denylist of names cannot keep a promise about capabilities.** If the
  claim is "no files", the check must be on the file operation.
- **Prose ages worse than code**, because nothing fails when it stops
  being true. The claims above were all accurate when written.
- **Probe before believing, including your own sweep.** The subagent that
  found the `scipy.io` gap also reported items that turned out already
  fixed; every finding acted on here was reproduced by hand first.

---

## Phase 5 — the missing tools

Gaps, in the order that a local-first assistant actually feels them.

- [ ] **5.1** **Timers and reminders.** "Remind me in 20 minutes" has no
  home. `schedule` is Windows Task Scheduler plus email — far too heavy.
  Needs an in-process timer with an OS notification.
- [ ] **5.2** **Notes / journal.** `keep this:` writes a desk note with no
  tool behind it and no UI button. Make it a real tool with list and
  search.
- [ ] **5.3** **Local document search.** The embedding index exists
  (`memory/indexer.py`), `recall` queries it, but there is no way to say
  "search my PDFs" as a first-class act.
- [ ] **5.4** **Audio/video transcription.** Sherpa and Whisper are
  already installed for voice. Pointing them at a file is a thin wrapper
  and an obvious daily-driver win.
- [ ] **5.5** **Patch / diff apply.** `workspace edit` does old→new string
  replacement. A unified diff is how code changes actually arrive.
- [ ] **5.6** **SQL over local data.** `memory.db` and workspace CSVs are
  both queryable; nothing exposes that.
- [ ] **5.7** **Calendar find-time.** `agenda` reads and writes events but
  cannot answer "when am I free Thursday."
- [ ] **5.8** **PDF assembly** — merge, split, rotate, fill forms. The
  pdfium stack lands in Phase 1; this is the payoff.
- [ ] **5.9** **Shell.** Deliberately absent today
  (`tools/run_script.py:35`, `tools/desktop_tool.py:48`) and that is a
  defensible position. Revisit only with a hard allowlist, and only if you
  decide the daily-driver case outweighs the product case.

---

## Phase 6 — usability

Pain #3. Ordered by how fast a user hits it.

- [ ] **6.1** **No hung-turn timeout.** The 8s busy watchdog only arms
  after you press Stop (`ui/window_turn.py:207-208, 242-248`). A turn that
  hangs in a tool shows a shimmer forever. Add a ceiling with a visible
  countdown and an automatic unlock.
- [ ] **6.2** **Errors route to a closed dock.** Workspace open/save
  failures (`ui/workspace_host.py:178-188`) and the phone notify status go
  to the Thinking dock footer, which is closed by default. Failures belong
  where the user is looking.
- [ ] **6.3** **Tool discoverability.** 41 tools and no way to learn they
  exist except reading `docs/` or watching one fire. The orbit idle screen
  has three suggestion chips. Add a browsable capability list — this
  directly serves pain #1 too, because a user who knows `cas` exists will
  ask for it by name.
- [ ] **6.4** **Voice settings need a restart** and the notice is easy to
  miss (`ui/voice_host.py:27-55`). Either apply live or block the toggle
  with an explicit restart prompt.
- [ ] **6.5** **No conversation export.** Per-reply copy exists; whole
  transcript does not.
- [ ] **6.6** **History search is title-only** (`ui/panels/history.py:54-58`).
  Message bodies are already in FTS5 — wire the existing index to the
  existing search box.
- [ ] **6.7** **No undo** in the workspace editor.
- [ ] **6.8** **No in-app model picker** after the setup wizard.
- [ ] **6.9** **Accessibility**: no screen-reader labels, no high-contrast
  mode, no light theme, frameless chrome throughout. Scope this honestly
  before committing — it is bigger than it looks.

### Tool depth: 4.5, 4.7, 4.8 — 2026-09-17

Three roadmap lines about tools that could start a job and not finish it.
All three landed, and in all three cases the roadmap line was less
interesting than what was behind it.

**`analyze` could describe a table but not answer a question about one**
(`fbb7bd6`). `summary`, `head` and `describe` tell you the shape of a file.
"What did we spend in March?" left the model choosing between reading two
hundred rows out of `head` and adding them up in its own head, or guessing.
Neither is acceptable from a tool that exists so numbers are not invented.

`action=query` now does the four verbs a data question actually uses:
`where`, `group_by` + `agg` + `on`, `sort`/`desc`, `limit`.

The obvious implementation is `DataFrame.query()` and it is not used, for
the third repeat of the same lesson in one day. That method *evaluates* its
argument, and `@name` resolves against the calling frame. Probed rather than
assumed, and both of these ran:

- `@df.to_csv(path)` — wrote a real file, then raised on the mask, so the
  write had already happened.
- `@asyncio.base_events.os.system(...)` — executed a shell command.
  `asyncio` is a module global in `analyze.py`, so that chain is live in the
  exact scope the call would have run in.

pandas blocks `__import__` by name, which matters for a reason worth
recording: **the first version of the escape test used `__import__` and
passed with the parser swapped out for `df.query()`.** It was a test named
for a thing it did not check. The two payloads above replaced it, and both
fail under that mutation now.

So `where` is parsed by hand into a column, an operator and a literal. No
precedence, no arithmetic, no calls — each of those is a step back towards
needing an evaluator. `or` is refused with the workaround named (`in`), a
wrong column name lists the real columns, and every result states
`N of M rows matched` so an empty filter cannot be read as a real zero.

**`web_fetch` was GET-only** (`5244834`). Now `method`, `headers`, `body`.
The capability is the easy part; three other things had to be right.

- *The gate, wired before the feature.* Non-GET is `action_is_write` and
  answers to the same confirm toggle as a file write. `DELETE` is
  `action_is_destructive`, so it pauses on the filament face too — without
  that, "delete my account" spoken aloud would have gone through with no
  pause at all, because on that face the spoken ask is the grant.
- *Redirects are not followed for non-GET, at all.* A 307 replays the
  method, the body **and** the headers against whatever host the `Location`
  names. An `Authorization` meant for one API would be handed to another,
  chosen by the server. There is no check that makes that acceptable, so the
  hop is reported and the model can fetch the new URL deliberately. GET still
  follows hop-by-hop with the existing per-hop check.
- *`Host` cannot be set.* Every guard in `fetch.py` validates the host in the
  *URL*; a `Host:` header that disagrees is how a request that passed the
  check arrives somewhere else. Framing headers (`Content-Length`,
  `Transfer-Encoding`, …) are refused for the smuggling reason. A forbidden
  header **fails the call** rather than being dropped — a silently dropped
  `Authorization` reads as "the API rejected us" rather than "we never sent
  the key".

The confirm card shows the verb and the host and nothing else. Header values
are the one place an API key lives on this path, and a card is one
screenshot away from somewhere it should not be.

Two of these tests were caught passing for the wrong reason during the
mutation round: the made-up hosts fail DNS, so `ok is False` was true
regardless of the guard. They assert on the message now, and a `resolvable`
fixture stubs the URL check only where the question is what went on the
wire — never in the SSRF tests, where stubbing it would test the stub.

**`calculator` was wrong about arithmetic** (`6ee6e22`, `b371959`). This is
the one worth reading. The roadmap line asked for variables and units; both
were already answered elsewhere — `python` has variables and says so in its
own description, and `units.py` is pint-backed and has existed the whole
time. Meanwhile the tool whose module docstring reads *"Deterministic
arithmetic — so the model does not invent numbers"* had **no test file at
all**, and returned:

- `0.1 + 0.2 = 0.30000000000000004`
- `100 * 1.1 = 110.00000000000001`
- `0.1 + 0.2 - 0.3 = 5.551115123125783e-17` (the answer is zero)
- `2e400 = inf`, with `ok=True`
- `2e400 - 2e400 = nan`, with `ok=True`

The last two are the bad ones. A tool called specifically so the model would
not invent a number handed back a non-number and marked it a success.

Arithmetic now runs on `Fraction`. A decimal literal is read as the decimal
that was *written* — `Fraction(str(0.1))` is one tenth, where `Fraction(0.1)`
is the exact binary value and would be the problem rather than the fix.
Floats are still used the moment a real function is involved, because `sqrt`
and `log` have no rational answer and pretending otherwise is a different
lie. `1/3` reports `0.3333333333333333 (exactly 1/3)`, so the model does not
treat the decimal as the whole truth.

Two problems this *created*, both found by my own tests rather than by
reading:

- Exact arithmetic has no overflow, so `1e308 * 10` stopped being `inf` and
  became a genuinely correct 309-digit integer — correct, and three hundred
  tokens of prompt nobody can read. Capped at 500 digits (generous:
  `factorial(170)` is 307 and is a real answer), with a refusal that says
  why rather than truncating.
- A huge *float* still satisfies `is_integer()`. `hypot(1e308, 1e308)` was
  being spelled out as a 309-digit integer of which roughly 292 digits are
  an artefact of the binary representation — claiming precision the number
  does not have, which is the same failure as returning `nan` with `ok=True`.

Mutation found one more: disabling the `isfinite` check broke nothing,
because `Fraction` now catches the obvious overflows at the literal. It is
not dead code — `sqrt(1e308)*1e300` goes through a real function and comes
back as `inf` — but nothing had been covering it, and it is covered now.

Separately, every failure now names the next tool the way `analyze` does for
a PDF: unit conversions point at `units`, equations at `cas`, scripts at
`python`, combinations at the `factorial` form. A bare "invalid syntax"
leaves answering from memory as the model's only remaining move.

And the shapes people actually type are accepted: `15% of 84`,
`30% off 59.99`, `$45.00 + $12.50`, `1,250 + 300`, `20 x 5`, `what is 8*7`,
`3 + 4 =`. The thousands separator is only stripped when the expression
contains no `(`, because `max(1,250)` is two arguments and reading it as
1250 would be silent and wrong — much worse than not understanding a comma.

**What generalises, again.** Two of the three tools here had no test file.
Both had a real defect. The `no test file` query has now found a defect
every single time it has been run, and there are tools left on that list.

### Policy holes found during the audit

Small, and they belong wherever they get done fastest:

- [ ] **6.10** `research_report` writes a file to disk with
  `risk="read"` and no Allow card (`tools/research_report.py:102`).
  `docs/architecture.md:278` admits this.
- [ ] **6.11** `camera` capture has `confirm_toggle: none`
  (`tools/policy.py:287-288`) while `vision` on the same still is gated.
  The webcam is the ungated half.
- [ ] **6.12** `external_read` appears in confirm copy and policy
  (`tools/policy.py:518-525`) but is not a registered tool, so docs and
  model prompt can drift from it freely.

---

## Phase 7 — ship 0.2.8

- [ ] **7.1** Run the live boards: `scripts/live_glass_board.py` (20
  prompts) and a subset of `live_glass_fifty.py`.
- [ ] **7.2** Screenshot/video pass on every touched feature.
- [ ] **7.3** Write `docs/releases/v0.2.8.md`.
- [ ] **7.4** Bump `arelis/__init__.py:10`, tag, let the installer
  workflow build, publish the draft.
- [ ] **7.5** Add a nightly CI job running `live_feature_pass.py` with the
  report as an artifact, so live regressions surface without a person.

### Ship blockers that are not code

- Installer is **unsigned** — SmartScreen warns every stranger.
  A code-signing certificate is the single biggest trust gap.
- GitHub releases publish as **drafts**; `releases/latest` 404s until a
  human clicks, which also means the self-updater sees nothing.
- No crash reporting. Logs are local-only by design, which is the right
  privacy call, but it means a stranger's crash is invisible to you.

---

## Frozen

**Earth / Reality / solar.** `arelis/earth/` (~16k lines, 70 files),
`arelis/spatial/` (~3.1k), `arelis/physics/` (~3.9k). 141 catalog feeds,
a Cesium child process, a native GL solar lab.

It is coherent and well documented. It also ships in no installer
(`spatial/grant.py:27-38` hard-blocks it), carries 327 of the 1,391 mypy
errors, and has the thinnest per-fetcher test coverage in the tree.

**Rule for this roadmap:** keep it green, do not extend it, do not delete
it. If a Phase 3 refactor touches a shared file, make the Earth side
compile and move on. Revisit after 0.2.8 ships.

The existing `.cursor/rules/multi-agent-lanes.mdc` protections stay in
force regardless of this freeze.
