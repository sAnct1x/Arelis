# Location

Location is on by default. That lets her use a saved place for weather
and local sky times.

Turn it off by setting `location.enabled: false` in your local settings
file (`config.local.yaml` in the data folder).

With location off:

- She does not put your place in the prompt
- The location tool shares nothing and says location is off
- Your computer's country and time zone are not read for that tool
- The clock line in the prompt does not name the time zone or offset

A city you name in a weather question still gets a forecast. Your
saved city in `data/profile.yaml` is still used for weather and local
sky if you ask without naming a place.
