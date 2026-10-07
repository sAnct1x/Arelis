"""What a person reads when something fails, as opposed to what a model reads.

``arelis.llm.errors`` already does this for Ollama: chat gets a short instruction,
the exception and the URL go to Thinking. Two paths never got the same treatment.

The orchestrator's last line of defence published
``f"Turn failed: {exc.__class__.__name__}: {exc}"``, which the UI put straight in
the transcript, so the worst moment the app has produced the least human sentence
it could, ``Turn failed: ConnectError: [Errno 11001] getaddrinfo failed``.

Failed tool output went to chat verbatim, up to 500 characters. That was a
deliberate choice and half right: "Not a file: C:/typo.csv" is exactly what the
user needs, and hiding it made a wrong path look like a silent no-op. What it did
not anticipate is that tool failures are written *for the model*, the analyze tool
now answers a bad file type with "Call vision(path=…) for an image", which is an
instruction to a 7B appearing in a human's chat window.

So the rule here is not "hide the output". It is: pass through what a person can
act on, and swap out anything addressed to the model. Detail is never lost, it
goes to Thinking and Workspace either way.
"""

from __future__ import annotations

import json
import math
import re
from decimal import Decimal, InvalidOperation

from arelis.core.evidence import looks_like_bot_wall

TURN_FAILED_NOTICE = (
    "Something went wrong mid-turn, so I stopped rather than guess. "
    "The details are in Thinking (Ctrl+1). Try again, or rephrase."
)

# Sentences aimed at the model. A tool that says "Call vision(path=…)" or
# "Rejected: `calculator` takes none of…" is mid-conversation with the 7B, and
# repeating that to the user reads as the app talking to itself.
_MODEL_DIRECTED = re.compile(
    r"(?i)("
    r"^rejected:|"
    r"\bcall\s+\w+\(|"
    r"\bcall\s+(?:the\s+)?\w+\s+tool\b|"
    r"\bdo not\s+(?:call|invent|guess|quote|scrape)\b|"
    r"\bwith its own arguments\b|"
    r"\bintent preflight\b|"
    r"\ballow still applies\b"
    r")"
)

# Instruction footers on a successful tool result. Strip only when that result
# is about to become chat because Qwen left the wrap-up empty.
_SUCCESS_FOOTER = re.compile(
    r"(?i)("
    r"summarize these events|"
    r"do not invent(?:\s+events)?|"
    r"do not quote(?:\s+(?:event\s+ids|google/outlook))|"
    r"do not quote event ids"
    r")"
)

_WORKSPACE_LISTING_LINE = re.compile(r"(?m)^\[(?:dir|file)\]\s")
_PAGE_META = re.compile(
    r"(?i)^(site|by|published|length|url|sources|#+\s*sources)\s*:"
)
_SEARCH_TITLE = re.compile(r"(?i)^\s*\d+\.\s*Title:\s*(.+)$")
_PAGE_TOOLS = frozenset({"scrape", "web_fetch", "browser"})
_SEARCH_TOOLS = frozenset({"web_search"})
_PAGE_WRITE_TOOLS = frozenset({"scrape", "web_search", "web_fetch", "browser"})
_ALGEBRA_WRITE_TOOLS = frozenset({"cas", "calculator", "python", "units", "plot"})
_PAGE_CHAT_CHARS = 420
# Short fact lines (a price, a one-line hit) can ship as chat.
# A scraped article or a SERP must not — ask the model to write first.
_PAGE_WRITE_NUDGE_CHARS = 400
# They typed an equation. "hard math tonight" is not that.
_TYPED_EQUATION = re.compile(
    r"(?i)[a-z][a-z0-9]*\s*(?:\*\*|\^|²|[+\-*/]).{0,48}="
)


def _algebra_was_asked(ask: str) -> bool:
    from arelis.core.claims import detect_cas_ask, detect_math_ask, detect_units_ask

    raw = ask or ""
    return (
        detect_cas_ask(raw)
        or detect_math_ask(raw)
        or detect_units_ask(raw)
        or bool(_TYPED_EQUATION.search(raw))
    )

