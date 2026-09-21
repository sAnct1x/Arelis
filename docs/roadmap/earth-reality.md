# Earth / Reality audit

Written 2026-09-19 against commit `46b6391` (HEAD after the
daily-driver close + this handoff). This is a working checklist,
not a vision doc. Steps are numbered so a sitting can say "I did
3.14" and mean something.

Audit source: a full read of `arelis/earth/` (66 files, 17,555
lines), `arelis/physics/` (26 / 4,955), `arelis/spatial/` (12 /
3,575), the Reality UI plate (`world_window.py`, `solar_*`,
`earth_globe/`, `earth_overlay.py`, `earth_marks.py`, `solar_gl.py`,
`solar_paint.py`, `launch.py`, `earth_globe_host.py`,
`earth_globe_proc.py`), `arelis/tools/earth_tool.py` +
`solar_tool.py`, and every `tests/test_earth*`, `test_reality*`,
`test_solar*`, `test_physics*`, `test_spatial*`, `test_egress*`,
`test_globe_stack.py` file. Numbers in here were measured on this
checkout, not estimated.

The daily-driver audit (`docs/roadmap/README.md`) is **closed**.
Do not reopen it. Glass, tools, orchestrator, SMS, Allow stay
frozen the other way.

Canvas view: `earth-reality-audit.canvas.tsx` in the Cursor
canvases folder. The markdown is the source of truth. If the
canvas dies, keep this file.

Handoff prompt: `docs/roadmap/earth-reality-handoff.md`.

## Contents

