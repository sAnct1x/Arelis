# Weather handling inventory

Inventory of the assistant weather path before the one-path rebuild. No code changed in this commit.

Scope: routing, turn handling (`arelis/core/turn_*.py`, `no_call_finish.py`, and the helpers those files call), prompt text, `arelis/tools/weather.py`, and the place lookup in `arelis/briefing/weather.py`.

Method: `git log -S` for the symbol or the sentence, then the commit subject and any `(#NNN)` in that subject. Early history is one squashed checkout with no PR number. Those rows say so.

Not this path, and not in the rebuild: the Earth map layer named weather, filament desk animation state, and the morning briefing template that only formats a forecast it already has. The briefing still calls `resolve_place` / `geocode_place`, and that lookup is in here.

Known bug this inventory is here to pin: `Springfield, Illinois` resolves to Springfield, Missouri. `resolve_place` sends the whole string as the Open-Meteo `name` and keeps `results[0]`. The state or country the user named is never compared to `admin1` or `country`.

## Place lookup

### `arelis/briefing/weather.py` `resolve_place`

Geocodes a name against Open-Meteo, asks for five candidates, and returns the first one that has coordinates. The label is name, region, country. Other hits are stored as alternatives. It does not filter those hits by a state or country in the query.

Added in `6c24b42` (2026-09-17, `weather: say which place, and answer "when"`, no PR number). Before that, `geocode_place` asked for `count=1` and returned a bare lat/lon, and the tool printed the user's own string back, so a wrong Springfield was invisible. The fix made the wrong city visible. It did not start picking the city whose region matches the words the user said.

### `arelis/briefing/weather.py` `geocode_place`

Coordinates only. Briefing and the profile fallback use it. It calls `resolve_place` and drops the label.

Same commit as `resolve_place` (`6c24b42`). Kept so callers that have nowhere to show a label still compile.

### `arelis/briefing/weather.py` `fetch_forecast`

Builds the Open-Meteo forecast URL. `hours` trims from now. `past_days` asks for history. Daily rows start today, so yesterday had no route until this existed.

`hours` and `past_days` landed in `6c24b42`. The comment in that commit is the "whenever" half: a daily precipitation max cannot say if it rains at 3pm, and forecast rows do not include yesterday.

### `arelis/tools/weather.py` `WeatherTool.run` named-place branch

If the model passed `place`, geocode that string via `place_query_for_geocode` then `resolve_place`. Print the resolved label, not the typed string. If several cities matched, append `That name also matched: ...`. Set `data["ambiguous"]` when alternatives exist. Coordinates from the model are not a parameter.