# Human copy for the tools whose failures reach the transcript, used when the raw
# output turns out to be model-directed. Keyed by tool name.
_TOOL_NOTICES: dict[str, str] = {
    "analyze": (
        "That file is not a spreadsheet, so I could not read it as a table. "
        "I will try the right reader for it."
    ),
    "workspace": "I could not read that file. The path is in Workspace.",
    "image": "Image generation failed. The details are in Workspace.",
    "doc_extract": "I could not read that PDF. The details are in Workspace.",
    "document": "I could not write that file. The details are in Thinking.",
    "vision": "I could not open that image.",
}

_GENERIC_TOOL_NOTICE = "`{tool}` did not complete. The details are in Thinking."

# Long enough for "Not a file: <a real Windows path>", short enough that a stack
# trace or a page of scraped text cannot land in the transcript.
_MAX_PASSTHROUGH = 240


_ERRNO_PREFIX = re.compile(r"^\[(?:Errno|WinError)\s*-?\d+\]\s*")


def plain_reason(exc: BaseException) -> str:
    """The readable half of an exception: no class name, no errno bracket.

    ``open failed: [Errno 13] Permission denied: 'C:/x'`` becomes
    ``Permission denied: 'C:/x'``. The refusal itself is usually the useful part
    a path outside the workspace roots, a file held open by something else, so
    this trims the machine framing rather than replacing the sentence.
    """
    text = str(exc).strip()
    text = _ERRNO_PREFIX.sub("", text)
    if not text:
        return type(exc).__name__
    if len(text) > _MAX_PASSTHROUGH:
        text = text[:_MAX_PASSTHROUGH].rstrip() + "…"
    return text[0].upper() + text[1:] if text[:1].islower() else text


def turn_failed_notice(exc: BaseException) -> tuple[str, str]:
    """Return (chat copy, Thinking detail) for an unhandled turn failure.

    An Ollama exception that reaches this far is still an Ollama exception, so it
    keeps the copy that names the chip in the title bar rather than the generic
    line, the user's next action is different.
    """
    detail = f"{type(exc).__name__}: {exc}"
    try:
        import httpx

        from arelis.llm.errors import classify_ollama_failure

        if isinstance(exc, (httpx.HTTPError, httpx.NetworkError, httpx.TimeoutException)):
            failure = classify_ollama_failure(exc)
            return failure.chat, failure.detail
    except Exception:
        # Copy is not worth an exception inside the handler of an exception.
        pass
    from arelis.i18n import tr

    return tr(TURN_FAILED_NOTICE), detail


def is_model_directed(text: str) -> bool:
    """True when this sentence is talking to the model, not to the user."""
    return bool(_MODEL_DIRECTED.search((text or "").strip()))


def tool_failure_notice(tool: str, output: str) -> str:
    """One line a person can act on, for a tool that failed.

    Passes the tool's own first line through when it is plain, "Not a file:
    C:/typo.csv" is the whole answer and swapping it for something vaguer would
    undo the reason this was ever shown. Substitutes human copy when the line is
    addressed to the model, or when there is nothing to show.
    """
    name = (tool or "").strip() or "that tool"
    first = ""
    for line in (output or "").splitlines():
        if line.strip():
            first = line.strip()
            break

    if not first or is_model_directed(first) or is_model_directed(output or ""):
        return _TOOL_NOTICES.get(name, _GENERIC_TOOL_NOTICE.format(tool=name))
    if len(first) > _MAX_PASSTHROUGH:
        return _TOOL_NOTICES.get(name, _GENERIC_TOOL_NOTICE.format(tool=name))
    return first


