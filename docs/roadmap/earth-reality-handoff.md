# Handoff — same audit, Reality + Earth

Paste everything below the line into a new chat. The markdown
roadmap you write is the source of truth. The canvas is a view over
it. This file stays so a sitting that loses context can recover.

---

You are continuing Arelis. The daily-driver audit (tools, glass,
Allow, SMS, PDF, eval floors, 0.2.8) is **closed**. Do not reopen
it. Do not “clean up” glass/chat/orchestrator. Do not ruff-format
the tree. Do not thin Earth catalogs. Do not delete `earth_globe/`,
WebEngine host, or `choose_stack`. Never echo or commit
`data/secrets.yaml`. Do not commit unless I ask. Never call the
product God's Eye View. Earth is a zone. Room id is `physics`
(humans read **Reality**).

I am the only person on this checkout. Solo hobbyist. Daily driver
already ships as 0.2.9 locally; last published installer is the
draft until a human publishes it. 12 GB GPU. “Cost” means
compute / tokens / VRAM / latency, not money. Talk like a person
at this desk, not a ticket. Keep working until the plan is closed.
Do not ask me to launch Arelis as your test loop — you run the
walks, grabs, pytest, and scripts. I will test the plate myself
when you say the code is ready, the same way I did for glass.

## What we just finished, so you do not redo it

HEAD after the live-test pass is on `main`. Version is
**0.2.9**. Tag `v0.2.9` is the installer draft. 3D stays
checkout-only. Last daily-driver commit that closed 0.2.8:

- `105b0b8` Close the remaining roadmap: PDF raster lane, Allow
  holes, picker, SMS radio.
- `4237e47` Paint first-run TOOLS chips and stop the companion
  dying after a quiet week.

**Closed phases (0–7 of `docs/roadmap/README.md`):** eval floors +
choice board; PDF raster lane (pypdfium2, loud miss); Phase 2
**cancelled on measurement** (guards +6.0, full schema +1.0 vs ±2
at 2.4× prefill — do not restore descriptions); cleanup/dedup that
found wrong-person sends; tool depth; missing verbs; no general
shell (stay-absent); Settings model picker; scoped a11y; Allow
holes; SMS radio on cellular + background Allow + week-idle
rediscover; screenshot/video pass; nightly CI.

**Still not your job:** live glass boards (7.1) against Ollama;
unsigned SmartScreen; publishing the installer draft; sideloading
the companion APK (I do that). Those are human / this desk.

**The daily-driver sitting that ran this:**
[Daily driver audit](0cdf46b9-5fef-4dd4-b8ba-017cc7696f44).
Context died more than once. That is why the markdown roadmap is
checked in and the canvas is a view.

## How we approached everything — copy this method

This is the part that matters. The Earth/Reality work is not
“make the globe prettier.” It is the same audit.

1. **Full read first.** The last audit read `arelis/` (~170k) and
   `tests/` (~40k) before writing a plan. You read `arelis/earth/`,
   `arelis/physics/`, `arelis/spatial/`, the Reality UI plate
   (`world_window.py`, `solar_*`, `earth_globe/`, `earth_overlay.py`,
   `earth_marks.py`, `solar_gl.py`, `solar_paint.py`, `launch.py`,
   `globe_stack.py`), and every `tests/test_earth*`,
   `test_reality*`, `test_solar*`, `test_physics*` file. Numbers
   in the roadmap are measured on this checkout, not estimated.

2. **Two artifacts, immediately, before implementing.**
   - Checked-in markdown roadmap:
     `docs/roadmap/earth-reality.md` — source of truth. Numbered
     steps so a sitting can say “I did 3.14” and mean something.
   - Interactive canvas beside the chat (same shape as
     `arelis-audit.canvas.tsx`). The canvas is a view. If the
     canvas dies, the markdown still has the findings. We lost
     the audit canvas to a zero-byte write twice; the roadmap
     survived because it was in git.

3. **Execute immediately after the plan exists.** Mixed
   depth-then-gaps is fine. Cleanup before new features was the
   accepted order last time and it is the order again: safety net,
   then close in-flight lies, then measure any “this architecture
   is the wound” thesis before acting on it, then dedup/cleanup
   that is actually hiding wrong answers, then missing verbs,
   then usability, then a visual/receipt pass you run yourself.

4. **Do not trust existing tests.** Write tests that catch flaws
   and mutants. A helper with 100% coverage and unwired call
   sites is how we shipped wrong-person email. Disable the new
   guard; the suite must go red. A gate that is only ever
   observed passing needs a companion that proves it can fail.

5. **The roadmap is a lead, not a diagnosis.** Last audit was
   wrong about specifics eleven times (file counts, line ranges,
   “already fixed,” a path that did not exist) and still pointed
   at real places. Two of the wrong tickets sat on the worst
   bugs. **Read the code, then fix. Never fix from the ticket.**
   When the ticket is wrong, write that into the roadmap. Do not
   silently “correct” history.

