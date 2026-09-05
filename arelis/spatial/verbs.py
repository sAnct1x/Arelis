"""Closed physics-room verbs. Tiny decoder, no turn, no 9B.

Whole utterance only. In orbit these words are English.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

PhysicsVerb = Literal[
    "heavier",
    "lighter",
    "freeze",
    "unfreeze",
    "undo",
    "pause",
    "resume",
    "step",
    "faster",
    "slower",
    "realtime",
    "hour",
    "day",
    "year",
    "fly",
    "inspect",
]

_HEAVIER = re.compile(
    r"(?i)^\s*(?:make (?:it|this|that) )?(?:heavier|heavy)\s*[.!]?\s*$"
)
_LIGHTER = re.compile(
    r"(?i)^\s*(?:make (?:it|this|that) )?lighter\s*[.!]?\s*$"
)
_FREEZE = re.compile(
    r"(?i)^\s*(?:freeze(?:\s+it)?|hold still)\s*[.!]?\s*$"
)
_UNFREEZE = re.compile(
    r"(?i)^\s*(?:unfreeze(?:\s+it)?|thaw)\s*[.!]?\s*$"
)
_UNDO = re.compile(r"(?i)^\s*(?:undo(?:\s+that)?)\s*[.!]?\s*$")
_PAUSE = re.compile(
    r"(?i)^\s*pause(?:\s+(?:it|the\s+(?:sim(?:ulation)?|lab|solar\s+system)))?"
    r"\s*[.!]?\s*$"
)
_RESUME = re.compile(
    r"(?i)^\s*(?:resume(?:\s+it)?|unpause|play(?:\s+the\s+sim(?:ulation)?)?)\s*[.!]?\s*$"
)
_STEP = re.compile(r"(?i)^\s*step(?:\s+once)?\s*[.!]?\s*$")
_FASTER = re.compile(
    r"(?i)^\s*(?:faster|speed\s+up(?:\s+time)?|go\s+faster|"
    r"increase\s+(?:the\s+)?(?:speed|rate)|speed\s+time\s+up)\s*[.!]?\s*$"
)
_SLOWER = re.compile(
    r"(?i)^\s*(?:slower|slow\s+down(?:\s+time)?|go\s+slower|"
    r"decrease\s+(?:the\s+)?(?:speed|rate)|slow\s+time\s+down)\s*[.!]?\s*$"
)
_REALTIME = re.compile(
    r"(?i)^\s*(?:real\s*time|realtime|1x|real[- ]time)(?:\s+speed)?\s*[.!]?\s*$"
)
_HOUR = re.compile(
    r"(?i)^\s*(?:one\s+|an\s+)?hour(?:\s+(?:per|a)\s+second)?\s*[.!]?\s*$"
)
_DAY = re.compile(
    r"(?i)^\s*(?:one\s+|a\s+)?day(?:\s+(?:per|a)\s+second)?\s*[.!]?\s*$"
)
_YEAR = re.compile(
    r"(?i)^\s*(?:one\s+|a\s+)?year(?:\s+(?:per|a)\s+second)?\s*[.!]?\s*$"
)
_FLY = re.compile(
    r"(?i)^\s*(?:fly|craft|pilot|board)\s*[.!]?\s*$"
)
_INSPECT = re.compile(
    r"(?i)^\s*(?:inspect|look|orbit\s+view)\s*[.!]?\s*$"
)
_RESET_VIEW = re.compile(
    r"(?i)^\s*(?:reset(?:\s+the)?\s+view|back\s+up)\s*[.!]?\s*$"
)
_ENTER_EARTH = re.compile(
    r"(?i)^\s*(?:enter\s+earth|earth\s+zone|go\s+into\s+earth)\s*[.!]?\s*$"
)
_LEAVE_EARTH = re.compile(
    r"(?i)^\s*(?:leave\s+earth|exit\s+earth|leave\s+the\s+earth\s+zone)"
    r"\s*[.!]?\s*$"
)
_RIDE_ISS = re.compile(
    r"(?i)^\s*ride(?:\s+(?:the\s+)?iss)?\s*[.!]?\s*$"
)
_TRAVEL_THERE = re.compile(
    r"(?i)^\s*(?:take\s+me\s+there|go\s+there|fly\s+there|take\s+me\s+to\s+it)"
    r"\s*[.!]?\s*$"
)
_TRAVEL_TO = re.compile(
    r"(?i)^\s*(?:take\s+me\s+to|go\s+to|fly\s+to|fly\s+me\s+to|travel\s+to)\s+"
    r"(?P<body>.+?)\s*[.!]?\s*$"
)
_GOTO_PLACE = re.compile(
    r"(?i)^\s*(?:"
    r"take\s+(?:me|us)\s+to|go\s+to|fly\s+(?:me\s+)?to|"
    r"show\s+me|visit|head\s+to|bring\s+me\s+to|let'?s\s+go\s+to|"
    r"zoom\s+to|fall\s+toward|i\s+want\s+to\s+see"
    r")\s+(?P<place>.+?)\s*[.!]?\s*$"
)
_TAKE_HOME = re.compile(
    r"(?i)^\s*(?:take\s+(?:me|us)\s+home|go\s+home|fly\s+home)\s*[.!]?\s*$"
)
_INSPECT_BODY = re.compile(
    r"(?i)^\s*(?:inspect|look\s+at)\s+(?P<body>.+?)\s*[.!]?\s*$"
)
_NOT_BODY = re.compile(
    r"(?i)https?://|www\.|\.com\b|\.org\b|\.net\b|\.io\b|"
    r"\blogin\b|\bsign\s*in\b|\bcalendar\b|\bcamera\b|\bwebcam\b|\bweb\s*cam\b"
)
_ARTICLE = re.compile(r"(?i)^(the|a|an)\s+")

# Canonical overlay flags match H, the ⋯ tray, and solar action=toggle.
_OVERLAY_ALIASES: tuple[tuple[str, str], ...] = (
    ("gravity", r"gravity|gravitational\s+(?:field|wells?|potential)"),
    ("magnetic", r"magnetosphere|magnetic(?:\s+field)?"),
    ("wind", r"(?:solar\s+)?wind|parker(?:\s+spiral)?"),
    ("grid", r"grid"),
    ("osculating", r"orbits?|osculating(?:\s+orbits?)?"),
    ("trails", r"trails?"),
    ("lagrange", r"lagrange(?:\s+points?)?"),
    ("graphs", r"graphs?"),
)

_OVERLAY_UNION = "|".join(f"(?P<{name}>{pat})" for name, pat in _OVERLAY_ALIASES)
_OVERLAY_ON = re.compile(
    r"(?i)^\s*(?:show(?:\s+me)?|display|enable|turn\s+on|switch\s+on|"
    r"put\s+on)\s+(?:the\s+)?(?:"
    + _OVERLAY_UNION
    + r")\s*[.!]?\s*$"
)
_OVERLAY_OFF = re.compile(
    r"(?i)^\s*(?:hide|disable|turn\s+off|switch\s+off)\s+(?:the\s+)?(?:"
    + _OVERLAY_UNION
    + r")\s*[.!]?\s*$"
)
_OVERLAY_PUT_ON = re.compile(
    r"(?i)^\s*put\s+(?:the\s+)?(?:"
    + _OVERLAY_UNION
    + r")\s+on\s*[.!]?\s*$"
)
_OVERLAY_TURN = re.compile(
    r"(?i)^\s*(?:turn|switch)\s+(?:the\s+)?(?:"
    + _OVERLAY_UNION
    + r")\s+(?P<state>on|off)\s*[.!]?\s*$"
)

# Earth chips — same shape as overlays, so "show me the planes" is not a place.
_EARTH_LAYER_ALIASES: tuple[tuple[str, str], ...] = (
    ("flights", r"planes?|flights?"),
    ("satellites", r"satellites?|sats?"),
    ("iss", r"(?:the\s+)?iss"),
    ("tiles", r"streets?|roads?"),
    ("buildings", r"buildings?"),
    ("live", r"live(?:\s+feeds?)?"),
    ("drones", r"drones?"),
    ("vessels", r"vessels?|ships?"),
    ("weather", r"weather\s+layer|weather\s+radar"),
    ("cameras", r"cameras?"),
    ("traffic", r"traffic"),
    ("fires", r"fires?"),
    ("quakes", r"quakes?|earthquakes?"),
)
_EARTH_LAYER_UNION = "|".join(
    f"(?P<el_{name}>{pat})" for name, pat in _EARTH_LAYER_ALIASES
)
_EARTH_LAYER_ON = re.compile(
    r"(?i)^\s*(?:show(?:\s+me)?|display|enable|turn\s+on|switch\s+on)\s+"
    r"(?:the\s+)?(?:"
    + _EARTH_LAYER_UNION
    + r")\s*[.!]?\s*$"
)
_EARTH_LAYER_OFF = re.compile(
    r"(?i)^\s*(?:hide|disable|turn\s+off|switch\s+off)\s+(?:the\s+)?"
    r"(?:"
    + _EARTH_LAYER_UNION
    + r")\s*[.!]?\s*$"
)
_EARTH_LAYER_TURN = re.compile(
    r"(?i)^\s*(?:turn|switch)\s+(?:the\s+)?(?:"
    + _EARTH_LAYER_UNION
    + r")\s+(?P<state>on|off)\s*[.!]?\s*$"
)

_LOOK_SPACE = re.compile(
    r"(?i)^\s*(?:zoom\s+out(?:\s+to\s+space)?|pull\s+back(?:\s+to\s+space)?|"
    r"show\s+me\s+the\s+whole\s+planet|from\s+space)\s*[.!]?\s*$"
)
_LOOK_APPROACH = re.compile(
    r"(?i)^\s*(?:come\s+in\s+from\s+space|approaching)\s*[.!]?\s*$"
)
_LOOK_NEAR = re.compile(
    r"(?i)^\s*(?:get\s+closer(?:\s+to\s+the\s+ground)?|near\s+the\s+ground|"
    r"come\s+down\s+some)\s*[.!]?\s*$"
)
_LOOK_CITY = re.compile(
    r"(?i)^\s*(?:drop\s+into\s+the\s+city|over\s+the\s+city|city\s+level)\s*[.!]?\s*$"
)
_LOOK_STREET = re.compile(
    r"(?i)^\s*(?:(?:take\s+me\s+)?down\s+to\s+(?:the\s+)?streets?|"
    r"street\s+level)\s*[.!]?\s*$"
)

_TOY = frozenset({"heavier", "lighter", "freeze", "unfreeze", "undo"})
_TIME = frozenset(
    {
        "pause",
        "resume",
        "step",
        "faster",
        "slower",
        "realtime",
        "hour",
        "day",
        "year",
        "fly",
        "inspect",
    }
)


@dataclass(frozen=True)
class PhysicsAct:
    """One closed physics-room act. Not a model turn."""

    verb: str
    name: str = ""
    flag: str = ""
    on: bool | None = None
    page: str = ""

    def payload(self) -> dict[str, str | bool]:
        data: dict[str, str | bool] = {"verb": self.verb}
        if self.name:
            data["name"] = self.name
        if self.flag:
            data["flag"] = self.flag
        if self.on is not None:
            data["on"] = self.on
        if self.page:
            data["page"] = self.page
        return data


def classify_physics_verb(text: str) -> PhysicsVerb | None:
    """Return a closed verb, or None when this is ordinary talk."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _HEAVIER.match(raw):
        return "heavier"
    if _LIGHTER.match(raw):
        return "lighter"
    if _FREEZE.match(raw):
        return "freeze"
    if _UNFREEZE.match(raw):
        return "unfreeze"
    if _UNDO.match(raw):
        return "undo"
    if _PAUSE.match(raw):
        return "pause"
    if _RESUME.match(raw):
        return "resume"
    if _STEP.match(raw):
        return "step"
    if _FASTER.match(raw):
        return "faster"
    if _SLOWER.match(raw):
        return "slower"
    if _REALTIME.match(raw):
        return "realtime"
    if _HOUR.match(raw):
        return "hour"
    if _DAY.match(raw):
        return "day"
    if _YEAR.match(raw):
        return "year"
    if _FLY.match(raw):
        return "fly"
    if _INSPECT.match(raw):
        return "inspect"
    return None


