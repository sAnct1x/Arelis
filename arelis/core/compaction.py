"""Deterministic compaction helpers for a long chat's working set.

The model may write a short narrative of older turns. Exact numbers with
units, equations or LaTeX, code identifiers and decisions are extracted
here by regex so they survive word for word, even when the model omits
them, times out, or the fold is skipped. The archive keeps the original
messages; only the in-process working set shrinks.
"""

from __future__ import annotations

import re
from typing import Any

# Narrative from the model (or a short fallback line) stays within this.
MAX_SUMMARY_CHARS = 800
# Deterministic verbatim list. Items are complete or omitted, never cut mid-value.
MAX_VERBATIM_CHARS = 1200
MAX_VERBATIM_ITEMS = 24
MAX_VERBATIM_ITEM_CHARS = 400
# Combined pin injected as [earlier in this conversation: …].
MAX_COMPACTION_PIN_CHARS = 2000
# Token reserve so the pin plus its wrapper still fits after a fold.
# 2000 chars at ~4 chars/token, plus the wrapper, with slack.
SUMMARY_RESERVE_TOKENS = 640

COMPACTION_MARKER = "Earlier messages summarized"
COMPACTION_MARKER_NOTE = "compaction"
VERBATIM_HEADING = "Kept word for word:"
_FALLBACK_NARRATIVE = (
    "Earlier turns were summarized. Exact numbers, equations and decisions "
    "are listed below."
)

# One numeric token, shared by a lone quantity and by both ends of a range.
_NUM_TOKEN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
_SCI_TAIL = r"(?:\s*[×xX]\s*10\s*\^\s*[+-]?\d+)?"
_UNIT_TOKEN = r"(?:%|°[CFK]?|[A-Za-zµμ][A-Za-z0-9µμ/%^*_-]{0,16})"

# 12.4 km, 5kg, 3.8e8 m/s, 3.8 × 10^8 m/s, $1,200, 24%, 90 °C, 70 km/s/Mpc
# A leading sign is allowed only when it is not the hyphen in a range
# such as 12-15 km (lookbehind: not immediately after a digit or comma).
_NUMBER_WITH_UNIT = re.compile(
    rf"""
    (?:
        \$\s*
        [+-]?
        {_NUM_TOKEN}
      |
        (?<![\d,])[+-]?
        {_NUM_TOKEN}
        {_SCI_TAIL}
        \s*
        {_UNIT_TOKEN}
    )
    """,
    re.VERBOSE,
)

# 12-15 km, 12–15 km (en dash), 12—15 km (em dash), 12 to 15 km, $12-15k.
# Both ends share one unit or currency; a true negative stays a signed number.
_NUMBER_RANGE = re.compile(
    rf"""
    (?:\$\s*)?
    [+-]?
    {_NUM_TOKEN}
    {_SCI_TAIL}
    (?:\s*{_UNIT_TOKEN})?
    (?:
        \s*[-–—]\s*
      | \s+to\s+
    )
    (?:\$\s*)?
    [+-]?
    {_NUM_TOKEN}
    {_SCI_TAIL}
    \s*
    {_UNIT_TOKEN}
    """,
    re.VERBOSE | re.IGNORECASE,
)

_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# Longer names need an allowlist so "0 about" is not a quantity.
_UNIT_NAMES = {
    "ampere", "amperes", "angstrom", "angstroms", "atmosphere", "atmospheres",
    "au", "bar", "becquerel", "byte", "bytes", "celsius", "centimeter",
    "centimeters", "coulomb", "coulombs", "day", "days", "degree", "degrees",
    "ev", "fahrenheit", "farad", "farads", "foot", "feet", "ft", "g", "gb",
    "ghz", "gram", "grams", "hour", "hours", "hr", "hrs", "hz", "inch",
    "inches", "joule", "joules", "k", "kb", "kelvin", "kev", "kg", "khz",
    "kilogram", "kilograms", "kilometer", "kilometers", "km", "kpa", "kw",
    "lb", "lbs", "liter", "liters", "litre", "litres", "m", "mas", "mb",
    "meter", "meters", "metre", "metres", "mev", "mg", "mhz", "mi", "microgram",
    "micrograms", "micrometer", "micrometers", "micron", "microns", "mile",
    "miles", "milligram", "milligrams", "millimeter", "millimeters", "min",
    "minute", "minutes", "ml", "mm", "mol", "mole", "moles", "month", "months",
    "mpc", "ms", "mv", "mw", "n", "newton", "newtons", "nm", "ns", "oz", "pa",
    "parsec", "parsecs", "pascal", "pascals", "percent", "psi", "rad", "radian",
    "radians", "s", "sec", "second", "seconds", "sr", "tb", "tesla", "tev",
    "ton", "tons", "torr", "ug", "um", "volt", "volts", "w", "watt", "watts",
    "week", "weeks", "year", "years", "yr", "yrs", "µg", "µm",
}