6. **Measure before deleting a compensation layer.** The opening
   thesis of the last audit (“12,700 lines of regex are a wound;
   restore the full tool schema”) was confident and wrong.
   Thirteen runs, three seeds, shipped guards +6.0, full schema
   in the noise. We cancelled Phase 2 and kept the wrong thesis
   in the doc so nobody “cleans it up.” If you decide Cesium, the
   catalog, REBOUND, or the native disc is a wound, **measure
   it**. Do not rip it because it is large.

7. **Duplication is where defects hide.** When three modules
   express one rule and disagree, the odd one out is the bug.
   Earth will have this in fetchers, frames (ECEF vs ECLIPJ2000),
   enter/leave, park/unpark, and “Live off” vs “chip off.”
   Diff copies against each other.

8. **A comment that promises behaviour is not behaviour.**
   Re-read docstrings and `docs/earth.md` against the code.
   Every false claim last time had been true on the day it was
   written.

9. **`no test file` found a defect every time it was run.**
   Query which earth/physics/spatial modules no test names.
   Read those first.

10. **Fail loud, never empty.** Scanned PDFs used to return `[]`.
    Weather used to pick one Springfield. Inbound SMS used to say
    “no texts” when the bridge was dark. On Earth that shape is:
    a feed miss that paints nothing and looks like “this region
    has no planes,” a photoreal miss that sets `host.failed`, a
    leave that looks like enter, a catalog chip on that fetches
    nothing. Holes stay holes. Completeness is the anti-beacon —
    do not thin a region to hide a gap.

11. **You run the visual pass.** HWND grab via `widget.grab()` /
    `grabWindow(winId)`, never `screen.grabWindow(0)` — that
    paints Cursor through translucent glass. Isolated
    `ARELIS_DATA_DIR`. Do not enter Earth from a glass-only
    script unless Earth is the point of that shot. Stitch a
    walk video. Look at every frame. Fix what the pixels show.

12. **Stay in lane on shared files.** Surgical edits only on
    `docs/whats-new.md`, `docs/earth.md`, `solar_paint.py` HUD,
    `earth/__init__.py`. Do not remount Drive. Do not widen
    `policy.py`. Filament desk and voice/chrome sittings own
    those faces — read `.cursor/rules/multi-agent-lanes.mdc`
    before touching `conversation.py` or `launch.py`.

13. **Do not implement a cancelled phase.** If you cancel
    something after measuring, check the box cancelled and move.

14. **Talk like me.** Casual, direct, contractions. Swear when
    it is natural. No support-ticket voice. Technical accuracy
    stays high.

## Plans and canvases to read before you write a line

**Daily-driver audit (method + lessons, not your scope):**

- `docs/roadmap/README.md` — the closed 0–7 checklist. Read
  **The thesis — measured, and wrong**, Phase 3’s “roadmap is a
  lead,” the Frozen section, and the lessons. That is how we
  work.
- Canvas: `arelis-audit.canvas.tsx` (Cursor canvases folder).
  Headlines, lessons, verb table, open leftovers. Updated
  2026-09-18. If it is empty, trust the markdown.

**Earth / Reality — existing concept and production boards
(prior build campaigns, not this audit):**

- `docs/earth.md` — inventory + legal line. Zone not title.
  Labeled sim. Live replaces. Holes stay holes. 109 shipped /
  25 keyed / 3 later / 4 out. Stretch 1–8 of the year spine
  are **in the tree**. Later/out rows are refusals, not leftover
  build.
- `docs/rooms.md` — room id `physics`, humans read Reality.
  Earth is a zone inside Reality, not its own room.
- `docs/architecture.md` — Spatial / Earth / Physics table.
  Reality plate is source-checkout only (`world_stage_allowed`).
- `docs/whats-new.md` **Reality** paragraph — Cesium vs native
  GL contract, travel, Live bands.
- `docs/telemetry.md` — Reality receipts under
  `outputs/physics/`.
- Canvas: `reality-vs-concept.canvas.tsx` — concept thread
  closed. Inventory mix. Do not reopen that chat to decide a
  host.
- Canvas: `reality-production-plan.canvas.tsx` — GPU skip /
  park / chip-bar / trail / GIBS campaign, marked completed.
  Treat those items as “claimed done.” Your job is to **verify
  against the code and the pixels**, the same way we did not
  trust the tool tests.

**Lane rules (still in force):**
`.cursor/rules/multi-agent-lanes.mdc`

- Earth zone is Cesium; solar lab is native GL; **never both
  live.**
- Enter Earth destroys the offscreen context (`park()`), then
  mounts Cesium in a **child process** when solar GL was live.
- `globalShareContext()` survives park — do not construct
  `QWebEngineView` in the glass process next to that share
  group.
- Do not add `--disable-gpu` unless a share group is still
  present *and* Cesium is in-process.
- Leave Earth kills the child, then recreates solar GL.
- Native NASA disc is **fallback only** (no WebEngine, Cesium
  boot fail). A photoreal miss must not set `host.failed`.
- Do not “keep the native disc” as GPU cleanup. Do not delete
  this as dead code.