The refusal of model coordinates is the original tool contract, first in `37c3b5b` (2026-08-15, repo squash, no PR). The class docstring records the later cleanup: `run` used to read latitude/longitude from kwargs, the profile always won, and a named place silently returned home weather. `6c24b42` added the visible label and the alternatives line. `b3a8106` (#236) reads `ambiguous` from this payload in the phantom-home guard.

### `arelis/tools/weather.py` `WeatherTool.run` home branch

No `place` argument: use the profile snapshot. If it has no coordinates, refresh, else geocode the profile city with `geocode_place` (first hit, no label). Failure text tells the user to set city plus lat/lon in the profile, or call `user_location`. It tells them not to pass coordinates to weather.

Home-without-geocoding-the-profile-city is the 0.2.9 fix in `f60aaf9` (2026-09-21, `Ship 0.2.9: weather for here...`, no PR number). Release note: tomorrow with no city uses the profile location and does not geocode that city into the first gazetteer hit.

### `arelis/tools/weather.py` `place_query_for_geocode`

If the last tokens are a US state name, put a comma back in front of them. `Springfield Illinois` becomes `Springfield, Illinois`. Extraction drops commas, and the comment says the gazetteer does not answer the no-comma form.

Added in `72ac2f8` (#165, `Fix 9B tool misses, and use the saved place the same way for weather and sky`). The comma does not fix the Missouri bug. `resolve_place` still ignores the state.

### `arelis/tools/weather.py` `weather_place_key`

Fold case, drop punctuation, and shorten a trailing US state name to its abbreviation so `Baltimore, OH` and `baltimore ohio` compare equal.

First in `91e8479` (2026-08-19 checkout, no PR). Used by the once-per-place guard and by `weather_places_missing`.

## Place extraction and argument rewrite

These functions parse the user sentence with regular expressions and word lists. After #234 removed the force inject, the live turn does not call `draft_weather_args` or `fill_weather_args`. Tests still do. `weather_places_missing`, `extract_weather_places`, `weather_place_key`, and `weather_wants_beyond_today` are still called from the turn.

### `extract_weather_places`

Pull up to four city-ish strings out of the ask. Strip tool instructions, dates, weekdays, and a large noise list (`weather`, `tomorrow`, `please`, and so on). Split on `and` / `or`. Treat here / home / outside as the empty place (profile). Drop leftovers that fail `_is_place_candidate`.

First in `91e8479`. `f60aaf9` (0.2.9) stopped `to morrow` counting as a place via `normalize_weather_ask`. `b3a8106` (#236) uses the empty result in the phantom-home check.

### `weather_places_wanted` / `weather_places_missing`

Wanted places, or `[""]` when the extractor found none (meaning home). Missing is wanted places whose key is not in the success set or the failure set.

First in `91e8479`. Failure keys arrived in `f60aaf9` so a city that already failed is not asked for again.

### `extract_weather_place`

First non-empty city from `extract_weather_places`, else empty for home.

Same era as the extractor (`91e8479`).

### `weather_wants_beyond_today`

True when the ask mentions tomorrow, the weekend, next weekday, or a month-day.

First in `91e8479`. Live caller: the days retry in `execute_call`.

### `weather_wants_hourly` / `weather_wants_past`

Hourly window (12 today, 36 if tomorrow plus a time of day) or one past day, from phrase lists (`at 3pm`, `this afternoon`, `yesterday`, `last night`).

Added in `6a9898b` (2026-09-17, `weather: route the time-of-day ask to the hourly rows`, no PR). The commit says the force gate built the call with `draft_weather_args`, so a new `hours` parameter never fired until the extractor asked for it. #234 removed that inject. Nothing in the turn calls these two anymore.

### `draft_weather_args`

Args for an injected weather call: `days=3`, plus place, hours, and past_days from the extractors.

First in `91e8479`. Hourly and past fields in `6a9898b`. No production caller after #234.

### `fill_weather_args`

Drop invented coordinate keys. If the extractor found no city, delete `place` so a stuffed profile city is not geocoded. If the model omitted place but the extractor found one, copy it. If days is under 2 and the ask is beyond today, bump days to 3. Only widen hours and past_days.

First in `91e8479`. The home-place strip is the 0.2.9 behavior (`f60aaf9`): the model stuffing `place=Baltimore` on a home ask geocoded Maryland first. Comment in `execute_call` still says `fill_weather_args` usually bumps days before the call. That call site is gone. Only tests call it.

### `WeatherTool._int_arg` and the days parse in `run`

A non-integer `days` / `hours` / `past_days` falls back instead of raising. The 9B passes `days="today"`.

Days fallback is original tool behavior. `_int_arg` came with the hourly work in `6c24b42`.

## Turn handling: guards, retries, nudges

### `arelis/core/turn_execute.py` `execute_call` weather failure

On a failed weather call with a place argument, add that place key to `ctx.weather_failed_places`.

`weather_failed_places` first appears in `f60aaf9` (0.2.9).

### `arelis/core/turn_execute.py` `execute_call` days retry

After a successful weather call, if days was under 2, the ask wants beyond today, and this place has not been retried, do not mark the place done. Append a user line: call weather again with `days=3` (and the same place). One retry per place (`weather_days_retried`).

The sentence `That reading is today only` first appears in `91e8479`. Telemetry action `retry_days` is the same block.

### `arelis/core/turn_execute.py` `execute_call` other-city nudge

If this batch has no later weather call and `weather_places_missing` is non-empty, append a user line telling the model to call weather for the next city, or with no place for home. Do not mark the turn ready to answer.

The "do not stop after the first city" behavior is the two-city work in `91e8479`. The comment about a two-city fanout leaving a stale user line (9b re-calls until `max_rounds`) is why `later_weather` skips the nudge. `later_weather` is computed in `dispatch_calls` as "another weather call is still in this batch".

### `arelis/core/turn_execute.py` `execute_call` phantom-home guard

If the result is ambiguous, the call had a place, the extractor found no city, and missing is only home, clear missing. Springfield resolved to one gazetteer label, the ask text yielded no place, and `weather_places_missing` reported home. That is not a second city. Telling the model to call weather again blocked every later round.

Added in `b3a8106` (#236). The test is `test_flag_off_need_place_blocked_weather_still_runs_document`.

### `arelis/core/turn_execute.py` `execute_call` answer-now nudge

If nothing is missing and no later weather call is in the batch, append: you already have a successful weather result, answer in plain prose, do not call weather again. Do not remove weather from the schema list in this round. A shorter list re-prefills the prefix. The next round offers no tools via `_weather_answer_ready`.

The "answer from the reading" line is in the initial squash `37c3b5b`. The "do not strip the schema this round" comment is the prefix-cache fix. `_weather_answer_ready` first appears in `5f41e93` (2026-10-01 refactor, no PR).

### `arelis/core/turn_execute.py` `execute_call` weather_once mark

Timer mark `weather_once` with action `retry_days`, `batch`, `need_place`, or `answer_now`. `need_place` is true when `weather_places_missing` is non-empty, including the phantom-home case, because the mark recomputes missing after the phantom clear is only applied to the local list used for the nudge. The #236 test asserts `need_place` on the ambiguous Springfield fixture.

`weather_once` first appears in `37c3b5b`.

### `arelis/core/turn_execute.py` `execute_call` plain-user pin skip

Successful tools pin a plain user line. Weather does not (`name != "weather"`). Weather has its own answer nudge instead.

Lives next to the weather block in `execute_call`. The pin helper is general. The weather exception is the special case.

### `arelis/core/turn_execute.py` `execute_call` web_search fail redirect

If `web_search` fails and exactness or expected tools say weather, append "call weather, do not web_search again" onto the replan notice.

First in the initial squash (`37c3b5b` has the sentence `Call the weather tool for the forecast`). The current wording is the weather branch of the general fail replan.

### `arelis/core/turn_dispatch.py` `dispatch_calls` duplicate weather fetch

Before the call runs: if this place key is already in `weather_ok_places`, do not run it. Return a tool result that says the call did not run, name `weather_resolved_place` when set, and say to use that result or ask the user once. Count it with `_record_block`. Trace: `duplicate fetch blocked`.

The block itself is in the initial squash `37c3b5b` (trace string `duplicate fetch blocked`). The "did not run" tool result and the resolved-place sentence were added in `b3a8106` (#236). Before that, a weather retry after `need_place` vanished, and every later retry spent a step until the turn hit the limit.

### `arelis/core/turn_dispatch.py` `dispatch_calls` repeat-block end

If the round ran zero calls, every name it blocked has a guard count of at least 2, finish the turn with the last successful tool output (or "This {tool} call did not run.").

Added in `b3a8106` (#236) for the weather retry. It is not weather-only. `_record_block` also runs for: web_search after SMS, web_search of a known contact, duplicate `send_sms`, extra SMS body, duplicate `send_email`, duplicate agenda create, look grant block, camera look cap, workspace tool-cache, scrape/web_fetch URL not in hits, page budget, duplicate URL, browser open-a-hit-first, search budget, duplicate search query, empty peek, duplicate image generate, same-call, and "repeat held for the file". A second block of any of those now ends the turn. Pre-#236 they only injected a tool message and continued.

### `arelis/core/turn_round.py` `_weather_answer_ready`

True when at least one place succeeded and `weather_places_missing` is empty. A days retry or a still-missing city leaves tools up.

First in `5f41e93` (2026-10-01). Called from `run_round` on round 2 and later, together with SMS sent, agenda done, calculator done, and the write nudges. When it is true and `close_tools_after_progress` agrees, the round offers no tools (`plain_only`).

### `arelis/core/turn_round.py` `run_round` tool strip

The condition above. Comment: the native flag drops regex injects, not the "user named these tools" hold. `close_tools_after_progress` (`turn_scratch.py`) returns false when exactness kinds are missing or a named tool is still owed, so a document still owed after weather keeps the menu. That interaction is what C02 depends on.

`close_tools_after_progress` is general. The weather arm of the condition is `_weather_answer_ready`.

### `arelis/core/turn_confirm.py` `confirm_call` repeat-fail note

After the same arguments fail twice, the user line says stop calling that tool. If weather is expected, still in the schema, and not yet used, it adds "Call the weather tool for the forecast instead."

Sentence first in `37c3b5b`. This fires for whatever tool failed twice, and the weather clause is the special case.

### `arelis/core/turn_prepare.py` closing chitchat

`looks_like_closing_chitchat`: drop weather and web_search from available, visible, and expected tools. Short thanks or bye must not revive a weather tool.

First in `37c3b5b`. The helper lives in `utterance_guards.py` `looks_like_closing_chitchat`.

### `arelis/core/turn_prepare.py` fresh-page veto

If exactness needs weather, or weather is expected and search/scrape are not, do not arm scrape-after-search. Comment: "weather today" must not arm scrape-after-search.

Lives in `prepare_turn`. The research-role exception next to it is `apply_research_web_need` (below).

### `arelis/core/turn_context.py` weather fields

`weather_ok_places`, `weather_failed_places`, `weather_days_retried`, `weather_resolved_place`, `weather_nudge_used`, `weather_preinject`, `guard_block_counts`.

`weather_ok_places` and `weather_days_retried` date to `91e8479` (moved onto the turn object in `ddaa6db`, 2026-08-20). `weather_failed_places` is `f60aaf9`. `weather_resolved_place` and `guard_block_counts` are #236. `weather_nudge_used` is the initial squash. Nothing increments it anymore (last touch `9be3197`, #234, when the force nudge went away). `weather_preinject` is copied through scratch and is always `None`. #234 removed the inject that used to fill it.

### `arelis/core/same_call.py`

Weather is in `_SKIP_TOOLS`, so the generic same-args gate does not own a weather repeat. The place key guard does. Weather is also in `_FINISH_ON_REPEAT`, so if some other path did call `same_call_finishes_turn("weather")`, the prior output would ship as the chat line. The skip means that path does not see weather today.

`_SKIP_TOOLS` including weather is the "another gate already owns the repeat" comment. `_FINISH_ON_REPEAT` lists weather beside calculator, browser, and agenda.

### `arelis/core/read_fanout.py` `_distinct_weather_places`

Two weather calls in one round may fan out when each names a different place. A second weather call after weather already ran this turn does not fan out. Expected weather (or SMS, email, agenda) also keeps the round serial when a redirect might fire (`_REDIRECT_EXPECTED`). The redirect itself was removed in #234. The fanout special case remains.

`_distinct_weather_places` first appears in `91e8479`.

### `arelis/core/failure_copy.py` weather passthrough

`chat_followup_from_tool` returns the weather output as the answer instead of treating the key:value lines as a data dump. Weather is in `_SPOKEN_TOOL_OUTPUT`.

This is how a forecast can be spoken without a second model pass. Not a retry. It is the "give the forecast in plain words" behavior the rebuild wants to keep, in a shared helper.

## Owed-tool holds that involve weather

### `arelis/core/no_call_finish.py` `run_finish_steps` / `_still_owed`

When the model answers with no tool call, hold the turn if a tool the user named has not run and still has no evidence. Nudge cap is `_MAX_TOOL_NUDGES` (2). Negated names are dropped.

The comment names the weather case: document beside a weather ask. Exactness only tagged weather, so document is not an evidence kind on this turn and stays owed until the tool runs. That is C02 / P09. Added in `b3a8106` (#236) because with the native flag off the hold never ran, and a weather-then-document turn ended when the model asked a question instead of calling document.

The hold is not weather-specific. Weather is the bench case that forced it on with the flag off.

### `arelis/core/turn_scratch.py` `named_tools_owed` / `close_tools_after_progress`

Owed names come from tools the user named that have not run. `close_tools_after_progress` refuses to take the menu away while any of those names, or any missing exactness kind, is still open. Weather success therefore does not strip tools when document is still owed.

The #236 commit message: "a weather-then-document turn ended when the model asked a question instead of calling document."

### `arelis/core/evidence.py` weather warrant

A successful weather call records kind `weather`. Exactness then treats the forecast as warranted. A missed weather call can still refuse with the evidence floor.

Weather as an evidence kind is original (`37c3b5b` era claims). The ledger branch for `name == "weather"` is the record site.

## Routing

### `arelis/core/intent_catalog.py` `WEATHER` and `weather_intent_matches`

`_WEATHER_PRE` matches weather, forecast, temperature, how hot, how cold, rain, snow, umbrella, degrees outside, humid. `_WEATHER_EXACT` matches question shapes plus imperatives (`get the forecast for ...`) so a 9am weather email counted. `_WEATHER_SPEC_VETO` rejects operating temperature, room temperature, kelvin, and similar device wording. `weather_intent_matches` is false when this turn can call `data_cell` and the ask names a room data file.

The spec veto is `3555e9a` (2026-09-05, `core: close live-board holes...`, no PR). The imperative patterns exist so a scheduled forecast was not tagged as a web page and then refused. The data-cell veto is `fcbd78e` (#169): a room file saying temperature was stealing the weather preflight, and the force nudge ran after `data_cell` had already printed the table.

`WEATHER.nudge` is the preflight sentence: call the weather tool now, place is a name, days includes today, do not scrape. `WEATHER.schema_tools` is weather, user_location, web_fetch. `expected_tools` is weather.

### `arelis/core/preflight.py` `detect_intent_hints`

Weather hints go through `weather_intent_matches` instead of the raw pattern. A research hint drops the weather hint. A scheduled-send hint drops weather, compose_email, and sms_send so a job title is not this-turn weather. A data-cell offer drops weather and analyze when the ask is a room file (`offer_data_cell` false leaves them alone).

The scheduled-send drop is the "those run when the job fires" nudge in the same file. The data-cell drop is #169.

### `arelis/core/claims.py` `detect_exactness_need`

`needs_weather` comes from `exactness_match("weather", text)`. Cleared when the sentence is a temperature scale with no today/tomorrow/tonight/outside/forecast/weather. Cleared when data_cell is on and the ask names a room file. If both web and weather match, web is cleared so a missed forecast is not refused for lack of a page warrant (the 9am mail bug).

The web-vs-weather clear and the research exception below are the job-defaulted-to-research bug. The data-cell clear is #169, same comment as the intent veto: the hour question names a room file and the word temperature.

### `arelis/core/claims.py` `apply_research_web_need`

Research mode adds a page warrant except when the need is already weather, CAS, or calculator. Jobs used to default to role research, which stamped web onto a forecast and the 9am mail was a page-warrant refusal.

### `arelis/core/claims.py` `weather_force_notice`

One-shot sentence: call the weather tool, place is a name, tomorrow needs days of 2 or more, do not web_search or scrape, do not invent a forecast.

Defined since `37c3b5b`. No caller after `9be3197` (#234) removed the force gates. Dead text.

### `arelis/core/turn_goal.py` `derive_turn_goal`

If exactness says weather, or the weather kind is set and this is not research, the goal is weather. Line: "A weather-tool forecast for the place they named." Need weather. Forbid web_search, scrape, web_fetch, research_report, browser. SMS and email goals forbid weather. Research goal forbids weather. Browser goal forbids weather. `receipt_serves_goal` for a weather goal is true only when the tool name is weather.

The line first appears in `13a1ee2` (2026-09-05). `append_turn_goal` in `prompt_sections.py` writes it into the prompt and rewrites `_expected_tools` via `apply_goal_to_expected`. Research-beats-weather is the "temperature-word false lock" docstring.

### `arelis/core/plan_nudge.py` `_PLAN_WEATHER`

Plan text: call the weather tool for the user's place, then answer only from the tool result. `skip_progress=True` with the comment that `weather_force_call` owns the nudge. `select_plan` returns this plan when weather is in kinds or skills.

Plan spec is in the initial squash `37c3b5b`. `weather_force_call` was removed in #234. The skip flag and the comment remain, so this plan does not also fire a progress nudge.

### `arelis/core/agent_loop.py` `_hide_daily_wander` / `_WEATHER_WANDER`

On a weather expected set, hide web_search, scrape, web_fetch, and user_location. On SMS, email, or agenda, also hide weather unless weather is expected. A local-store turn hides weather. A weather turn hides send_sms and send_email when those are not expected.

`user_location` was added to `_WEATHER_WANDER` in `6203c8b` (2026-09-17, `fix: stop the weather turn sending her to look up where you are`, no PR). Hiding search pushed the model onto user_location. Weather refuses coordinates, so that round cannot help. `cd41d24` the same day made the hide set and the redirect set agree for local-store turns. The redirect module is gone after #234. The hide remains, and `apply_expected` in `tool_surface.py` still calls it. The comment there still says "the weather narrowing".

### `arelis/core/tool_subset.py` `SKILL_TOOLS`

Weather skill offers weather, user_location, and web_fetch. Location skill offers user_location and weather. Research extras include weather.

This is the schema narrowing for a weather skill card, not a turn guard.

### `arelis/core/route_hints.py` `TOOL_LOOP_HINT`

The word weather or forecast in the ask is one reason to stay on the fast tool loop instead of a long research model. The module docstring says it does not pick the model by itself.

### `arelis/core/loop_helpers.py` escalate skip

`should_escalate` does not escalate a fast turn to the research model when expected tools include weather (also analyze, SMS, email, agenda). Comment: every turn after round 2 used to escalate to 14B and pin VRAM.

Weather is one name in that set, first in the loop-helper split.

### `arelis/core/email_complete.py` `looks_like_standard_briefing`

A canned morning digest may mention weather. If `extract_weather_places` finds a named city, it is not the standard briefing (that one is home weather plus mail). A custom job goes to `schedule(action=create)` instead of `create_briefing`.

Uses the weather place extractor as a routing rule for jobs.

### `arelis/core/intent_catalog.py` `data_cell_should_reject`

Rejects a weather call when the ask explicitly names a room data file and data_cell is available. Same #169 rule as the intent veto, on the call itself.

### `arelis/core/intent_catalog.py` `should_inject_saved_place`

Does not inject `user_location` when `weather_intent_matches`. Weather resolves its own place.

Same reason as `6203c8b`.

## Prompt text about weather

### `arelis/tools/weather.py` `WeatherTool.description` and the place parameter

Tells the model: Open-Meteo, default is the profile, place is a name this tool geocodes, never coordinates, days includes today, tomorrow needs 2 or more, default 3, hours for a time of day, past_days for yesterday, do not scrape AccuWeather or weather.com. Place example is `Lyon, France`.

The example city changed in `e578c0c` (#218, `Stop the weather schema from naming the bench city`). It used to say Springfield, Illinois, which is the city in matrix items S16, C02, and C22, so the schema hinted the bench answer. Lyon is not on the bench. Worst-profile token count stayed 7392 because parameter descriptions are stripped before the tools array is built.

### `arelis/core/compact_prompt.py` catalog and policy lines

Weather catalog line: forecast, defaults to the user's place, omit place for home, never look up their location first, place is a city name not coords. Policy line: call the weather tool, not search, not scrape, place is a name, two cities means two calls. Location line: do not call user_location before weather. data_cell lines say "not weather".

The two-cities policy line first appears in `8393e6f` (2026-08-31, `0.2.5 ships a 5,500-token prefix...`, no PR). The "never look up their location first" clause is the `6203c8b` fix written into the prompt (`user_location` comment in this file cites that bug).

### `arelis/core/skills.py` weather card

Hints: weather, forecast, temperature, rain, snow, humid, how hot, how cold, umbrella. Body: call weather, do not scrape forecast sites, do not hand-build Open-Meteo URLs, omit place for home (a city name geocodes the first gazetteer hit), never pass coordinates, days rule, two named cities means one call each.

Card is in the initial squash. The "do not pass the profile city" sentence is the 0.2.9 home-place bug (`f60aaf9`).

### `arelis/core/skills.py` schedule card

"every single morning" and show/delete automations are schedule, not weather or send this turn. A word in a job title is not this-turn weather.

Routing sentence in the schedule skill, paired with the preflight drop of weather hints on a scheduled send.

### `arelis/core/lessons.py` `weather-not-scrape`

Seed lesson, tag weather: use the weather tool only, never AccuWeather, weather.com, or hand-built Open-Meteo URLs.

Initial squash `37c3b5b`. Injected when the weather tag matches the turn.

### `arelis/tools/web.py` `WebFetchTool.description`

"For weather, prefer the weather tool over hand-built Open-Meteo URLs."

Initial squash `37c3b5b`.

### `arelis/tools/scrape.py` `ScrapeTool.description`

"Do not use this for weather, call the weather tool instead."

Initial squash `37c3b5b`.

### `arelis/tools/research_report.py` `ResearchReportTool.description`

"Do not use for weather, SMS, email, or a single known URL."

Initial squash `37c3b5b`.

### `arelis/core/turn_goal.py` goal line

"A weather-tool forecast for the place they named." Written into the system tail by `append_turn_goal` when the goal kind is weather.

### `arelis/core/plan_nudge.py` plan message

"Plan: 1) Call the weather tool for the user's place. 2) Answer only from the tool result."

### Preflight nudge string on `WEATHER`

"Intent preflight: this message asks about weather. Call the weather tool now. ..."

Still attached when `detect_intent_hints` emits a weather hint and preflight guidance is appended in `turn_prepare`.

## What #234 already removed

`9be3197` (#234) removed the regex intent router, the preinjects, the wander redirects, and the finish force gates. Confirm cards, send locks, and the honesty floor stayed. Left behind, and still in the tree:

- `weather_force_notice` with no caller.
- `weather_nudge_used` with nothing writing it.
- `weather_preinject` always `None`.
- `draft_weather_args` and `fill_weather_args` only reached from tests.
- `weather_wants_hourly` and `weather_wants_past` only reached from those two.
- `_PLAN_WEATHER.skip_progress` still comments that `weather_force_call` owns the nudge.
- `read_fanout` still treats weather as a redirect risk, and the redirect is gone.
- `execute_call` still comments that `fill_weather_args` usually bumps days before the call.

## Bench cases this path is carrying

- S18 and S27 are memory and sql evidence, not weather. They landed in the same #236 commit as the owed-tool hold. They must keep working. They are not weather guards.
- C02 and P09 are weather, then write a document brief. Live failure: weather ran, document was stripped or the model asked a question, and no file was written. Tests: `test_weather_document_chain` in `tests/test_loop_chain_regression.py`, and the flag-off owed-document tests in `tests/test_named_tools_owed_native.py`. The turn must still reach document and must not finish on the tool-step limit.
- The ambiguous Springfield fixture in that file (`need_place`, second weather call does not run, document still runs) is the #236 once-guard case.
- S16, C02, and C22 ask for Springfield, Illinois. #218 exists so the schema does not contain that city. The Missouri resolution bug is separate and still open.
