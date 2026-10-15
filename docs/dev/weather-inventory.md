# Weather path deletions

The forecast tool is one optional `place` argument. Code geocodes that string, keeps a named state or country, calls the forecast once, and returns one sentence. No place uses Windows location, then the saved home city, then IP geolocation. A named place skips those. None of the old turn guards below are on the path.

Deleted:

- Days retry after a short forecast
- Other-city nudge
- Phantom-home check
- Answer-now nudge after a forecast
- `_weather_answer_ready` tool strip
- Web search sentence that steered back to weather
- Confirm-phase sentence that named a weather tool
- Once-guard that blocked a second weather call and logged `weather_once` / `need_place`
- Repeated-weather end from #237, including the canned "I have the forecast" and "I couldn't save the brief" lines
- Weather failure auto-finish ("I couldn't get a forecast.")
- `days`, `hours`, and `past_days` on the model-facing schema
- First-hit geocode on the live tool (`place_query_for_geocode` stays for the email extractor only)
- Same-call finish set entry for weather

Kept, because a non-weather test fails without them:

- Owed-document hold in dispatch paste, `turn_round`, and `no_call_finish`
- Nudge cap inside that hold (`_MAX_TOOL_NUDGES`)
- `send_sms`, camera, and look once-guards, and the rule that a repeated block of those does not end the turn

Place extractors (`extract_weather_places`, `draft_weather_args`, `fill_weather_args`, `weather_wants_hourly`, `weather_wants_past`) stay for email briefing and the extractor tests. The live tool does not call them.
