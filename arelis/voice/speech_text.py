"""Turn an on-screen answer into something worth hearing.

An answer is written to be read: it carries markdown, fenced code, tables, a
Sources list, and bare URLs. Handing that to a synthesizer verbatim produces
"asterisk asterisk Sources colon asterisk asterisk, one, Example Domain, h t t p
s colon slash slash", which is unusable. Everything here strips presentation
without touching meaning. Dates, a hash number, degrees, and percents are
spoken as words. The chat transcript never comes through this module.

Nothing is truncated by default. Long answers are handled by letting the user
interrupt, not by cutting the text: see the sentence queue in the voice service,
which starts speaking after the first sentence and can be abandoned mid-answer.
max_chars stays available as a runaway guard and is off unless configured.
"""
from __future__ import annotations

import re
from datetime import date

# A Sources block is a citation apparatus, not prose. It is the single worst
# thing to read aloud: a list of URLs spelled character by character.
_SOURCES_HEADING = re.compile(r"^\s*\**\s*sources\s*:?\s*\**\s*$", re.IGNORECASE)

_FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_INDENTED_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL = re.compile(r"<?\b(?:https?://|www\.)\S+>?")
# A markdown heading needs a space after the hashes. `#2` is a number,
# not a heading, and the hash has to survive until symbol spelling.
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?")
_BULLET = re.compile(r"^\s*[-*+]\s+")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]*\|[\s:|-]*\|?\s*$")
_BOLD_ITALIC = re.compile(r"(\*{1,3})(\S(?:.*?\S)?)\1", re.DOTALL)
# Underscore emphasis only when it is not inside a word. snake_case identifiers
# are constant in this assistant's output and must survive intact.
_UNDERSCORE_EMPHASIS = re.compile(r"(?<![\w_])(_{1,2})(\S(?:.*?\S)?)\1(?![\w_])", re.DOTALL)
_INLINE_CODE = re.compile(r"`+([^`]*)`+")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_CJK_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]+")


def scrub_cjk_runs(text: str, *, strip: bool = True) -> str:
    """Drop leaked CJK runs from English answers (model slip / TTS junk)."""
    if not text:
        return ""
    cleaned = _CJK_RUN.sub(" ", text)
    cleaned = _MULTI_SPACE.sub(" ", cleaned)
    return cleaned.strip() if strip else cleaned


# Piper has no lexicon for invented names — without this she says "airelyse".
# Also rewrite Whisper/Piper mangled spellings that slip into answer text.
_ARELIS_NAME = re.compile(r"(?i)\b(?:Arelis|Airelyse|Airelis|Ahrelis)\b")
_ARELIS_SPOKEN = "Uh-rell-iss"

# Sentence end followed by whitespace. The lookbehind list keeps common
# abbreviations from splitting mid-sentence, which would make the synthesizer
# drop a full stop's worth of silence into the middle of a clause.
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "st", "vs", "etc", "e.g", "i.e", "fig",
    "no", "approx", "al", "inc", "ltd", "jr", "sr",
}
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
# Chinese prose often has no space after 。！？. A period between two digits
# is not a sentence end. English still requires whitespace so an abbreviation
# like "Dr." is not cut in half.
_SENTENCE_END_ZH = re.compile(
    r"(?:(?<=[。！？!?])|(?<=\.)(?!\d))[\"'\"')\]]*\s*"
)


def prepare_spoken_text(text: str, *, max_chars: int = 0, language: str = "en") -> str:
    """Reduce an answer to plain speakable prose.

    max_chars of 0 means no limit. A positive value cuts at the last sentence
    boundary that fits, falling back to a hard cut only when a single sentence
    is longer than the whole allowance.
    """
    if not text:
        return ""

    body = _THINK_BLOCK.sub(" ", text)
    body = _FENCED_CODE.sub(" ", body)
    body = _drop_sources(body)

    lines: list[str] = []
    for raw in body.splitlines():
        line = _speakable_line(raw)
        if line is not None:
            lines.append(line)

    spoken = "\n".join(lines)
    chinese = str(language or "").lower().startswith("zh")
    if not chinese:
        spoken = scrub_cjk_runs(spoken)
    spoken = _MULTI_NEWLINE.sub("\n\n", spoken)
    # A single newline inside a paragraph is a wrap, not a pause.
    spoken = re.sub(r"(?<!\n)\n(?!\n)", " ", spoken)
    spoken = _MULTI_SPACE.sub(" ", spoken)
    spoken = "\n\n".join(part.strip() for part in spoken.split("\n\n") if part.strip())
    # Phonetic spelling for Piper (persona text never reaches TTS).
    # Mandarin Kokoro gets a spoken name; "Uh-rell-iss" is an English mouth trick.
    if chinese:
        spoken = _ARELIS_NAME.sub("阿瑞丽丝", spoken)
    else:
        spoken = _ARELIS_NAME.sub(_ARELIS_SPOKEN, spoken)
        # English Kokoro phonemizes with espeak. Espeak expands °, #, dates,
        # and percents into a different word count than phonemizer counted,
        # and the glyphs come out raw. Spell them before that call.
        spoken = _normalize_spoken_symbols(spoken)

    if max_chars > 0:
        spoken = _cap(spoken, max_chars)
    return spoken.strip()