def _strip_success_footers(text: str) -> str:
    """Drop model-only instruction lines; keep the person-facing body."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        if _SUCCESS_FOOTER.search(line):
            continue
        if is_model_directed(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def should_nudge_write_after_page(tool: str, output: str) -> bool:
    """True when empty-after-tool would paste an article instead of a fact.

    Qwen3.5 often leaves chat empty after scrape and puts the wrap-up in
    thinking. Shipping a short price is fine. Shipping a blog is not
    the user asked for an answer, not the page.
    """
    if (tool or "").strip() not in _PAGE_WRITE_TOOLS:
        return False
    out = output or ""
    if looks_like_bot_wall(out):
        return True
    if "Site:" in out or out.lstrip().startswith("# "):
        return True
    return len(out) >= _PAGE_WRITE_NUDGE_CHARS


def should_nudge_write_after_algebra(tool: str) -> bool:
    """CAS / calc dumps are not a chat line. Ask for a sentence first."""
    return (tool or "").strip() in _ALGEBRA_WRITE_TOOLS


_RESULT_TOOLS = frozenset({"calculator", "units"})


def _algebra_result_tokens(output: str) -> list[str]:
    """Numeric / unit tokens from a calculator or units receipt."""
    body = (output or "").strip()
    if not body:
        return []
    right = body.rsplit(" = ", 1)[-1].strip() if " = " in body else body
    tokens: list[str] = []
    if " (exactly " in right:
        main, rest = right.split(" (exactly ", 1)
        main = main.strip()
        exact = rest.rstrip(")").strip()
        if main:
            tokens.append(main)
        if exact:
            tokens.append(exact)
    elif right:
        tokens.append(right.split()[0] if right.split() else right)
        # "5 mi = 8.047 km" — keep the converted magnitude too.
        parts = right.split()
        if len(parts) >= 2 and parts[-1].isalpha():
            tokens.append(parts[0])
    # A spoken answer often uses the short display form ("1.88"), not the
    # full float from the receipt. Count that as stating the result.
    for tok in list(tokens):
        if not re.fullmatch(r"-?\d+\.\d{3,}", tok):
            continue
        try:
            val = float(tok)
        except ValueError:
            continue
        short = f"{val:.2f}".rstrip("0").rstrip(".")
        if short and short not in tokens:
            tokens.append(short)
    return [t for t in tokens if t]


def _token_in_reply(token: str, text: str) -> bool:
    tok = (token or "").strip()
    if not tok or not text:
        return False
    if re.fullmatch(r"-?\d+(?:\.\d+)?", tok):
        # "2." is the answer plus a period. "2.5" is a different number.
        return bool(
            re.search(rf"(?<![\d.]){re.escape(tok)}(?!\d)(?!\.\d)", text)
        )
    return tok in text


def reply_states_algebra_result(content: str, tool: str, output: str) -> bool:
    """True when chat already states the calculator / units result.

    Qwen3.5 often puts the number in thinking and ships 'What's next?' as
    the bubble. Empty-after-tool only catches a blank reply; this is the
    filler case. CAS dumps stay on the write-up path, do not police them.
    """
    name = (tool or "").strip()
    if name not in _RESULT_TOOLS:
        return True
    tokens = _algebra_result_tokens(output)
    if not tokens:
        return True
    return any(_token_in_reply(tok, content or "") for tok in tokens)


_DATA_FOLLOWUP = (
    "I got the information, but I could not put it into words. Ask me again and I will try."
)

_PLANET_IN_ASK = re.compile(r"(?i)\b(mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto)\b")
# Spoken duration rewrite for "how long is a year on Mars": (686.980)/365.256
_PERIOD_OVER_EARTH = re.compile(r"^\(\d+(?:\.\d+)?\)/365\.256$")
_WANTS_EARTH_DAYS = re.compile(r"(?i)\b(?:earth\s+)?days?\b")
# Calendar / reminder / task lists are already written for people.
_PERSON_LIST_TOOLS = frozenset({"agenda", "remind", "tasks"})

# Text pulled FROM a page, image, clipboard, or note is already the answer.
_CONTENT_PASSTHROUGH_TOOLS = frozenset(
    {"ocr", "clipboard", "transcribe", "notes", "doc_extract", "vision"}
)


def chat_followup_from_tool(tool: str, output: str, *, ask: str = "") -> str:
    """Person-facing copy when the model leaves chat empty after a tool.

    The model still sees the raw tool result (including instruction footers).
    This path is only the last-resort chat line. It must never ship a formula
    line, a data header, or a bare Done.
    """
    body = (output or "").strip()
    name = (tool or "").strip()
    if (
        name in _ALGEBRA_WRITE_TOOLS
        and name != "plot"
        and not _algebra_was_asked(ask)
    ):
        return "Ready when you are. What problem do you want to start with?"
    if not body:
        return (
            "I finished the lookup, but I could not write a follow-up. "
            "Send the same ask again."
        )
    listing = _WORKSPACE_LISTING_LINE.search(body) or body.lstrip().startswith(
        ("[dir]", "[file]")
    )
    if name == "workspace" and listing:
        return "That listing is in Workspace."
    if listing and name in {"", "workspace"}:
        return "That listing is in Workspace."
    cleaned = _strip_success_footers(body)
    if not cleaned:
        if name == "agenda":
            return "No events in this window."
        return "I finished the lookup. The details are in Workspace."
    # Ahead of the page branch, because web_fetch is on both lists now: it was
    # a page reader when that branch was written and it answers APIs as well
    # since it grew POST/PUT/PATCH/DELETE. _page_talk has no idea what to do
    # with a response body, so it handed the whole object back unchanged.
    if _is_json_body(cleaned):
        return (
            "The call went through and came back with data, but I did not get "
            "a sentence out of it. Ask again and I will read the response."
        )
    if name in {"calculator", "units"}:
        return plain_algebra_chat(cleaned, ask=ask)
    if name in _PAGE_TOOLS:
        if looks_like_bot_wall(cleaned):
            return (
                "That page did not give a usable source (login, captcha, "
                "or a bot check). I need another URL or a search, this "
                "is not the report."
            )
        return _page_talk(cleaned)
    if name in _SEARCH_TOOLS:
        return _search_talk(cleaned)
    if name == "doc_extract" and (
        "source: ink" in cleaned.lower() or "no text layer" in cleaned.lower()
    ):
        return (
            "That PDF is handwritten or scanned, I still need to look at "
            "the page images. Ask me again if I stopped on the path list."
        )
    # A posed CAS/python dump is the answer they asked for. Do not treat
    # latex / result lines as a generic data header.
    if name in {"cas", "python"} and _algebra_was_asked(ask):
        if len(cleaned) > 1600:
            cleaned = cleaned[:1597].rstrip() + "…"
        return cleaned
    # Agenda / remind / tasks already answer in words. Keep the list.
    if name in _PERSON_LIST_TOOLS:
        if len(cleaned) > 1600:
            cleaned = cleaned[:1597].rstrip() + "…"
        return cleaned
    # Weather already answers in words (current-only lines look like key:value).
    if name == "weather":
        if len(cleaned) > 1600:
            cleaned = cleaned[:1597].rstrip() + "…"
        return cleaned
    # OCR / clipboard / notes / PDF text: the content IS the answer.
    if name in _CONTENT_PASSTHROUGH_TOOLS:
        if len(cleaned) > 1600:
            cleaned = cleaned[:1597].rstrip() + "…"
        return cleaned
    if _looks_like_data_dump(cleaned):
        return _DATA_FOLLOWUP
    if len(cleaned) > 1600:
        cleaned = cleaned[:1597].rstrip() + "…"
    return cleaned


def followup_passthrough_tool(tool: str, line: str, raw: str) -> str:
    """Tool name for memory passthrough only when the shipped line is the tool's text."""
    shipped = (line or "").strip()
    source = (raw or "").strip()
    if shipped and (shipped == source or (source and shipped in source)):
        return (tool or "").strip()
    return ""


