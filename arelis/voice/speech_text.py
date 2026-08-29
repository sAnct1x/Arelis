"""Turn an on-screen answer into something worth hearing.

An answer is written to be read: it carries markdown, fenced code, tables, a
Sources list, and bare URLs. Handing that to a synthesizer verbatim produces
"asterisk asterisk Sources colon asterisk asterisk, one, Example Domain, h t t p
s colon slash slash", which is unusable. Everything here strips presentation
without touching meaning.

Nothing is truncated by default. Long answers are handled by letting the user
interrupt, not by cutting the text: see the sentence queue in the voice service,
which starts speaking after the first sentence and can be abandoned mid-answer.
max_chars stays available as a runaway guard and is off unless configured.
"""
from __future__ import annotations

import re

# A Sources block is a citation apparatus, not prose. It is the single worst
# thing to read aloud: a list of URLs spelled character by character.
_SOURCES_HEADING = re.compile(r"^\s*\**\s*sources\s*:?\s*\**\s*$", re.IGNORECASE)

_FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_INDENTED_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL | re.IGNORECASE)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BARE_URL = re.compile(r"<?\b(?:https?://|www\.)\S+>?")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
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


def prepare_spoken_text(text: str, *, max_chars: int = 0) -> str:
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
    spoken = scrub_cjk_runs(spoken)
    spoken = _MULTI_NEWLINE.sub("\n\n", spoken)
    # A single newline inside a paragraph is a wrap, not a pause.
    spoken = re.sub(r"(?<!\n)\n(?!\n)", " ", spoken)
    spoken = _MULTI_SPACE.sub(" ", spoken)
    spoken = "\n\n".join(part.strip() for part in spoken.split("\n\n") if part.strip())
    # Phonetic spelling for Piper (persona text never reaches TTS).
    spoken = _ARELIS_NAME.sub(_ARELIS_SPOKEN, spoken)

    if max_chars > 0:
        spoken = _cap(spoken, max_chars)
    return spoken.strip()


def split_sentences(text: str) -> list[str]:
    """Split prepared text into synthesis units.

    The voice service synthesizes and plays these one at a time so speech starts
    about a second after the answer lands instead of after the whole thing is
    rendered, and so stopping her only has to abandon a queue.
    """
    if not text.strip():
        return []
    out: list[str] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        pending = ""
        for piece in _SENTENCE_END.split(block):
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


def next_speakable_units(
    prepared: str, already: int, *, finalize: bool
) -> list[str]:
    """Return synthesis units that are newly safe to speak.

    `already` is how many units from this prepared text have been handed to
    Piper. While the answer is still streaming (`finalize=False`), the last
    unit is held back: it may still be growing. On the final pass every
    remaining unit is returned so a one-sentence answer still gets spoken.
    """
    if not prepared.strip():
        return []
    units = split_sentences(prepared) or [prepared.strip()]
    if already < 0:
        already = 0
    if already >= len(units):
        return []
    if finalize:
        return units[already:]
    # A complete trailing sentence can start audio before the turn ends.
    trailing = units[-1].rstrip()
    if trailing[-1:] in ".!?" and not _ends_on_abbreviation(trailing):
        return units[already:]
    # Hold the trailing unit until another sentence appears or the turn ends.
    if len(units) <= already + 1:
        return []
    return units[already:-1]


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
