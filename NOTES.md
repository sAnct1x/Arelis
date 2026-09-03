# Cleanup notes

Verified against this checkout before any Phase 1 work. Review claims
that did not hold were skipped, not forced.

## Found during Phase 0

### Baseline (this checkout, 2026-09-03)

- `ruff check .`: clean
- `pytest -q`: **3181 passed, 3 skipped**, 13 warnings, 187s
- `mypy` (2.3.1, `[tool.mypy]` in `pyproject.toml`, `ignore_missing_imports`,
  not `--strict`): **1391 errors in 134 files**, 441 source files checked
- `tests/test_egress.py` was not modified

mypy by package (same run):

| Package | Errors |
|---|---|
| `arelis/ui` | 689 |
| `arelis/earth` | 327 |
| `arelis/core` | 158 |
| `arelis/tools` | 97 |
| `arelis/physics` | 21 |
| `arelis/voice` | 21 |
| `arelis/eval` | 17 |
| `arelis/presence` | 15 |
| `arelis/memory` | 11 |
| `arelis/guard` | 0 |

`guard/` is already clean. Phase 1 E should start with `memory/` and
`tools/base.py`, and stay out of `core/` until A and B have merged.

`tests/test_ci_gate.py` currently forbids the word `mypy` in
`.github/workflows/ci.yml`. A later non-blocking report job has to
rewrite that pin, not sneak a step past it.

### Claim: dangling README doc links — stale, skipped

`docs/test-results.md`, `docs/foundation.md`, `docs/BREADCRUMBS.md`,
`docs/operator-hardware-e2e.md`, and `docs/voice-ttft.md` are not
referenced anywhere in the tree. They are not gitignored. The README
further-reading table only names files that exist. `tests/test_docs_links.py`
already fails if a relative link rots or a top-level `docs/*.md` is
unlinked. No README or stub change.

### Claim: oversized core dispatch — holds, paths drifted

| Symbol | Review said | This checkout |
|---|---|---|
| `apply_no_call_path` | ~1,400 lines in the core loop | **1398** lines in `arelis/core/turn_round.py` (starts line 231) |
| `dispatch_calls` | ~1,100 lines | **1129** lines in `arelis/core/turn_dispatch.py` (starts line 67) |
| `agent_loop.py` | 1,500–2,000 | **1467** lines |
| `turn_round.py` | 1,500–2,000 | **1966** lines |

Agent A's ownership table listed only `agent_loop.py` and `turn_round.py`.
`dispatch_calls` already lives in `turn_dispatch.py`. A must take that
file too, or it is editing the wrong coordinator.

### Claim: duplicated complete modules — holds, sizes slightly off

Same detect → draft → force-notice shape, independently implemented:

| File | Lines |
|---|---|
| `arelis/core/sms_complete.py` | 1119 |
| `arelis/core/email_complete.py` | 1625 |
| `arelis/core/agenda_complete.py` | 925 |

Agenda is under the "~1,000+" shorthand. Still a real dedup candidate
after A lands.

### Claim: oversized non-core files — holds

| File | Lines |
|---|---|
| `arelis/ui/panels/solar_paint.py` | 2360 |
| `arelis/ui/panels/solar.py` | 2322 |
| `arelis/ui/solar_gl.py` | 2288 |
| `arelis/earth/cameras.py` | 1646 |
| `arelis/earth/traffic.py` | 1535 |

### Claim: earth / spatial / physics tests are thin — mixed

Code volume is real: `earth/` 16,043 lines (59 files), `spatial/` 3,463
(12), `physics/` 4,842 (25) — **24,348** together.

Dedicated tests are more than "9 files of nothing": `test_earth.py` alone
is 2,534 lines. Named earth/spatial/physics files:

- `test_earth.py`, `test_earth_goto.py`, `test_earth_polish.py`
- `test_spatial_rung0.py`
- `test_physics_solar.py`, `test_physics_verbs.py`, `test_world_physics.py`

The part that still wants Agent D is per-fetcher fail-soft / timeout /
rate-limit coverage. `shodan.py` is the shape to copy. Do not touch
`shodan.py` ethics, and do not take `cameras.py` internals from C.

### Claim: regex routing in orchestrator.py — holds, not a Phase 0 fix

`TOOL_LOOP_HINT` and `RESEARCH_HINTS` are still in
`arelis/core/orchestrator.py` (around lines 120 and 134). Phase 2 G only:
make them legible and testable. Do not replace the approach.

### Do-not-touch list — confirmed present, left alone

`tests/test_egress.py`, `arelis/earth/shodan.py`, `arelis/earth/cameras.py`
restraint comments, `LICENSE`, `arelis/guard/`, `arelis/relay/crypto.py`.

## Found during Phase 1 A

`apply_no_call_path` still unpacks ~40 rebound locals and writes them back
in `finally`. The inject/finish tables are the strategy split; collapsing
the scratch object is a later contract, not this pass.

`dispatch_calls` still owns confirm/execute and the per-call skip guards
(duplicate weather, page budget, same-call). Redirects are the table.

## Found during Phase 1 B

The three `*_complete` parsers stay domain-specific (`_SEND_CONFIRM` wording
differs for text / mail / create). The shared leftover is remaining
recipients, the unfinished-call notice, and appending the current user
turn. A base class would have been a fake.