def is_time_verb(verb: str) -> bool:
    return verb in _TIME


def is_toy_verb(verb: str) -> bool:
    return verb in _TOY


def speech_body_names() -> tuple[str, ...]:
    """Loaded system if any, else the IAU catalog. Tracers are not destinations."""
    try:
        from arelis.physics.runtime import get_system

        system = get_system()
    except Exception:
        system = None
    if system is not None:
        names = tuple(
            p.name for p in system.nbody.particles if not getattr(p, "tracer", False)
        )
        if names:
            return names
    from arelis.physics.constants import BODIES

    return tuple(b.name for b in BODIES)


def resolve_body(raw: str, names: Iterable[str] | None = None) -> str | None:
    blob = (raw or "").strip().strip(".,!?")
    blob = _ARTICLE.sub("", blob).strip()
    if not blob or _NOT_BODY.search(blob):
        return None
    folded = blob.casefold()
    pool = tuple(names) if names is not None else speech_body_names()
    hits = [n for n in pool if n.casefold() == folded]
    if len(hits) == 1:
        return hits[0]
    return None


def _overlay_flag(match: re.Match[str]) -> str:
    for name, _pat in _OVERLAY_ALIASES:
        if match.group(name):
            return name
    return ""


def match_overlay(text: str) -> tuple[str, bool] | None:
    """Canonical overlay flag and on/off, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    hit = _OVERLAY_TURN.match(raw)
    if hit:
        flag = _overlay_flag(hit)
        if flag:
            return flag, hit.group("state").casefold() == "on"
    hit = _OVERLAY_PUT_ON.match(raw)
    if hit:
        flag = _overlay_flag(hit)
        if flag:
            return flag, True
    hit = _OVERLAY_ON.match(raw)
    if hit:
        flag = _overlay_flag(hit)
        if flag:
            return flag, True
    hit = _OVERLAY_OFF.match(raw)
    if hit:
        flag = _overlay_flag(hit)
        if flag:
            return flag, False
    return None


def match_travel(text: str, *, names: Iterable[str] | None = None) -> str | None:
    """Body to fly the inspect camera to. Empty string means the inspect target."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _TRAVEL_THERE.match(raw):
        return ""
    hit = _TRAVEL_TO.match(raw)
    if not hit:
        return None
    body = resolve_body(hit.group("body") or "", names)
    if body is None:
        return None
    return body