_UNIT_STOP = {
    "a", "about", "after", "all", "also", "an", "and", "answer", "any", "are",
    "as", "at", "be", "but", "by", "can", "do", "for", "from", "had", "has",
    "have", "if", "is", "it", "its", "just", "me", "my", "no", "not", "of",
    "on", "or", "our", "question", "so", "than", "that", "the", "their",
    "then", "there", "these", "they", "this", "to", "too", "turn", "up",
    "us", "was", "we", "were", "what", "when", "which", "who", "will",
    "with", "you", "your",
}


def _quantity_has_unit(token: str) -> bool:
    """True when a number match already carries a real unit, %, °, or $."""
    raw = (token or "").strip().rstrip(".,;:")
    if not raw:
        return False
    if raw.startswith("$") or raw.endswith("%") or "°" in raw:
        return True
    # Split off the numeric prefix and inspect the unit tail.
    body = raw.lstrip("+-")
    i = 0
    while i < len(body) and (body[i].isdigit() or body[i] in ",."):
        i += 1
    if i < len(body) and body[i] in "eE":
        j = i + 1
        if j < len(body) and body[j] in "+-":
            j += 1
        while j < len(body) and body[j].isdigit():
            j += 1
        i = j
    # 3.8 × 10^8 m/s
    rest = body[i:].strip()
    if rest.lower().startswith(("x 10", "× 10")):
        caret = rest.find("^")
        if caret >= 0:
            k = caret + 1
            if k < len(rest) and rest[k] in "+-":
                k += 1
            while k < len(rest) and rest[k].isdigit():
                k += 1
            rest = rest[k:].strip()
    if not rest:
        return False
    key = rest.casefold()
    if key in _UNIT_NAMES:
        return True
    if key in _UNIT_STOP:
        return False
    if any(mark in rest for mark in "/^·"):
        return True
    # Short abbreviation such as kPa, Hz, Mpc.
    letters = "".join(ch for ch in rest if ch.isalpha())
    return 1 <= len(rest) <= 4 and bool(letters) and key not in _UNIT_STOP


_LATEX_BLOCK = re.compile(
    r"\$\$[\s\S]+?\$\$"
    r"|\$[^$\n]+\$"
    r"|\\\[[\s\S]+?\\\]"
    r"|\\\([\s\S]+?\\\)"
    r"|\\begin\{(?:equation\*?|align\*?|gather\*?)\}[\s\S]+?\\end\{(?:equation\*?|align\*?|gather\*?)\}"
)

# E = mc^2, H0 = 70 km/s/Mpc, x + y = 4. Stop before prose punctuation.
_EQUATION = re.compile(
    r"(?<![\w])([A-Za-z][A-Za-z0-9_]*"
    r"(?:\s*[+\-/*^]\s*[A-Za-z0-9_]+)*"
    r"\s*=\s*[^\n,.?!]{1,80})"
)

# `name`, file.ext, dotted.path, snake_case, CamelCase, trailing ()
_CODE_ID = re.compile(
    r"`([^`\n]{1,120})`"
    r"|[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]{0,12}"
    r"|[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_.]*[A-Za-z0-9_]"
    r"|[A-Za-z_][A-Za-z0-9_]*\(\)"
    r"|[A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]+"
    r"|[A-Z][a-z]+[A-Z][A-Za-z0-9]*"
)