- Overlay tests stay Qt. They do not replace the Cesium planet.
- Pytest may construct WebEngine.
- Catalogs / egress: pin hosts. Do not thin a region.
- Physics `pause` outside a live Drive is a Reality verb.

**Hard block in code:**
`arelis/spatial/grant.py` `world_stage_allowed()` — installer
and wheels do not get the 3D plate. The Reality *room* still
exists there for chat, CAS, Horizons. Do not “fix” that by
shipping Cesium in the installer unless the audit measures
why and I agree.

## Your assignment

The same audit, now on **Reality + Earth + solar**. The last
roadmap froze this on purpose:

> `arelis/earth/` (~16k lines, 70 files), `arelis/spatial/`
> (~3.1k), `arelis/physics/` (~3.9k). 141 catalog feeds, a
> Cesium child process, a native GL solar lab. Coherent and
> well documented. Ships in no installer. 327 of 1,391 mypy
> errors. Thinnest per-fetcher test coverage in the tree.

That freeze is lifted **for you**, for this work only. Glass,
tools, orchestrator, SMS, Allow stay frozen the other way —
do not wander back.

Pains to treat as named complaints (verify, do not assume):

- Confidently / silently wrong: empty catalog looks like empty
  sky; wrong body; travel that does not arrive; enter/leave
  that leaves GPU in a hole; a receipt that lies.
- Slowness: Live on in space hammering every feed; GIBS;
  Cesium + solar GL both trying to live; prefix / VRAM on a
  12 GB card if you pull models into this sitting (you should
  not — this plate is not an LLM problem first).
- Wrong / missing verbs: travel, enter, leave, find, take me
  to, ride, track, Live on/off, dump, copy view.
- Shallow tools: `earth` / `solar` / rooms actions that
  advertise more than they do.
- Catalog honesty: keyed feeds that look shipped; later/out
  rows that still get fetched; a thinned region.

## Deliverables (same contract as last time)

1. **Now:** `docs/roadmap/earth-reality.md` + a canvas. Both.
   Roadmap is source of truth. Numbered phases. Keep a “thesis”
   section you are allowed to prove wrong.
2. **Then:** execute until the plan is closed. Update the
   roadmap as you go, including where the ticket was wrong.
3. **Visual pass you run:** enter Reality, travel, enter Earth,
   Live bands, Find / take me to a city, ride ISS, leave Earth,
   leave Reality. HWND grabs + a walk video under
   `outputs/` (gitignored). Look at the frames.
4. **Tests that would have failed before the fix.** Mutants.
5. **Docs:** `docs/earth.md`, `docs/whats-new.md` Reality
   paragraph, architecture table — surgical, after the code
   is true.
6. Do not commit unless I ask. Do not push unless I ask.

## Suggested phase shape (rewrite after you read)

This is a lead. Replace numbers after the full read.

- **0 — safety net.** Inventory tests vs fetchers. Mutant for
  “empty catalog looks like success.” Pin hosts. Pin
  enter/leave / park / child-process isolation. Wire anything
  that exists and is not in pytest.
- **1 — close in-flight lies.** `docs/earth.md` vs
  `feeds.FEEDS` vs chips vs what actually fetches. Photoreal
  miss vs `host.failed`. Native disc as fallback only.
- **2 — measure any “rip it” thesis.** If you want to kill
  Cesium, merge GL, or thin feeds, measure first. Cancel
  yourself if the numbers say no.
- **3 — cleanup / dedup.** Frames, park/unpark, enter/leave,
  trail vs ride vs track, Live vs chip. Diff copies. The odd
  one out is the bug.
- **4 — verb depth.** Travel, enter, leave, find, ride, track,
  dump, copy view, solar inspect. What the tool/schema
  promises vs what runs.
- **5 — missing verbs / honest holes.** Things a person at the
  plate asks for that have no home. Stay-absent is a valid
  close (we did that for a general shell).
- **6 — usability.** HUD copy, Find, Live-off default, band
  chip bar, receipts without stream URLs.
- **7 — you walk the plate.** Screenshots + video. Receipts.
  Notes in `docs/earth.md` / whats-new.

## Constraints that already cost us weeks

- Cesium and solar GL **never both live**. Child process for
  Cesium after `park()`. This is not optional polish.
- Do not thin a region. Do not add Unsecured / Insecam /
  global face index / VIN-plate trackers / paid satellite AIS
  — those are documented refusals on the concept board.
- Do not extend Earth into a second UI theme. Sodium HUD
  persists.
- Overlay Qt tests do not replace the Cesium planet.
- `physhw/` is gitignored student work. Do not commit it.
- Do not load `nomic-embed-text` mid-turn (12 GB). This
  sitting should barely touch Ollama.
- Windows. PySide6. Isolated data dir for any shot script.

## When you start

Read the files above. Write the roadmap and the canvas. Then
start Phase 0 without waiting for a typed “go.” Update me
when the plan exists and when something is actually closed,
not when you feel busy.

If context dies, recover from `docs/roadmap/earth-reality.md`
and this handoff. Do not invent a new plan on top of a live
one.