# The units tool appends a note for the model after a temperature
# conversion. It is not part of the answer, so it is dropped before phrasing.
_TEMP_NOTE = re.compile(r"\s*Temperature conversions use an offset\b.*$", re.S)
_CLEAN_UNIT_RHS = re.compile(
    r"^(?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+"
    r"(?P<unit>[A-Za-z]+(?:_[A-Za-z]+)*)$"
)
_CLEAN_NUM_RHS = re.compile(
    r"^(?P<num>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?P<pct>%)?$"
)
_UNIT_WORDS: dict[str, tuple[str, str]] = {
    "degree_celsius": ("degree Celsius", "degrees Celsius"),
    "degree_fahrenheit": ("degree Fahrenheit", "degrees Fahrenheit"),
    "centimeter": ("centimeter", "centimeters"),
    "millimeter": ("millimeter", "millimeters"),
    "kilometer": ("kilometer", "kilometers"),
    "meter": ("meter", "meters"),
    "inch": ("inch", "inches"),
    "foot": ("foot", "feet"),
    "mile": ("mile", "miles"),
    "kilogram": ("kilogram", "kilograms"),
    "gram": ("gram", "grams"),
    "second": ("second", "seconds"),
    "minute": ("minute", "minutes"),
    "hour": ("hour", "hours"),
}
# Plurals that do not just take an "s".
_IRREGULAR_PLURALS: dict[str, str] = {
    "foot": "feet",
    "century": "centuries",
    "henry": "henries",
}
# Unit names that read the same for one or many.
_SAME_PLURAL_ENDINGS = ("hertz", "lux", "siemens", "celsius", "fahrenheit")
# Big numbers are said with a scale word, never in e-notation.
_SCALE_WORDS: tuple[tuple[int, str], ...] = (
    (10**24, "septillion"),
    (10**21, "sextillion"),
    (10**18, "quintillion"),
    (10**15, "quadrillion"),
    (10**12, "trillion"),
    (10**9, "billion"),
    (10**6, "million"),
)