_DECISION = re.compile(
    r"(?i)(?:"
    r"(?:^|(?<=[.!?]\s)|(?<=\n))"
    r"(?:"
    r"(?:we(?:'ll| will)?|i(?:'ll| will)?|let'?s)\s+"
    r"(?:(?:will|should|decided to|decide to)\s+)?"
    r"(?:use|go with|keep|pick|choose|chose|settle on)\s+[^.!?\n]{3,160}"
    r"|decided to\s+[^.!?\n]{3,160}"
    r"|(?:the\s+)?(?:decision|plan|choice)(?:\s+is|\s+was)\s+[^.!?\n]{3,160}"
    r"|we decided\s+[^.!?\n]{3,160}"
    r")"
    r")"
)


def is_compaction_marker(role: str = "", content: str = "", note: str = "") -> bool:
    """True for the transcript notice painted at a compaction cut."""
    if (note or "").strip() == COMPACTION_MARKER_NOTE:
        return True
    if (role or "") in {"notice", "system"} and (content or "").strip() == COMPACTION_MARKER:
        return True
    return False


def messages_text(messages: list[Any]) -> str:
    """Plain transcript of dropped rows, for extraction and the model excerpt."""
    lines: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            role = str(message.get("role") or "?")
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = str(content)
            if is_compaction_marker(role, content, str(message.get("note") or "")):
                continue
        else:
            role = str(getattr(message, "role", None) or "?")
            content = str(getattr(message, "content", None) or "")
            note = str(getattr(message, "note", None) or "")
            if is_compaction_marker(role, content, note):
                continue
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def extract_verbatim(text: str) -> list[str]:
    """Exact values pulled from *text* by pattern.

    Decisions, equations and LaTeX claim slots first when the 24-item cap
    binds, so a long list of quantities cannot drop them. Dates, ranges,
    other quantities and code identifiers fill whatever room is left.
    """
    raw = text or ""
    seen: set[str] = set()
    occupied: list[tuple[int, int]] = []
    latex: list[str] = []
    dates: list[str] = []
    quantities: list[str] = []
    equations: list[str] = []
    decisions: list[str] = []
    codes: list[str] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= left or start >= right) for left, right in occupied)

    def _add(item: str, bucket: list[str], span: tuple[int, int] | None = None) -> None:
        cleaned = " ".join((item or "").strip().rstrip(".,;:").split())
        if not cleaned:
            return
        if len(cleaned) > MAX_VERBATIM_ITEM_CHARS:
            # A long derivation stays in the archive; do not ship a mid-cut copy.
            return
        key = cleaned.casefold()
        if key in seen:
            return
        seen.add(key)
        bucket.append(cleaned)
        if span is not None:
            occupied.append(span)

    for match in _LATEX_BLOCK.finditer(raw):
        _add(match.group(0), latex, match.span())
    for match in _ISO_DATE.finditer(raw):
        if not _overlaps(*match.span()):
            _add(match.group(0), dates, match.span())
    for match in _NUMBER_RANGE.finditer(raw):
        if not _overlaps(*match.span()):
            _add(match.group(0), quantities, match.span())
    for match in _NUMBER_WITH_UNIT.finditer(raw):
        token = match.group(0)
        if _quantity_has_unit(token) and not _overlaps(*match.span()):
            _add(token, quantities, match.span())
    for match in _EQUATION.finditer(raw):
        if not _overlaps(*match.span()):
            _add(
                match.group(1) if match.lastindex else match.group(0),
                equations,
                match.span(),
            )
    for match in _DECISION.finditer(raw):
        _add(match.group(0).rstrip(" ."), decisions)
    for match in _CODE_ID.finditer(raw):
        token = match.group(1) if match.lastindex and match.group(1) else match.group(0)
        token = token.strip()
        # Bare `12` is a number, already handled when units are present.
        if token.isdigit():
            continue
        if not _overlaps(*match.span()):
            _add(token, codes, match.span())

    # Reserved types keep their slots; fillers take only what remains.
    reserved = latex + equations + decisions
    fillers = dates + quantities + codes
    if len(reserved) >= MAX_VERBATIM_ITEMS:
        kept = reserved[:MAX_VERBATIM_ITEMS]
    else:
        kept = reserved + fillers[: MAX_VERBATIM_ITEMS - len(reserved)]
    kept_keys = {item.casefold() for item in kept}
    ordered: list[str] = []
    for item in latex + dates + quantities + equations + decisions + codes:
        key = item.casefold()
        if key in kept_keys:
            ordered.append(item)
            kept_keys.discard(key)
    return ordered


