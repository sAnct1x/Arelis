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

Coverage is now **19 covered, 0 holes, 3 blind spots** (the same three
above). The board gained the `recall`, `inspect` and `document` guards it
never had.

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

### 3a — exact duplication

- [ ] **3.1** `research_needs_vram_swap`, `comms_bypasses_sticky`,
  `TOOL_CMD`, and `ROLES` are **byte-identical** in
  `core/orchestrator.py:77-125` and `core/orchestrator_turns.py:44-106`.
  One owner.
- [ ] **3.2** `_BUSY_WATCHDOG_MS = 8000` is defined in four files:
  `ui/window_build.py:102`, `ui/window_chrome.py:65`,
  `ui/window_lifetime.py:45`, `ui/window_turn.py:34`.
- [ ] **3.3** Four modules independently scan history for a path mention
  with their own `_PATH_MENTION` regex: `core/document_refs.py:23`,
  `core/image_refs.py:15`, `attachments.py`, `core/look.py`. Extract
  `core/path_refs.py`.
- [ ] **3.4** Tool surface is computed in `turn_prepare.py:209-371` and
  recomputed as a near-subset in `turn_round.py:666-696` on escalate. One
  function, called twice.

### 3b — the three `*_complete` modules

3,935 lines across `sms_complete.py`, `email_complete.py`,
`agenda_complete.py`. Literal shared code is tiny (~2%); **structural**
duplication is near-total — every one has a draft dataclass, a parse
function, a history-merge, an args-lock, a preflight nudge, and a force
notice, in that order.

Do **not** merge the parsers. The 84 compiled regexes are STT-mishear
scars and they are domain-specific on purpose.

- [ ] **3.5** Extract `core/utterance_guards.py` and move the ~48
  `looks_like_*` guards out of `sms_complete.py`. This also breaks the
  ugly dependency where `intent_catalog.is_tiny_prompt_ask`
  (`intent_catalog.py:1326-1329`) imports from the fattest complete module
  just to detect a greeting.
- [ ] **3.6** Extract `core/confirm_patterns.py`. `_SEND_CONFIRM` appears
  at `sms_complete.py:365`, `email_complete.py:409`,
  `agenda_complete.py:190` with the same skeleton and a different verb
  list. `_PROCEED_ASK` is the same story.
- [ ] **3.7** Extract the history-revival walk (Case B/C). Roughly 80
  lines, written three times.
- [ ] **3.8** Unify recipient resolution. `contacts.resolve_sms_alias`
  and `email_complete`'s address resolution are the same operation on
  different channels.
- [ ] **3.9** Write `tests/test_agenda_complete.py`. SMS and email have
  real coverage; agenda has none — `test_agenda_parse.py` tests
  `tools/agenda._parse_dt`, a different module.

### 3c — silent failure surface

460 bare `except Exception:` and 222 `except: pass` across `arelis/`.
Not all are wrong — fail-soft is often correct in a desktop app. These
specific ones can produce a wrong answer rather than an error:

- [ ] **3.10** `llm/router.py:311-317` — `_refuse_if_host_vram_full`
  returns silently on probe failure, so the host VRAM guard vanishes
  without a trace.
- [ ] **3.11** `llm/ollama.py:315-317` — `capabilities()` returns an empty
  frozenset on any error, so a vision-capable chat model gets treated as
  blind and pays an unnecessary VL detour.
- [ ] **3.12** `memory/indexer.py:111-187` — embed batch failures log and
  return 0, so the index silently falls behind forever.
- [ ] **3.13** `core/lessons.py:177-178` — a malformed `lessons.yaml`
  becomes `{}` with no user warning.
- [ ] **3.14** `core/turn_round.py:818-848` — `_tool_followup_fallback`
  can ship raw tool output as the final answer when the model returns
  empty after a successful tool.
- [ ] **3.15** Adopt a convention: `except Exception` must either log at
  `warning` or carry a comment saying why silence is correct. Add a ruff
  or custom check so new ones need a reason.

### 3d — god functions

Do these last; they are the highest-risk edits and Phase 0's net is what
makes them possible at all.

- [ ] **3.16** `turn_round.apply_no_call_path` (`turn_round.py:179-607`)
  unpacks ~40 rebound locals and writes them back in a `finally`. The
  author's own note at `turn_round.py:187-190` says collapsing the scratch
  object is "a later contract." This is that contract: make a real
  dataclass instead of `SimpleNamespace`.
- [ ] **3.17** `turn_dispatch.dispatch_calls` (`turn_dispatch.py:101-793`)
  — same scratch pattern, same fix.
- [ ] **3.18** `turn_prepare.prepare_turn` (`turn_prepare.py:76-653`) —
  ~580 lines of prompt assembly. Split by section, not by line count.
- [ ] **3.19** `ui/window_build._construct_shell` — constructs 50+
  subsystems in one method.

### 3e — types

1,391 mypy errors across 134 files, advisory in CI. `arelis/guard/` is
already clean, and `NOTES.md:30-31` has the recommended order.

- [ ] **3.20** Make mypy blocking for `arelis/guard/` and `arelis/memory/`
  only, via per-module CI config. A clean package that can regress is not
  clean.
- [ ] **3.21** Take `arelis/tools/base.py` and `arelis/llm/` next — small,
  high-traffic, and they define contracts everything else depends on.
- [ ] **3.22** Add each newly clean package to the blocking list. Never
  attempt the 689-error `arelis/ui` pile as one task.

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
- [ ] **4.2** `workspace` has no recursive search. "Find where X is
  defined" is impossible without listing every folder, which the same-call
  guard then blocks. Add `action=grep` with a path glob.
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
- [ ] **4.5** `calculator` takes one expression with no variables and no
  units (`tools/calculator.py:66-67`). Give it a variable scratchpad.
- [ ] **4.6** `plot` does line, scatter, residuals only. Add histogram,
  bar, and subplots — the three a homework or data question actually asks
  for.
- [ ] **4.7** `web_fetch` is GET-only with no headers, no POST, no auth
  (`tools/web.py:28-32`). Any real API integration is impossible.
- [ ] **4.8** `analyze` does summary/head/describe. No filtering, no
  grouping, no joins. Add a query action.
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