# A lone short sentence plays in a second, then dead air until the next
# period arrives. Hold it. A long sentence covers the wait, so it can go.
_SHORT_CLIP_CHARS = 72
# Glue following sentences into one WAV so Kokoro keeps the breath across
# periods instead of restarting on every full stop.
_PACK_TARGET_CHARS = 160


def split_sentences(text: str, *, language: str = "en") -> list[str]:
    """Split prepared text on sentence ends.

    The voice service packs these into breaths before synthesis so a period
    is not its own clip. Stopping her still abandons the queue.
    """
    if not text.strip():
        return []
    out: list[str] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        pending = ""
        zh = str(language or "").lower().startswith("zh") or bool(
            re.search(r"[。！？]", block)
        )
        pattern = _SENTENCE_END_ZH if zh else _SENTENCE_END
        for piece in pattern.split(block):
            if not piece:
                continue
            candidate = f"{pending} {piece}".strip() if pending else piece
            if _ends_on_abbreviation(candidate):
                pending = candidate
                continue
            pending = ""
            out.append(candidate)
        if pending:
            out.append(pending)
    return [s for s in (part.strip() for part in out) if s]


def _sentence_complete(chunk: str) -> bool:
    trailing = (chunk or "").rstrip()
    if not trailing:
        return False
    if trailing[-1:] in "。！？":
        return True
    if trailing[-1:] not in ".!?" or _ends_on_abbreviation(trailing):
        return False
    # "27." is still open: the next character may be the fractional digit.
    # A period between two digits is not a sentence end. "27.22." is closed,
    # because that last period has no digit after it.
    if (
        trailing[-1] == "."
        and trailing[-2:-1].isdigit()
        and re.search(r"\d\.\d+\.$", trailing) is None
    ):
        return False
    return True


def next_speakable_units(
    prepared: str, already: int, *, finalize: bool, language: str = "en"
) -> tuple[list[str], int]:
    """Return new clips and how many sentences have now been handed off.

    `already` is a sentence count, not a clip count. The first sentence
    starts as soon as it is complete. Later short leftovers wait for a
    neighbor so she does not restart on every period. Neighboring
    sentences are glued into one clip until ``_PACK_TARGET_CHARS``.
    Finalize flushes whatever is left.
    """
    if already < 0:
        already = 0
    raw = (prepared or "").strip()
    if not raw:
        return [], already
    sentences = split_sentences(raw, language=language) or ([raw] if finalize else [])
    if already >= len(sentences):
        return [], already

    limit = len(sentences) if finalize or _sentence_complete(sentences[-1]) else len(sentences) - 1
    pending = sentences[already:limit]
    if not pending:
        return [], already
    # Later leftovers can wait for a neighbor. The first sentence of a
    # reply has to start now — holding it until finalize is how the
    # whole answer types out and she sits silent until Kokoro gets it.
    if (
        not finalize
        and already > 0
        and len(pending) == 1
        and len(pending[0]) < _SHORT_CLIP_CHARS
    ):
        return [], already

    clips: list[str] = []
    consumed = already
    buf: list[str] = []
    size = 0
    for sentence in pending:
        buf.append(sentence)
        size += len(sentence) + 1
        pack_at = 64 if _CJK_RUN.search(prepared or "") else _PACK_TARGET_CHARS
        if size >= pack_at:
            clips.append(" ".join(buf))
            consumed += len(buf)
            buf = []
            size = 0
    if buf:
        leftover_is_short = len(buf) == 1 and len(buf[0]) < _SHORT_CLIP_CHARS
        if finalize or not leftover_is_short or len(buf) >= 2:
            clips.append(" ".join(buf))
            consumed += len(buf)
        elif clips:
            # A trailing short after a full pack waits for more text.
            pass
        else:
            clips.append(" ".join(buf))
            consumed += len(buf)
    return clips, consumed