def _clip_narrative(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 1:
        return "…"
    return cleaned[: limit - 1].rstrip() + "…"


def format_verbatim_block(items: list[str], *, budget: int = MAX_VERBATIM_CHARS) -> str:
    """Render complete verbatim items that fit *budget*, including the heading."""
    kept: list[str] = []
    used = len(VERBATIM_HEADING) + 1
    for item in items:
        line = f"- {item}"
        extra = len(line) + (1 if kept else 0)
        if used + extra > budget:
            continue
        kept.append(line)
        used += extra
        if len(kept) >= MAX_VERBATIM_ITEMS:
            break
    if not kept:
        return ""
    return VERBATIM_HEADING + "\n" + "\n".join(kept)


def merge_compaction_pin(
    narrative: str,
    items: list[str],
    *,
    previous: str = "",
) -> str:
    """Build the working-set pin: narrative plus a verbatim block.

    Verbatim items win over a long narrative when the combined cap binds.
    A previous pin's verbatim items are carried forward and deduped.
    """
    previous = (previous or "").strip()
    prev_narrative, prev_items = split_compaction_pin(previous)
    merged_items: list[str] = []
    seen: set[str] = set()
    for item in [*prev_items, *items]:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        merged_items.append(item)

    text = (narrative or "").strip() or prev_narrative
    if text.startswith(VERBATIM_HEADING):
        text = ""
    if not text and merged_items:
        text = _FALLBACK_NARRATIVE
    if not text and not merged_items:
        return previous

    verbatim = format_verbatim_block(merged_items, budget=MAX_VERBATIM_CHARS)
    narrative_budget = MAX_SUMMARY_CHARS
    if verbatim:
        # Leave room for a blank line plus the verbatim block inside the pin cap.
        narrative_budget = min(
            MAX_SUMMARY_CHARS,
            max(0, MAX_COMPACTION_PIN_CHARS - len(verbatim) - 2),
        )
    clipped = _clip_narrative(text, narrative_budget) if text else ""
    parts = [part for part in (clipped, verbatim) if part]
    pin = "\n\n".join(parts)
    if len(pin) > MAX_COMPACTION_PIN_CHARS:
        overflow = len(pin) - MAX_COMPACTION_PIN_CHARS
        if clipped and len(clipped) > overflow + 1:
            clipped = _clip_narrative(clipped, len(clipped) - overflow)
            pin = "\n\n".join(part for part in (clipped, verbatim) if part)
        else:
            pin = pin[: MAX_COMPACTION_PIN_CHARS - 1].rstrip() + "…"
    return pin


def split_compaction_pin(pin: str) -> tuple[str, list[str]]:
    """Split a stored pin into the narrative and its verbatim items."""
    text = (pin or "").strip()
    if not text:
        return "", []
    heading = f"\n{VERBATIM_HEADING}\n"
    if text.startswith(VERBATIM_HEADING + "\n"):
        narrative = ""
        body = text[len(VERBATIM_HEADING) :].lstrip("\n")
    elif heading in f"\n{text}":
        narrative, body = text.split(VERBATIM_HEADING, 1)
        narrative = narrative.strip()
        body = body.lstrip(":\n")
    else:
        return text, []
    items: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item:
                items.append(item)
    return narrative, items


def compaction_prompt_line(pin: str) -> str:
    """System pin the next turn sees."""
    text = (pin or "").strip()
    if not text:
        return ""
    return f"[earlier in this conversation: {text}]"