def match_inspect_body(text: str, *, names: Iterable[str] | None = None) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None
    hit = _INSPECT_BODY.match(raw)
    if not hit:
        return None
    return resolve_body(hit.group("body") or "", names)


def match_earth_place(text: str) -> str | None:
    """A named Earth destination, or None. Bodies stay travel, not here."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _TAKE_HOME.match(raw):
        return "home"
    hit = _GOTO_PLACE.match(raw)
    if not hit:
        return None
    blob = (hit.group("place") or "").strip()
    if not blob or _NOT_BODY.search(blob):
        return None
    from arelis.earth.gazetteer import resolve_place

    found = resolve_place(blob)
    if found is None:
        return None
    return found.name


def _earth_layer_flag(match: re.Match[str]) -> str:
    for name, _pat in _EARTH_LAYER_ALIASES:
        if match.group(f"el_{name}"):
            return name
    return ""


def match_earth_layer(text: str) -> tuple[str, bool] | None:
    """Earth chip id and on/off, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    hit = _EARTH_LAYER_TURN.match(raw)
    if hit:
        flag = _earth_layer_flag(hit)
        if flag:
            return flag, hit.group("state").casefold() == "on"
    hit = _EARTH_LAYER_ON.match(raw)
    if hit:
        flag = _earth_layer_flag(hit)
        if flag:
            return flag, True
    hit = _EARTH_LAYER_OFF.match(raw)
    if hit:
        flag = _earth_layer_flag(hit)
        if flag:
            return flag, False
    return None