def plain_algebra_chat(output: str, *, ask: str = "") -> str:
    """One plain sentence from a calculator or units receipt.

    Never the formula line. The model still saw the exact receipt.
    """
    body = (output or "").strip()
    if not body:
        return body
    expr = ""
    right = body
    if " = " in body:
        expr, right = body.rsplit(" = ", 1)
        expr = expr.strip()
        right = right.strip()
    main = right
    if " (exactly " in main:
        main = main.split(" (exactly ", 1)[0].strip()
    main = _TEMP_NOTE.sub("", main).strip()
    unit_hit = _CLEAN_UNIT_RHS.fullmatch(main)
    if unit_hit is not None:
        shown, rounded = _spoken_number(unit_hit.group("num"), expr=expr)
        if not shown:
            return _DATA_FOLLOWUP
        unit = _humanize_unit(unit_hit.group("unit"), shown)
        about = "about " if rounded else ""
        return f"That works out to {about}{shown} {unit}."
    num_hit = _CLEAN_NUM_RHS.fullmatch(main)
    if num_hit is None:
        return _DATA_FOLLOWUP
    shown, rounded = _spoken_number(num_hit.group("num"), expr=expr)
    if not shown:
        return _DATA_FOLLOWUP
    try:
        raw_val = float(num_hit.group("num"))
    except ValueError:
        raw_val = 0.0
    is_pct = bool(num_hit.group("pct")) or bool(
        expr and re.search(r"\*\s*100\b", expr) and abs(raw_val) < 10000
    )
    planet = _PLANET_IN_ASK.search(ask or "")
    if planet is not None and re.search(r"(?i)\byear\b", ask or ""):
        name = planet.group(1).capitalize()
        folded_expr = re.sub(r"\s+", "", expr)
        if _PERIOD_OVER_EARTH.fullmatch(folded_expr):
            return f"A year on {name} is about {shown} Earth years."
        # Only the bare sidereal day count. "687/7 for a Mars year" is their
        # arithmetic, not the length of the orbit.
        if _WANTS_EARTH_DAYS.search(ask or "") and re.fullmatch(
            r"\d+(?:\.\d+)?", folded_expr
        ):
            days = _round_day_count(shown)
            return f"A year on {name} is about {days} Earth days."
        # Age-in-planet-years and other shapes: just state the number.
    about = "about " if rounded else ""
    suffix = "%" if is_pct else ""
    return f"That works out to {about}{shown}{suffix}."


