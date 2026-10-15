# Weather path deletions

The forecast tool is one optional `place` argument. Code geocodes that string, keeps a named state or country from the geocoder row, and returns one sentence. A US place is City, State. Anywhere else is City, Country, using the geocoder's country name. A bare name with one clearly larger city is that city. No place uses Windows location, then the saved home city. IP geolocation runs only when `location.network.enabled` is on, and that switch ships off. A named place skips those. The model titles any file from the place in the forecast sentence. Code does not name the file. The model writes the reply. A lookup that finds no city says so. A timeout, a connection error, a 429, or a 5xx says the service could not be reached. None of the old turn guards below are on the path.

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

Removed comments (bug history and why-this-guard notes). What remains states an invariant:

- WeatherTool class essay: invented coordinates, the profile always winning, four descriptions of lat/lon
- Module line that named the forecast service and JS weather sites
- `weather_wants_hourly` paragraph about the force gate still asking for daily rows
- Hourly regex notes: a daily max cannot answer a clock time, tomorrow needs a wider window, past days had no route
- `fill_weather_args` note that a stuffed place name is not a second city in the ask
- `fill_weather_args` paragraph that a model count is never shrunk because the model knows better than the regex
- Dispatch count note that nothing ends the turn on weather (the #237 guard-count comment)
- Paste-path note that shipping the forecast used to end the turn before document
- No-call note that a document beside a weather ask is why a non-kind stays owed
- Compact catalog note measured on runs that called user_location first
- Plan note that `weather_force_call` owns the nudge
- Prepare note that research mode skips a forecast and that jobs used to default to research
- Turn-context note that the resolved label came from the last successful weather result
- Claims notes: a room file force-nudge, a page-warrant mail, and the research-role docstring that named the forecast service
- Intent note that a scheduled imperative never forced the forecast and then refused on a page warrant
- Briefing module line that the model is told to use the same service
- ResolvedPlace essay that a bare coordinate pair hid the wrong city, and the note that a disambiguation line on every forecast is noise
- `choose_geocode_hit` sentence that the first city is how a different city used to win
- Weather-wander note with the dated measurement of the wrong first tool
- Weather-wander test module note that repeated that measurement and the invented-coordinates story