def match_earth_look(text: str) -> str | None:
    """Altitude band from a zoom ask, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    if _LOOK_SPACE.match(raw):
        return "space"
    if _LOOK_APPROACH.match(raw):
        return "approach"
    if _LOOK_NEAR.match(raw):
        return "near"
    if _LOOK_CITY.match(raw):
        return "city"
    if _LOOK_STREET.match(raw):
        return "street"
    return None


def classify_physics_act(
    text: str,
    *,
    names: Iterable[str] | None = None,
) -> PhysicsAct | None:
    """Closed physics-room act, or None when this is ordinary talk."""
    verb = classify_physics_verb(text)
    if verb:
        return PhysicsAct(verb=verb)
    overlay = match_overlay(text)
    if overlay:
        flag, on = overlay
        return PhysicsAct(verb="overlay", flag=flag, on=on)
    raw = (text or "").strip()
    if _RESET_VIEW.match(raw):
        return PhysicsAct(verb="reset_view")
    if _ENTER_EARTH.match(raw):
        return PhysicsAct(verb="enter_earth")
    if _LEAVE_EARTH.match(raw):
        return PhysicsAct(verb="leave_earth")
    if _RIDE_ISS.match(raw):
        return PhysicsAct(verb="ride_iss")
    layer = match_earth_layer(text)
    if layer:
        flag, on = layer
        return PhysicsAct(verb="earth_layer", flag=flag, on=on)
    look = match_earth_look(text)
    if look:
        return PhysicsAct(verb="earth_look", name=look)
    body = match_travel(text, names=names)
    if body is not None:
        return PhysicsAct(verb="travel", name=body)
    inspected = match_inspect_body(text, names=names)
    if inspected:
        return PhysicsAct(verb="inspect_body", name=inspected)
    place = match_earth_place(text)
    if place:
        return PhysicsAct(verb="goto_earth", name=place)
    from arelis.core.tile_complete import match_tile_intent, world_page_for

    hit = match_tile_intent(text)
    if hit and hit[1] == "world":
        action, _name = hit
        page = world_page_for(text)
        return PhysicsAct(verb="lab", page=page, on=(action == "open"))
    return None