def _humanize_unit(unit: str, magnitude: str) -> str:
    """Turn Pint unit ids into plain spoken words; plural except for exactly 1."""
    key = (unit or "").strip().lower()
    try:
        val = float((magnitude or "").replace(",", ""))
        singular = abs(val - 1.0) < 1e-12 or abs(val + 1.0) < 1e-12
    except ValueError:
        singular = False
    pair = _UNIT_WORDS.get(key)
    if pair is not None:
        return pair[0] if singular else pair[1]
    spoken = " ".join((unit or "").replace("_", " ").split())
    if not spoken:
        return spoken
    words = spoken.split(" ")
    # Pint's force_pound (and "pound force") read as "pounds of force".
    if len(words) == 2 and "force" in (words[0].lower(), words[1].lower()):
        noun = words[1] if words[0].lower() == "force" else words[0]
        body = noun if singular else _plural_word(noun)
        return f"{body} of force"
    if singular:
        return spoken
    # "mile per hour" becomes "miles per hour": only the part before "per".
    head, sep, tail = spoken.partition(" per ")
    words = head.split(" ")
    words[-1] = _plural_word(words[-1])
    return " ".join(words) + sep + tail


def _plural_word(word: str) -> str:
    """Plural of one unit word: centuries, feet, inches, and hertz unchanged."""
    low = word.lower()
    for single, many in _IRREGULAR_PLURALS.items():
        if low.endswith(single):
            return word[: len(word) - len(single)] + many
    if low.endswith(_SAME_PLURAL_ENDINGS) or low.endswith("s"):
        return word
    if low.endswith("y") and len(low) > 1 and low[-2] not in "aeiou":
        return word[:-1] + "ies"
    if low.endswith(("x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def _spoken_number(raw: str, *, expr: str = "") -> tuple[str, bool]:
    """Return (shown, rounded) for a number said to a person.

    Never e-notation. Big numbers get a scale word (about 9.46 trillion),
    very long ones a digit count, and tiny ones an empty string so the
    caller ships the plain give-up line instead of something like 1.6e-19.
    """
    text = (raw or "").strip()
    if not _CALC_NUMBER.fullmatch(text):
        return "", False
    if expr and re.search(r"\*\s*100\b", expr):
        shown, rounded = _format_magnitude(text, expr=expr)
        if shown and "e" not in shown.lower():
            return shown, rounded
    try:
        value = Decimal(text)
    except InvalidOperation:
        return "", False
    if not value.is_finite():
        return "", False
    dash = "-" if value < 0 else ""
    minus = "minus " if value < 0 else ""
    size = abs(value)
    if size == 0:
        return "0", False
    nearest = size.to_integral_value()
    snap_rounded = False
    # Float noise such as -39.99999999999997 is a whole number.
    if nearest != 0 and abs(size - nearest) <= Decimal("1e-9") * nearest:
        if abs(size - nearest) > Decimal("1e-12") * nearest:
            snap_rounded = True
        size = nearest

    def _is_rounded(shown_num: str) -> bool:
        got = Decimal(shown_num.replace(",", ""))
        if got == size:
            return snap_rounded
        if size != 0 and abs(got - size) <= Decimal("1e-12") * size:
            return snap_rounded
        return True

    if size >= Decimal(10) ** 27:
        if size == size.to_integral_value():
            digits = str(int(size))
            lead = digits.rstrip("0")
            if len(lead) == 1:
                zeros = len(digits) - 1
                return f"{minus}{lead} followed by {zeros} zeros", False
            count = len(digits)
        else:
            count = size.adjusted() + 1
        return f"{minus}a number with {count} digits", False
    if size == size.to_integral_value() and size < 10**12:
        return f"{dash}{int(size):,}", snap_rounded
    if size >= 10**6:
        for i, (scale, word) in enumerate(_SCALE_WORDS):
            if size >= scale:
                part = f"{size / scale:.2f}".rstrip("0").rstrip(".")
                if part == "1000":
                    if i > 0:
                        scale, word = _SCALE_WORDS[i - 1]
                        part = f"{size / scale:.2f}".rstrip("0").rstrip(".")
                    else:
                        count = (
                            len(str(int(size)))
                            if size == size.to_integral_value()
                            else size.adjusted() + 1
                        )
                        return f"{minus}a number with {count} digits", False
                exact = Decimal(part) * scale == size
                return f"{dash}{part} {word}", snap_rounded or (not exact)
    if size < Decimal("1e-6"):
        if size >= Decimal("1e-9"):
            sig = len(size.normalize().as_tuple().digits)
            if sig <= 3:
                places = -int(size.adjusted()) + (sig - 1)
                shown = f"{size:.{places}f}".rstrip("0")
                return f"{dash}{shown}", _is_rounded(shown)
        return "", False
    if size < Decimal("1e-4"):
        places = -size.adjusted() + 2
        shown = f"{size:.{places}f}".rstrip("0")
        return f"{dash}{shown}", _is_rounded(shown)
    decimals = max(0, -size.as_tuple().exponent)
    if decimals > 4:
        if size < 1:
            shown = f"{float(size):.4g}"
        else:
            shown = f"{size:,.2f}".rstrip("0").rstrip(".")
    else:
        shown = f"{size:,.{decimals}f}"
    return f"{dash}{shown}", _is_rounded(shown)


def _round_day_count(number: str) -> str:
    """Sidereal days are quoted whole; 686.98 reads as about 687."""
    try:
        val = float((number or "").replace(",", ""))
    except ValueError:
        return number
    return str(round(val))


_SENTENCE_ENDS = tuple(".!?。！？")


def _looks_like_data_dump(text: str) -> bool:
    """True when the tool answered in headers / tables / key-value lines."""
    body = (text or "").strip()
    if not body:
        return False
    if re.search(
        r"(?im)^(api\s+version|api\s+source|target\s+body|center\s+body|"
        r"start\s+time|revised|r\.a\.|ephemeris)\b",
        body,
    ):
        return True
    # Markdown calendar / bullet lists are person-facing, not ephemeris dumps.
    if re.search(r"(?m)^(?:\*\*[^*]+\*\*|\s*[-*]\s+\S)", body):
        return False
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # Drop a trailing "Source: ..." line so a short list is not a dump.
    lines = [ln for ln in lines if not re.match(r"(?i)^source\s*:", ln)]
    if len(lines) >= 3:
        short = sum(
            1
            for ln in lines
            if len(ln) < 90 and not ln.endswith(_SENTENCE_ENDS)
        )
        if short >= 3:
            return True
    kv = sum(1 for ln in lines if re.match(r"^[\w ./-]{1,48}:\s+\S", ln))
    return kv >= 2


_SIMPLE_FRAC = re.compile(r"^-?\d{1,2}/\d{1,2}$")
_CALC_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def pretty_calculator_chat(output: str) -> str:
    """Chat line from a calculator receipt, not 15 decimals and a fraction.

    The model still sees the exact tool output. This is only what we ship
    when she leaves the bubble empty (or filler without the number).
    """
    body = (output or "").strip()
    if not body:
        return body
    if " = " not in body:
        return _pretty_number_token(body)
    left, right = body.rsplit(" = ", 1)
    main = right.strip()
    exact = ""
    if " (exactly " in main:
        main, rest = main.split(" (exactly ", 1)
        main = main.strip()
        exact = rest.rstrip(")").strip()
    pretty = _pretty_number_token(main, expr=left)
    if exact and _SIMPLE_FRAC.fullmatch(exact) and pretty != exact:
        return f"{left} = {pretty} (exactly {exact})"
    return f"{left} = {pretty}"


def _format_magnitude(raw: str, *, expr: str = "") -> tuple[str, bool]:
    """Return (shown, rounded) for a clean numeric token."""
    text = (raw or "").strip()
    if not _CALC_NUMBER.fullmatch(text):
        return "", False
    try:
        val = float(text)
    except ValueError:
        return "", False
    if not math.isfinite(val) and re.fullmatch(r"-?\d+", text):
        # An exact integer too big for a float (1e308*10 is 310 digits).
        # Say it in short scientific form instead of spelling it out.
        from decimal import Decimal

        return f"{Decimal(text):.4g}".lower(), True
    if not math.isfinite(val):
        # 1e308*10 overflows float; keep the short scientific token.
        if "e" in text.lower():
            return text.lower(), True
        return "", False
    if expr and re.search(r"\*\s*100\b", expr) and abs(val) < 10000:
        shown = f"{val:.1f}"
        return shown, shown != text
    # Ordinary integers (including millions) get thousands separators.
    if val.is_integer() and abs(val) < 2**53:
        n = int(val)
        shown = f"{n:,}" if abs(n) >= 1000 else str(n)
        return shown, False
    # Non-integer huge / tiny: keep it short (never a 309-digit sentence).
    if abs(val) >= 1e6 or (abs(val) > 0 and abs(val) < 1e-4):
        return f"{val:.4g}", True
    decimals = 0
    if "." in text:
        frac = text.split(".", 1)[1]
        frac = re.split(r"[eE]", frac, maxsplit=1)[0]
        decimals = len(frac)
    elif "e" in text.lower():
        return f"{val:.4g}", True
    if decimals > 4:
        if abs(val) < 1:
            shown = f"{val:.4g}"
        else:
            shown = f"{val:.2f}".rstrip("0").rstrip(".") or "0"
        return shown, True
    return text, False


def _pretty_number_token(raw: str, *, expr: str = "") -> str:
    text = (raw or "").strip()
    shown, _rounded = _format_magnitude(text, expr=expr)
    return shown if shown else text


def _is_json_body(text: str) -> bool:
    """True when the whole output is one JSON value.

    The last branch of `chat_followup_from_tool` pastes the tool's output into
    chat verbatim, which is right for a tool that answers in words and wrong
    for one that answers in data. `web_fetch` grew POST/PUT/PATCH/DELETE and
    now returns API bodies, so an empty model reply put a raw response object
    tokens and all, in the bubble as if she had written it.

    Parsed rather than pattern-matched, so a sentence that merely starts with a
    brace is still a sentence, and a body that only looks like JSON is still
    shown rather than swallowed.
    """
    body = (text or "").strip()
    if not body or body[0] not in "{[":
        return False
    try:
        json.loads(body)
    except (ValueError, TypeError):
        return False
    return True


def _first_sentences(text: str, *, n: int = 2, cap: int = _PAGE_CHAT_CHARS) -> str:
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    parts: list[str] = []
    start = 0
    for i, ch in enumerate(raw):
        if ch in ".!?" and i + 1 < len(raw) and raw[i + 1] == " ":
            parts.append(raw[start : i + 1].strip())
            start = i + 2
            if len(parts) >= n:
                break
    if not parts:
        parts.append(raw)
    out = " ".join(parts)
    if len(out) > cap:
        out = out[: cap - 1].rstrip() + "…"
    return out


def _page_talk(output: str) -> str:
    """Title + a couple of sentences. Not the article."""
    title = ""
    body: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("[") or line.startswith("On-page"):
            continue
        if _PAGE_META.match(line):
            continue
        if line.startswith("# "):
            if not title:
                title = line[2:].strip()
            continue
        body.append(line)
    lede = _first_sentences(" ".join(body))
    if title and lede:
        if lede.lower().startswith(title.lower()[:24]):
            return lede
        return f"{title}\n\n{lede}"
    return title or lede or output[:_PAGE_CHAT_CHARS]


def _search_talk(output: str) -> str:
    """First hit, not the whole SERP."""
    for raw in (output or "").splitlines():
        hit = _SEARCH_TITLE.match(raw)
        if hit:
            title = hit.group(1).strip()
            if title:
                return title
    return _first_sentences(output, n=1, cap=240)


__all__ = [
    "TURN_FAILED_NOTICE",
    "chat_followup_from_tool",
    "followup_passthrough_tool",
    "is_model_directed",
    "plain_algebra_chat",
    "plain_reason",
    "pretty_calculator_chat",
    "reply_states_algebra_result",
    "should_nudge_write_after_algebra",
    "should_nudge_write_after_page",
    "tool_failure_notice",
    "turn_failed_notice",
]