def _ends_on_abbreviation(chunk: str) -> bool:
    tail = chunk.rstrip().rstrip("\"')]")
    if not tail.endswith("."):
        return False
    word = re.split(r"[\s(]", tail[:-1])[-1].lower()
    if word in _ABBREVIATIONS:
        return True
    # A single initial ("J.") or a dotted acronym ("U.S.") is not a full stop.
    return len(word) <= 1 or bool(re.fullmatch(r"(?:[a-z]\.)+[a-z]", word))


def _drop_sources(text: str) -> str:
    """Cut the trailing Sources block, if the answer has one."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if _SOURCES_HEADING.match(line):
            return "\n".join(lines[:i])
    return text


def _speakable_line(raw: str) -> str | None:
    """Convert one line, or return None when it carries no speech."""
    line = raw.strip()
    if not line:
        return ""
    if _INDENTED_HR.match(line):
        return None
    if _TABLE_DIVIDER.match(line) and "|" in line and not re.search(r"[A-Za-z0-9]", line):
        return None
    if line.startswith("|"):
        cells = [c.strip() for c in line.strip("|").split("|")]
        cells = [c for c in cells if c]
        if not cells:
            return None
        line = ", ".join(cells)

    line = _BLOCKQUOTE.sub("", line)
    line = _HEADING.sub("", line)

    listed = bool(_BULLET.match(line) or _ORDERED.match(line))
    line = _BULLET.sub("", line)
    line = _ORDERED.sub("", line)

    line = _IMAGE.sub(" ", line)
    line = _LINK.sub(r"\1", line)
    line = _BARE_URL.sub(" ", line)
    line = _INLINE_CODE.sub(r"\1", line)
    line = _BOLD_ITALIC.sub(r"\2", line)
    line = _UNDERSCORE_EMPHASIS.sub(r"\2", line)
    line = _MULTI_SPACE.sub(" ", line).strip()

    if not line:
        return None
    # List items rarely end in punctuation. Without one the synthesizer runs
    # every bullet into the next as a single breathless sentence.
    if listed and line[-1] not in ".!?:;,":
        line = f"{line}."
    return line


def _cap(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    kept: list[str] = []
    used = 0
    for sentence in split_sentences(text):
        if used + len(sentence) + 1 > max_chars:
            break
        kept.append(sentence)
        used += len(sentence) + 1
    if kept:
        return " ".join(kept)
    return text[:max_chars].rstrip()


# espeak reads a digit string as more than one word, so the phonemizer's
# word count only matches once the number is already words.
_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)
_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
    "ninety",
)
_ORD_UNDER_20 = (
    "zeroth", "first", "second", "third", "fourth", "fifth", "sixth",
    "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
    "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
    "eighteenth", "nineteenth",
)
_ORD_TENS = (
    "", "", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth",
    "seventieth", "eightieth", "ninetieth",
)
_MONTH_FULL = (
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
)
_MONTH_INDEX = {
    alias: index
    for index, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for alias in names
}
_MONTH_WORD = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?"
)
_ISO_DATE = re.compile(
    r"(?<!\d)(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"
    r"(?:[T ](?P<h>\d{2}):(?P<min>\d{2})(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"(?!\d)"
)
_SLASH_YEAR = re.compile(
    r"(?<!\d)(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<y>\d{2,4})(?!\d)"
)
# Month names only when capitalized. "may" and "march" are ordinary words.
_MONTH_DAY = re.compile(
    rf"\b(?P<mon>{_MONTH_WORD})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:\s*,?\s*(?P<y>\d{{4}}))?\b"
)
_DAY_MONTH = re.compile(
    rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<mon>{_MONTH_WORD})\.?"
    rf"(?:\s*,?\s*(?P<y>\d{{4}}))?\b"
)
# A meridiem is required. Bare 12:00 and a 3:2 ratio are not clocks.
_CLOCK = re.compile(
    r"(?<!\d)(?P<h>\d{1,2}):(?P<m>\d{2})(?::\d{2})?\s*(?P<ap>[AaPp]\.?[Mm]\.?)(?!\w)"
)
# A leading N- is part of the quantity (60-75°F), not a second number left behind.
_DEGREE = re.compile(
    r"(?<![\w.])(?:(?P<lo>\d+(?:\.\d+)?)\s*-\s*)?"
    r"(?P<n>[+-]?\d+(?:\.\d+)?)\s*(?:°\s*(?P<u>[FfCc])|℉|℃|°)(?!\w)"
)
_TIME_RANGE = re.compile(
    r"(\d{1,2}:\d{2}(?:\s*[AaPp]\.?[Mm]\.?)?)\s*[\u2013\u2014]\s*(?=\d)"
)
_PERCENT = re.compile(
    r"(?<![\w.])(?:(?P<lo>\d+(?:\.\d+)?)\s*-\s*)?(?P<n>[+-]?\d+(?:\.\d+)?)\s*%"
)
# km/s/Mpc is one unit. A slash after the token means it keeps going.
_UNIT = re.compile(
    r"(?<!\w)(?P<n>[+-]?\d+(?:\.\d+)?)\s*(?P<u>km/h|km/s|m/s|mph)\b(?!/)",
    re.IGNORECASE,
)
_HASH_NUMBER = re.compile(r"(?<![\w#])#(?P<n>\d+)\b")
_TIMES = re.compile(
    r"(?<!\w)(?P<a>\d+(?:\.\d+)?)\s*\*\s*(?P<b>\d+(?:\.\d+)?)(?!\w)"
)
_UNIT_WORDS = {
    "mph": "miles per hour",
    "km/h": "kilometers per hour",
    "m/s": "meters per second",
    "km/s": "kilometers per second",
}


def _spell_cardinal(number: int) -> str:
    if number < 0:
        return "minus " + _spell_cardinal(-number)
    if number < 20:
        return _ONES[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        if ones == 0:
            return _TENS[tens]
        return f"{_TENS[tens]} {_ONES[ones]}"
    if number < 1000:
        hundreds, rest = divmod(number, 100)
        head = f"{_ONES[hundreds]} hundred"
        if rest == 0:
            return head
        return f"{head} {_spell_cardinal(rest)}"
    if number < 1_000_000:
        thousands, rest = divmod(number, 1000)
        head = f"{_spell_cardinal(thousands)} thousand"
        if rest == 0:
            return head
        return f"{head} {_spell_cardinal(rest)}"
    return str(number)


def _spell_ordinal(number: int) -> str:
    if number < 20:
        return _ORD_UNDER_20[number]
    if number < 100:
        tens, ones = divmod(number, 10)
        if ones == 0:
            return _ORD_TENS[tens]
        return f"{_TENS[tens]} {_ORD_UNDER_20[ones]}"
    return _spell_cardinal(number)


def _spell_year(year: int) -> str:
    if year < 1000 or year > 9999:
        return _spell_cardinal(year)
    if 2000 <= year < 2010:
        rest = year - 2000
        if rest == 0:
            return "two thousand"
        return "two thousand " + _spell_cardinal(rest)
    left, right = divmod(year, 100)
    head = _spell_cardinal(left)
    if right == 0:
        return f"{head} hundred"
    if right < 10:
        return f"{head} oh {_spell_cardinal(right)}"
    return f"{head} {_spell_cardinal(right)}"


def _spell_number(raw: str) -> str:
    text = raw.strip()
    sign = ""
    if text.startswith("+"):
        sign = "plus "
        text = text[1:]
    elif text.startswith("-"):
        sign = "minus "
        text = text[1:]
    if "." in text:
        whole, frac = text.split(".", 1)
        digits = " ".join(_ONES[int(ch)] for ch in frac if ch.isdigit())
        body = _spell_cardinal(int(whole or "0"))
        if digits:
            body = f"{body} point {digits}"
        return sign + body
    return sign + _spell_cardinal(int(text))


def _real_date(year: int | None, month: int, day: int) -> bool:
    try:
        date(year or 2024, month, day)
    except ValueError:
        return False
    return True


def _year_number(raw: str | None) -> int | None:
    if not raw:
        return None
    year = int(raw)
    if year < 100:
        return 2000 + year if year < 70 else 1900 + year
    return year


def _date_words(year: int | None, month: int, day: int) -> str | None:
    if not _real_date(year, month, day):
        return None
    spoken = f"{_MONTH_FULL[month - 1]} {_spell_ordinal(day)}"
    if year is not None:
        spoken = f"{spoken}, {_spell_year(year)}"
    return spoken


def _us_date(first: int, second: int, year: int | None) -> str | None:
    """Month/day/year, as in 10/15/2026.

    When the first number cannot be a month, try day/month.
    """
    if 1 <= first <= 12:
        spoken = _date_words(year, first, second)
        if spoken:
            return spoken
    if 1 <= second <= 12:
        return _date_words(year, second, first)
    return None


def _clock_parts(hour: int, ampm: str | None) -> tuple[int, str] | None:
    """12-hour number plus AM or PM, which espeak keeps as one word."""
    if ampm:
        if not 1 <= hour <= 12:
            return None
        mark = "AM" if ampm[0].lower() == "a" else "PM"
        return hour, mark
    if hour > 23:
        return None
    if hour == 0:
        return 12, "AM"
    if hour < 12:
        return hour, "AM"
    if hour == 12:
        return 12, "PM"
    return hour - 12, "PM"


def _spell_clock(hour: int, minute: int, ampm: str | None) -> str | None:
    if minute > 59:
        return None
    parts = _clock_parts(hour, ampm)
    if parts is None:
        return None
    hour12, half = parts
    if minute == 0:
        body = f"{_spell_cardinal(hour12)} o'clock"
    elif minute < 10:
        body = f"{_spell_cardinal(hour12)} oh {_spell_cardinal(minute)}"
    else:
        body = f"{_spell_cardinal(hour12)} {_spell_cardinal(minute)}"
    return f"{body} {half}"


def _sub_iso(match: re.Match[str]) -> str:
    year = int(match.group("y"))
    spoken = _date_words(year, int(match.group("m")), int(match.group("d")))
    if not spoken:
        return match.group(0)
    if match.group("h") is None:
        return spoken
    clock = _spell_clock(int(match.group("h")), int(match.group("min")), None)
    if not clock:
        return spoken
    return f"{spoken} at {clock}"


def _sub_slash_year(match: re.Match[str]) -> str:
    spoken = _us_date(
        int(match.group("a")),
        int(match.group("b")),
        _year_number(match.group("y")),
    )
    return spoken or match.group(0)


def _quantity(lo: str | None, raw: str) -> str:
    spoken = _spell_number(raw)
    if not lo:
        return spoken
    return f"{_spell_number(lo)} to {spoken}"


def _sub_named_date(match: re.Match[str]) -> str:
    month = _MONTH_INDEX.get(match.group("mon").lower())
    if month is None:
        return match.group(0)
    spoken = _date_words(_year_number(match.group("y")), month, int(match.group("d")))
    return spoken or match.group(0)


def _sub_clock(match: re.Match[str]) -> str:
    spoken = _spell_clock(int(match.group("h")), int(match.group("m")), match.group("ap"))
    return spoken or match.group(0)


def _sub_degree(match: re.Match[str]) -> str:
    raw = match.group(0)
    unit = match.group("u")
    number = _quantity(match.group("lo"), match.group("n"))
    if "℃" in raw or (unit and unit.lower() == "c"):
        return f"{number} degrees Celsius"
    if "℉" in raw or (unit and unit.lower() == "f"):
        return f"{number} degrees Fahrenheit"
    return f"{number} degrees"


def _sub_percent(match: re.Match[str]) -> str:
    return f"{_quantity(match.group('lo'), match.group('n'))} percent"


def _sub_unit(match: re.Match[str]) -> str:
    name = _UNIT_WORDS[match.group("u").lower()]
    return f"{_spell_number(match.group('n'))} {name}"


def _sub_hash(match: re.Match[str]) -> str:
    return "number " + _spell_cardinal(int(match.group("n")))


def _sub_times(match: re.Match[str]) -> str:
    return f"{_spell_number(match.group('a'))} times {_spell_number(match.group('b'))}"


def _normalize_spoken_symbols(text: str) -> str:
    """Spell the symbols espeak would otherwise read raw.

    One pass, English only. Kokoro's English path is espeak through
    phonemizer, and that stack has no word normalizer (misaki's English
    one pulls spaCy, which this build does not ship). The chat line is
    already on screen by the time this runs.
    """
    if not text:
        return ""
    spoken = _ISO_DATE.sub(_sub_iso, text)
    spoken = _SLASH_YEAR.sub(_sub_slash_year, spoken)
    spoken = _MONTH_DAY.sub(_sub_named_date, spoken)
    spoken = _DAY_MONTH.sub(_sub_named_date, spoken)
    spoken = _TIME_RANGE.sub(r"\1 to ", spoken)
    spoken = _CLOCK.sub(_sub_clock, spoken)
    spoken = _DEGREE.sub(_sub_degree, spoken)
    spoken = _PERCENT.sub(_sub_percent, spoken)
    spoken = _UNIT.sub(_sub_unit, spoken)
    spoken = _HASH_NUMBER.sub(_sub_hash, spoken)
    spoken = spoken.replace("\u2014", ", ").replace("\u2013", ", ")
    spoken = _TIMES.sub(_sub_times, spoken)
    spoken = spoken.replace("*", "").replace("`", "")
    spoken = spoken.replace("#", "")
    spoken = spoken.replace("°", " degrees ").replace("℉", " degrees Fahrenheit ")
    spoken = spoken.replace("℃", " degrees Celsius ").replace("%", " percent ")
    spoken = _MULTI_SPACE.sub(" ", spoken)
    spoken = re.sub(r"\s+([,.;:!?])", r"\1", spoken)
    return spoken.strip()