- [The thesis](#the-thesis)
- [Measured inventory](#measured-inventory)
- [Doc vs code, found on the read](#doc-vs-code-found-on-the-read)
- [Phase 0 — safety net](#phase-0--safety-net)
- [Phase 1 — close in-flight lies](#phase-1--close-in-flight-lies)
- [Phase 2 — measure any rip-it thesis](#phase-2--measure-any-rip-it-thesis)
- [Phase 3 — cleanup and dedup](#phase-3--cleanup-and-dedup)
- [Phase 4 — verb depth](#phase-4--verb-depth)
- [Phase 5 — missing verbs / honest holes](#phase-5--missing-verbs--honest-holes)
- [Phase 6 — usability](#phase-6--usability)
- [Phase 7 — walk the plate](#phase-7--walk-the-plate)
- [Frozen the other way](#frozen-the-other-way)
- [How to recover](#how-to-recover)

---

## The thesis

> Written before anything in this sitting was *fixed*. Keep it even
> if the numbers later contradict it. Last audit's thesis was
> confident and wrong; cancelling Phase 2 there was the point of
> measuring. Same rule here.

**The wound is not Cesium, and it is not 141 feeds.**

The production board (`reality-production-plan.canvas.tsx`) claimed
skip-Cesium / GPU native disc as the live Earth path, Live off by
default, a Buildings chip, and in-process photoreal slipped. The
lane rules, `docs/earth.md`, `docs/whats-new.md`, and the code on
this checkout all say the opposite for the planet: **Earth zone is
Cesium; solar lab is native GL; never both live; native NASA disc
is fallback only.** Enter parks solar GL, then mounts Cesium in a
child process when GPU solar was live. Travel to Earth does **not**
mount Cesium — it is a solar-lab warp. That contract is implemented.
Do not rip Cesium because a completed canvas said "skip." Verify
pixels in Phase 7; do not reopen the host debate in Phase 2 unless
a measurement says the child process is the GPU hole.

The wound that *does* look like last audit:

1. **Fail-soft merge treats `[]` the same as `None`.**
   `live._apply_live` only replaces a layer when the gathered result
   is truthy (`if flights:`, `if vessels:`, `if pins:`, …). A miss
   (`None`) correctly keeps sim. A successful empty fetch (`[]`)
   also keeps the previous layer. Walking the look box drops TTL
   (`LOOK_BOX_ADAPTERS`) so the next city refetches — and if that
   fetch is honestly empty, last city's planes/ships/cameras stay
   in the store. `visible()` may hide them. A dump receipt will
   not. This is "empty catalog looks like last sky," the Earth
   shape of scanned-PDF `[]` and "no texts" when the bridge was
   dark.

2. **The inventory test counts statuses, not ids.**
   `FEEDS` is 141 = 109 shipped / 25 keyed / 3 later / 4 out, and
   that string is pinned in `docs/earth.md`. **102 of 141 feed ids
   are never named in any `tests/test_*.py`.** 82 of those are
   shipped. A thinned region stays green as long as the four
   status counts hold. Same shape as a helper with 100% coverage
   and unwired call sites.

3. **Docs from two campaigns sit next to each other and disagree
   with the code.** Live-off default (production canvas) vs Enter
   turns Live on (runtime). Drop satellite refresh at near
   (`docs/earth.md`, `docs/whats-new.md`) vs `ADAPTER_BANDS`
   keeping CelesTrak on near *and* city. Buildings chip (earth.md
   table, whats-new) vs runtime `self.buildings = False` and
   `test_earth_docs_inventory_matches_feeds` asserting
   `"**Buildings**" not in earth`. `copy.status_line` says "Live
   keeps pulling" when `zone.live` is False. `earth_tool`
   description says enter snapshots then coasts; `EarthRuntime.enter`
   turns Live on.

4. **Fetcher tests assert `got in (None, [])` after mocking HTTP
   to death.** A fetcher that always returns `[]` on a live payload
   still passes. The fail-soft net cannot see the empty-sky bug.

What this thesis is *not* claiming, so Phase 2 does not run off
and delete things:

- Cesium is a wound. **Not claimed.** Measure hitch / VRAM before
  touching the child process. Overlay Qt tests do not replace it.
- 141 feeds are a wound. **Not claimed.** Do not thin a region.
  Later/out are already not fetched (measured: 0 later/out ids in
  `live._adapter_fns()`).
- Native disc is dead code. **Not claimed.** Fallback when
  WebEngine is missing or Cesium boot fails. Do not delete
  `earth_globe/`, the host, or `choose_stack`.
- Shipping Cesium in the installer. **Hard block.**
  `world_stage_allowed()` — source checkout only. The Reality
  *room* still exists in the installer for chat, CAS, Horizons.

If Phase 2 measures this thesis wrong, check the box cancelled and
leave the argument here.

---

## Measured inventory

Freeze note in `docs/roadmap/README.md` said ~16k / 70 files
earth, ~3.1k spatial, ~3.9k physics, 327 of 1,391 mypy. On this
checkout (physical `splitlines()`, 2026-09-19):

| Package | Files | Lines | Freeze said |
|---------|------:|------:|-------------|
| `arelis/earth/` | **66** | **17,555** | ~16k, 70 files |
| `arelis/physics/` | **26** | **4,955** | ~3.9k |
| `arelis/spatial/` | **12** | **3,575** | ~3.1k |
| **combined** | **104** | **26,085** | ~24k |

`FEEDS`: **141** rows = **109 shipped / 25 keyed / 3 later / 4 out**.
Matches `earth/__init__.py` and `docs/earth.md`. **34** live
adapter keys. Later/out are inventory-only: **none** appear in
`live._adapter_fns()`.

Feed ids named in any `tests/test_*.py`: **39 / 141**. Unnamed:
**102** (82 shipped, 18 keyed, 1 later `copernicus-dataspace`, 1
out `face-index`).

Lane docs name `test_earth_appearance.py` and
`test_reality_walk.py`. **Those files do not exist.** Walk
coverage lives in `test_earth_field.py` / `test_earth_inspect.py`
/ `test_globe_stack.py` instead.

Modules whose *filename* never appears in any `test_*.py`
(cheap query; not "unreachable"):

- `arelis/earth/traffic_fetch.py` (1,520 lines — the real 511/WZDx
  builders; tests hit the `traffic.py` façade)
- `arelis/physics/corona.py`, `star_look.py`
- `arelis/spatial/one_euro.py`

Read those first. Last audit: `no test file` found a defect every
time it was run.

`world_stage_allowed()` (`spatial/grant.py:27-38`): installer
(`unins000.exe` at install root) and wheels (no `tests/` next to
`pyproject.toml`) do not get the 3D plate. Physics room still
exists there.

GPU contract on this checkout (code, not the production canvas):

| Verb | What lives |
|------|------------|
| Travel to Earth | Solar-lab warp, ~8× IAU standoff. Sets `_earth_at_door`. **No Cesium.** |
| Enter Earth | `EarthRuntime.enter()` → park solar GL → `EarthGlobeHost`. Child process when `gl_wanted()` / share group live. |
| Leave Earth | Kill child / `deleteLater` in-process view → `unpark()` solar GL. |
| Photoreal miss | `host._on_failed`: `why != "cesium"` returns without setting `failed`. |
| Native disc | Fallback: no WebEngine, host construct fail, Cesium boot fail. |

Enter turns **Live on** (unless pytest / unix override). Default
chips: satellites + ISS. Buildings chip is gone in runtime
(`self.buildings = False`). Streets wait on city + altitude.

Frames: Earth store is ECEF metres; solar lab is ECLIPJ2000.
`earth/frames.py` imports `_earth_frame` from
`physics.attitude`. Not duplicated math.

---

## Doc vs code, found on the read

The roadmap is a lead. These are already measured. Phase 1 closes
them; do not silently "correct" the old sentences in git history
— write the fix and the note here.

| Claim | Where | Code |
|-------|-------|------|
| Live stays off by default | production canvas P1-7, "completed" | `EarthRuntime.enter` sets `live = True` outside pytest (`runtime.py:149-150`) |
| Drop satellite refresh at near | `docs/earth.md:68`, `docs/whats-new.md:281` | `ADAPTER_BANDS` keeps `celestrak` / `spacetrack` / `tip` on near **and** city (`lod.py:138-141`). Runtime docstring: "CelesTrak keeps running after you leave space." |
| Buildings chip / footprints | `docs/earth.md:159` table, `whats-new` building outlines | Runtime forces `buildings = False`. No Buildings chip on the bar. `test_earth_docs_inventory_matches_feeds` asserts `"**Buildings**" not in earth` — the table cell still says "when Buildings is on" without the bold |
| GPU Travel keeps the native NASA disc / skip Cesium | production canvas P0 / P2 | Travel skips Cesium (**true**). Enter mounts Cesium (**true**). Native disc is fallback, not the live Earth planet |
| "Live keeps pulling" on a coasting view | `copy.py:183-186` | That branch is `elif published` after `zone.live` was already False |
| enter snapshots then coasts | `earth_tool.py:31-32` | Enter turns Live on |
| Space = sats only; approach = planes only (chip bar) | production canvas P1-3/4 | `CHIP_LAYERS["approach"]` still includes satellites + ISS + flights + drones (`lod.py:187`) |
| Failures keep sim | almost every fetcher docstring | True for `None`. **False for `[]`** if you wanted a quiet box to replace last city — `_apply_live` truthy-check |

When a ticket below is wrong, write that under the step. Do not
edit the ticket until the code has been re-read.

---

## Phase 0 — safety net

Nothing else starts until this is green. Offline, no Ollama, no
need to launch the GUI. Visual pass is Phase 7.

**The rule this phase establishes (copied):** a test is not
trusted until it has been watched failing for the reason it
claims to guard. Disable the new guard; the suite must go red.

- [x] **0.1** Inventory this tree into this document. Measured
  2026-09-19. Freeze numbers were stale (file counts, line
  counts). Ticket said 70 earth files; it is 66.
- [x] **0.2** Pin the **full** `FEEDS` id → status map, not the
  four count strings. `tests/test_earth_audit.py` `FEEDS_PIN`.
- [x] **0.3** Pin later/out ids are **not** in
  `live._adapter_fns()`.
- [x] **0.4** Empty successful fetch vs miss.
  **Watched red on HEAD** (`if flights:` kept last city). Fixed
  `_apply_live` to replace look-box layers when the value is a
  list, including `[]`. Mutant: restore `if flights:`;
  `test_empty_opensky_clears_last_city_flights` goes red.
- [x] **0.5** Companion: `None` still keeps sim. **Ticket was
  half-wrong:** OpenSky already returned `[]` on timeout and
  budget stop, so treating `[]` as quiet-ocean would have wiped
  sim on a miss. `fetch_opensky` now returns `None` on fail /
  no credits, `[]` only when the API was heard and the box is
  empty. AIS already had that split.
- [x] **0.6** `trails.py` `note` / `points` / `forget`. Leave
  and unlock clear the deque. Mutant: skip `forget_trails()` in
  `leave`; `test_leave_forgets_earth_trails` goes red.
- [x] **0.7** `catalog.LAYERS` default_on is only satellites +
  ISS. Closer band must not flip chips — kept the existing
  `test_earth.py` pin.
- [x] **0.8** Enter / leave / park / child-process isolation.
  Existing `test_globe_stack.py` covers park-before-Cesium and
  `globe_wants_own_process`. Spoken leave now calls the same
  `_leave_earth_zone` as the chip (3.1). Photoreal vs cesium
  fail already had the companion that can go red.
- [x] **0.9** Photoreal miss must not set `host.failed`. Kept
  `test_globe_stack.py:172`. HUD copy "fancy map failed — NASA
  ball" already pinned in polish.
- [x] **0.10** `world_stage_allowed`: installer tree and
  non-checkout deny the plate. Existing
  `test_world_stage.py` / `test_installer_never_gets_a_session`.
- [x] **0.11** Buildings: runtime flag stays False; no chip on
  the bar. Pinned. Docs closed in 1.5.
- [x] **0.12** `traffic_fetch.py` named: WZDx Utah host +
  unpinned URL does not open + parser is not a car.
- [x] **0.13** Pin current sat-refresh bands (celestrak on
  space/approach/near/city). Phase 1.4: **docs were the lie**,
  not the fetch. Paint caps the swarm; TLE still refreshes.
- [x] **0.14** Egress pin stays. Ran green.
- [x] **0.15** Fail-soft parametrize left as timeout-must-not-raise.
  0.4 is the empty-sky net.

---

## Phase 1 — close in-flight lies

Code first, then the sentence in the doc. Surgical on
`docs/earth.md`, `docs/whats-new.md`, `earth/__init__.py`.

- [x] **1.1** `_apply_live` None vs `[]` (closed with 0.4/0.5).
  Look-box layers replace on a successful empty fetch. Orbital
  layers still do not wipe the shell because CelesTrak returned
  `[]` (`_merge_sats`).
- [x] **1.2** `copy.status_line` "Live keeps pulling" when
  live is off. **Was a lie.** Coasting sentence no longer
  promises a poll. Test in `test_earth_polish.py`.
- [x] **1.3** `earth_tool` description: enter turns Live on,
  distance-gated. Removed "snapshots then coasts" as the default.
  Streets, not Tiles.
- [x] **1.4** Sat refresh at near/city. **Ticket (docs) was
  wrong.** Fetch keeps CelesTrak on every band. Paint
  (`pick_orbit_marks`) caps the swarm in approach/near/city.
  Docs and whats-new now match: TLE still refreshes; the globe
  stops painting the swarm.
- [x] **1.5** Buildings. Code has no chip. Docs table and
  whats-new no longer advertise a Buildings chip.
  `buildings.py` stays in-tree (not deleted as dead code).
- [x] **1.6** Production canvas "GPU skip / Live off / Buildings
  chip" is a prior campaign. Noted on this audit canvas. Do not
  rewrite that board's history.
- [x] **1.7** Photoreal miss vs `host.failed` — already pinned.
  Native fallback HUD copy is loud (`fancy map failed — NASA ball`).
- [x] **1.8** Keyed without a key stays quiet. APRS already
  pinned; later/out never in adapters (0.3).

---

## Phase 2 — measure any rip-it thesis

Do not implement a cancelled phase. If the numbers say no, check
cancelled and move.

Candidates, each with a measurement that would justify acting:

- [x] **2.1** "Cesium child process is the GPU hole." **Cancelled
  as unneeded, 2026-09-19.** The live path is Cesium; native disc
  is fallback; park-then-child is implemented and tested. Do not
  rip it because it is large. Hitch numbers belong in Phase 7
  notes, not a host debate.
- [x] **2.2** "141 feeds are the slowness." **Cancelled on
  measurement, 2026-09-19.** `adapter_allowed("cameras", "space")`
  is False with default chips. Space does not hammer 511.
  Empty-sky was the merge truthy-check, not feed count. Do not
  thin a region.
- [x] **2.3** "Merge native disc + Cesium into one GL planet."
  **Cancelled.** Dual path is the fallback contract.
- [x] **2.4** "Restore Buildings chip / in-process photoreal."
  **Cancelled.** Photoreal is Google 3D tiles in Cesium when
  keyed. Buildings chip stays off. Do not remount Cesium
  in-process.

If this sitting never needs to rip architecture, close 2.1–2.4
as **cancelled on measurement** (or cancelled as unneeded) the
same way last audit cancelled schema restore.

---

## Phase 3 — cleanup and dedup

Duplication is where defects hide. Diff copies. The odd one out
is the bug. Do not extract for neatness.

- [x] **3.1** Enter / leave. Spoken `leave_earth` now calls the
  same `_leave_earth_zone` as the chip (dump + zone.leave +
  drop globe). Travel-away and `reset_view` funnel through it.
  Headless tool path still dumps then `zone.leave()`; the solar
  tick drops the globe when the zone is inactive.
  **Ticket was slightly wrong** that speech *only* waited on
  the tick — it also dumped — but the globe teardown was the
  lazy copy. Test: `test_spoken_leave_earth_uses_plate_teardown`.
- [x] **3.2** Park / unpark / `_cesium_off`. Travel does not
  park (02_travel_earth_door still NASA disc + Enter). Enter
  parks then mounts. Leave drops the globe then the solar HUD
  returns (10_leave_earth). Native Enter now calls
  `_hold_earth_eye` immediately — waiting on the physics tick
  left the Sun in the plate. Software `paint_overlay` no longer
  `reset_view()` (which leaves Earth) on a `_view_id` flap while
  the zone is on. Sun limb / other bodies skipped while the zone
  is on.
- [x] **3.3** Trail vs ride vs track. `trails.py` is not the
  solar ribbon. Leave/unlock forget. Ride sets track; unlock
  clears both. Pinned.
- [x] **3.4** Live chip vs layer chip. Chip off →
  `adapter_allowed` False. **Pixel lie:** `live_chip_label`
  painted `Live …` whenever `_live_busy`, including Live off
  during a coast snapshot. Off stays Off; ellipsis only when
  Live is on. Mutant: `live_chip_label(on=False, busy=True)`
  must not be `Live …`.
- [x] **3.5** GIBS URL literals in `globe_stack.py` and
  `tiles.py`. **They match** (`GIBS_XYZ == GIBS_BLUE`). Pinned.
  No extract until they drift.
- [x] **3.6** Camera/traffic host lists × `look._OFFICIAL_HOSTS`.
  Still-pin URLs are `official_url_ok`. Every look host is named
  in `cameras_fetch` / `traffic_fetch` or `_STILL_PIN_URLS`
  (first pass missed `511la.org` because it is a tuple host,
  not an `https://` literal — ticket was right, the scan was
  thin). `www.trafficnz.info` matches `trafficnz.info` via
  `_host_in` suffix.
- [x] **3.7** Frames: Earth dump `FRAME = "ECEF"`, solar export
  `ECLIPJ2000`. Intentional split, pinned. `earth/frames.py`
  bridges via physics attitude.
- [x] **3.8** `pause` is a Reality verb. `turn live off` is
  `earth_layer` / live. Pinned. `show buildings` is no longer a
  closed chip verb (chip is gone).

---

## Phase 4 — verb depth

What the tool/schema promises vs what runs. Closed speech
already skips the 9B for enter / leave / take me to.

- [x] **4.1** `earth` actions: status, enter, leave, track,
  ride, search, dump, live, coverage, goto. Goto miss is
  `fail:name`, not 0,0. Tokyo resolves; city look alt is 8 km.
  Module docstring still said "snapshots then coasts" after
  1.3 — **that leftover was a lie.** Fixed.
- [x] **4.2** `solar action=craft` is inspect. Same mode as
  `inspect`. "no rideable craft." Does not grow a vehicle.
- [x] **4.3** Travel arrives sunlit outside the body (existing).
  Goto Tokyo uses `CITY_LOOK_ALT_M` (8 km, city band).
- [x] **4.4** Ride sets `ride_id` and `track_id`. Unlock clears
  both. Inspect card: Esc / empty sky hops off (copy already).
- [x] **4.5** Dump / copy view. `dump_state` and `view_receipt`
  drop stream URLs. Pinned.
- [x] **4.6** Find / take me to: gazetteer then Nominatim
  `force=True`. Offline under pytest. **Miss was silent.**
  `apply_goto` now says `No place named X` / `Not a hop to 0, 0`.
  Nominatim / cache drop lat=lon=0.

---

## Phase 5 — missing verbs / honest holes

Stay-absent is a valid close.

- [x] **5.1** Honest gap list after 4.x. Travel / enter / leave /
  find / take me to / ride / track / Live on/off / dump / copy
  view / solar inspect **all have homes**. Copy view is the
  inspect-card chip (`view_receipt`), not a tool action — stay
  that way. No new verb.
- [x] **5.2** General "show me everything live from space."
  **Stay-absent.** Distance gate is the product. Space bar is
  sats + ISS.
- [x] **5.3** Unsecured cams / sat-AIS / face-index / VIN.
  **Stay-absent.** Already `out`.

---

## Phase 6 — usability

Sodium HUD persists. Not a second UI theme.

- [x] **6.1** HUD copy. Inspect Enter sentence now uses
  `earth_enter_offered` (same gate as the button). Live chip
  left-aligned, sized for **Live off**. Coach still names Find.
  Pixels: 04 space bar is sats+ISS; 08 Find suggests Tokyo.
- [x] **6.2** Band chip bar. **Ticket (production canvas) was
  wrong** that approach drops sats. 1.4 already decided: space
  = sats+ISS, approach keeps them and adds flights. Pixels
  match `CHIP_LAYERS`.
- [x] **6.3** Live-off is available; Enter still turns Live
  on. Not reverted to the production canvas. Product call if
  the human wants Live-off default later.
- [x] **6.4** Receipts without stream URLs (4.5).
- [x] **6.5** Deaf / hole lines paint via `coach_line` →
  `paint_coach`. Already pinned in `test_earth_polish.py`.
  Cameras chip on + empty look is the hole sentence.

---

## Phase 7 — walk the plate

You run this. Isolated `ARELIS_DATA_DIR`. HWND grab via
`widget.grab()` / `grabWindow(winId)`, never
`screen.grabWindow(0)`. Stitch a walk video under `outputs/`
(gitignored). Look at every frame.

- [x] **7.1** Enter Reality. Shot script mounts `SolarPanel`
  (the plate). Isolated `ARELIS_DATA_DIR`. 01_reality_lab.
- [x] **7.2** Travel to Earth. 02: NASA disc, Enter offered,
  Cesium **not** mounted. `_earth_at_door`.
- [x] **7.3** Enter Earth. First pass: Sun still in the plate
  (native eye waited on a tick; software path still painted
  the Sun; `reset_view` on a `_view_id` flap left the zone).
  Fixed. 03 is now the zone: space chips, fetching satellites,
  20000 km. Cesium Tool window is a sibling HWND —
  `panel.grab()` misses it; shot composites a **ready** host
  only. Wait used to bail when `_globe_host` was still `None`,
  so Enter frames were native-or-black. Wait now holds until
  `_globe_revealed` (GIBS tiles), not a 900 ms timer after JS
  boot. NASA disc + Earth chrome stay until tiles land. Enter
  nadir is the wall-clock subsolar, not 20°N 0°E at night.
- [x] **7.4** Live bands. Space bar is sats+ISS. City opens
  the rest. Scale reads 20000 km / 8 km. GIBS cite on the
  native/Cesium plate. City 8 km drapes OSM under GIBS /
  photoreal so it is not a pale z8 smear. VIIRS 404s do not
  cover Blue Marble.
- [x] **7.5** Find Tokyo. Gazetteer hit. 08.
- [x] **7.6** Ride ISS. 09: inspect card, copy view, simulated
  Kepler, Esc hops off. 502 km to surface.
- [x] **7.7** Leave Earth. 10: NASA disc, Enter offered again,
  Earth chips gone.
- [x] **7.8** Leave Reality. `dump_on_leave` under
  `outputs/physics/solar/<utc>/`. 11.
- [x] **7.9** Pixels that were lies, then fixed: Live … on a
  Live-off coast; Sun as Earth after Enter; silent Find miss;
  inspect "travel first" vs Enter button using different
  gates. Walk PNGs + `walk.mp4` under
  `outputs/earth_reality_pass/` (gitignored). HWND grab is
  `widget.grab()` / `grabWindow(winId)`, never
  `screen.grabWindow(0)`.
- [x] **7.10** Break pass (`scripts/shot_earth_break.py`,
  `tests/test_earth_break.py`). Enter from the Sun, double
  leave, Mercury kick, re-enter, Find garbage, ride ISS.
  Fixed what the pixels and the hunt actually broke: pending
  Enter after leave, travel-away under Cesium, GPU `view_id`
  reset, construct-fail `_cesium_off`, AIS Ohio `[]` wipe,
  last_fetch on a miss, tool goto 0,0, FIRMS MAP_KEY coverage.
  Enter no longer flashes a black “fetching satellites” beat;
  city is OSM/photoreal not a pale wash; space nadir is
  sunlit. Fetcher tests parse recorded USGS/OpenSky JSON
  through the real client path; optional live USGS behind
  `ARELIS_LIVE_EARTH=1`. Walks are still the live Cesium
  proof. ISS ride over Japan is the plate working. Walks:
  `outputs/earth_reality_pass/` and
  `outputs/earth_reality_break/` (gitignored).

Do not ask the human to launch Arelis as the test loop.

---

## Frozen the other way

Glass, chat UI, orchestrator, SMS, Allow, PDF lane, eval
floors, Settings model picker, companion APK. Closed in
`docs/roadmap/README.md`. Do not wander back. Do not
ruff-format the tree. Do not remount Drive. Do not widen
`policy.py`. Read `.cursor/rules/multi-agent-lanes.mdc`
before touching `conversation.py` or `launch.py`.

Still not this sitting: live glass boards (7.1 of the other
roadmap) against Ollama; unsigned SmartScreen; publishing the
installer draft; sideloading the companion APK.

Hard block: do not ship Cesium in the installer unless this
audit measures why and the human agrees.

Refusals (not leftover build): Unsecured / Insecam, global
face index, VIN-plate trackers, paid satellite AIS. VIIRS
boats / Earthdata GRD / Copernicus extra stay `later`.

`physhw/` is gitignored. Do not commit it. Never echo or
commit `data/secrets.yaml`. Do not commit unless asked.

---

## How to recover

If context dies: this file is the plan. Do not invent a new
one on top of it. Mark steps as you close them, including
where the ticket was wrong. The canvas is a view — rebuild it
from this markdown if it goes zero-byte again.

Handoff text lives in `docs/roadmap/earth-reality-handoff.md`.
