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

## Found during Phase 1 C

`paint_overlay` already calls HUD through `panel._paint_hud` / `_paint_inspect`
delegates, so the HUD extract has no circular import.

`tests/test_solar_panel.py` pins `paint_free_markers` by slicing to the next
`def`. After the split that function is last in `solar_paint.py`; the pin now
allows end-of-file. `paint_mark(` must also stay in `solar.py` (roster) —
roster was not extracted for that reason.

`tests/test_earth.py` monkeypatches `cameras._host_pinned` and
`cameras.fetch_osm_webcams`. Fetchers late-bind those two names. Ethics
docstring and "an open port is not consent" stay on `cameras.py`.
`test_egress.py` was not edited.

`solar_gl.py` is still ~2088 lines: the shaders and `SolarSpaceView` are the
bulk. Geom/projection/mesh left. `stars_only` and the Cesium park path stayed
on the widget / `SolarEarthMixin`.

After this pass (ruff-cleaned):

| File | Lines |
|---|---|
| `solar_paint.py` | 1096 |
| `solar_hud.py` | 1287 |
| `solar.py` | 1764 |
| `solar_earth.py` | 581 |
| `solar_gl.py` | 2088 |
| `solar_gl_geom.py` | 238 |
| `cameras.py` | 69 (façade) |
| `cameras_fetch.py` | 1653 |
| `traffic.py` | 43 (façade) |
| `traffic_fetch.py` | 1538 |

## Found during Phase 1 D

Every public `fetch_*` in `earth/` already swallowed HTTP errors
(`except Exception: return None` / `[]`). There was no shared helper and
no retry. `arelis/earth/http.py` is that helper: pin, timeout, optional
retry (default 0 so a dying host is not hit twice).

Wired into the clone-shaped GET JSON fetchers plus `traffic_fetch._get_json`.
`shodan.py` ethics and `cameras_fetch.py` internals were left alone; cameras
is covered through the public `fetch_cameras` API.

Did not migrate every remaining Client (opensky credits, AIS websocket,
Space-Track login). Those already fail-soft; the new tests pin that.

## Found during Phase 1 E (CI report)

`tests/test_ci_gate.py` used to forbid the word `mypy` in `ci.yml`.
The types job is `continue-on-error: true` and uses the same
`mypy==2.3.1` pin. The 8-way test matrix still does not run mypy.

## Found during Phase 2 F

Coverage is a separate `continue-on-error` job on earth/ and spatial/
tests. No `--cov-fail-under`. The 8-way matrix does not collect coverage.

## Found during Phase 2 G

`TOOL_LOOP_HINT` / `FILE_LOOP_HINT` / `RESEARCH_HINTS` were copy-pasted
into four orchestrator modules; only `classify_role` used them. One
module now owns the patterns. The regexes themselves were not rewritten.
