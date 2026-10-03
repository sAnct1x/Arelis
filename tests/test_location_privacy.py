"""The saved place stays out of the model's prompt and out of visible reasoning."""

from __future__ import annotations

import logging

from arelis.core.world_state import world_state_prompt_line
from arelis.location import UserLocation
from arelis.location.privacy import (
    LocationLogFilter,
    LocationRedactor,
    StreamRedactor,
    install,
    prompt_detail,
)

PLACE = UserLocation(
    city="Exampleville",
    region="EX",
    country="US",
    postal_code="62701",
    timezone="America/Example",
)


def test_prompt_line_hides_the_place_by_default() -> None:
    line = PLACE.prompt_line("off") or ""
    assert "Exampleville" not in line
    assert "62701" not in line
    assert "America/Example" in line
    assert "user_location" in line
    # city keeps the city but never the postal code; full is the old line.
    city = PLACE.prompt_line("city") or ""
    assert "Exampleville" in city and "62701" not in city
    assert "62701" in (PLACE.prompt_line() or "")


def test_prompt_detail_defaults_off_and_world_state_follows() -> None:
    assert prompt_detail({}) == "off"
    assert prompt_detail({"location": {"privacy": {"prompt_detail": "bogus"}}}) == "off"
    off = world_state_prompt_line({"_location": PLACE}, role="fast", model="m")
    assert "Exampleville" not in off
    full_cfg = {"_location": PLACE, "location": {"privacy": {"prompt_detail": "full"}}}
    full = world_state_prompt_line(full_cfg, role="fast", model="m")
    assert "place Exampleville, EX 62701, US" in full


def test_stream_redactor_catches_a_city_split_across_chunks() -> None:
    redactor = LocationRedactor(lambda: PLACE)
    stream = StreamRedactor(redactor)
    chunks = ["Weather in Exam", "pleville for 99", "999 today, ", "then Exam"]
    out = "".join(stream.feed(c) for c in chunks) + stream.flush()
    assert out == "Weather in [location] for [location] today, then Exam"


def test_log_filter_scrubs_records_and_install_can_switch_off() -> None:
    install({"_location": PLACE})
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "near %s", ("Exampleville",), None)
    assert LocationLogFilter().filter(record)
    assert record.getMessage() == "near [location]"
    assert install({"_location": PLACE, "location": {"privacy": {"redact_display": False}}}) is None
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "near Exampleville", None, None)
    LocationLogFilter().filter(record)
    assert record.getMessage() == "near Exampleville"
