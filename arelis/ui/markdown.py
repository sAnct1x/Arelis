"""Markdown to the HTML subset QTextEdit understands.

Model answers are markdown. The chat bubble used to insert them as plain text,
so "**Sources:**" reached the screen with its asterisks showing and a fenced
code block arrived as a row of backticks. This renders the subset that actually
turns up in model output: headings, lists, tables, code, quotes, rules, TeX
math, and the usual inline marks. Math goes through ``flatten_latex`` so a
CAS ``latex:`` line reads as unicode here and in every file she writes. An
image that names a chart this reply is already showing is left out. The
file-ready block is that picture. The path written in the markdown is not
loaded, so a local file outside the session output folder cannot be pulled
in from the reply. While a reply is still streaming, a trailing image
mark that has not closed is left out. The finished reply keeps that
text.

Two rules shape the implementation.

Nothing from the source text is emitted as markup. Every span is escaped before
a tag goes near it, and the only tags that reach the document are the ones
generated here. Model text can repeat whatever a scraped page contained, so
letting raw HTML through would let markup from a fetched page render itself
inside an answer, images included.

Styling is inline. Qt style sheets apply to widgets, not to the rich text inside
them, so a document-level class hook would do nothing and the colours have to
travel on the tags.
"""

from __future__ import annotations

import contextvars
import html
import logging
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from arelis.mathtext import flatten_for_render
from arelis.mathtext import flatten_latex as flatten_latex
from arelis.ui.theme import COLORS, FONTS, SPACE

log = logging.getLogger(__name__)

# index, tex, unicode fallback, display flag. None means keep the unicode.
MathHook = Callable[[int, str, str, bool], str | None]

# Only schemes worth making clickable. Anything else renders as plain text, so a
# link a model invented cannot become a live handler for some other protocol.
_SAFE_SCHEMES = ("http://", "https://", "mailto:")

_FENCE = re.compile(r"^\s*```+\s*[\w+#.-]*\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
# Item text after the marker must be non-empty. "391. " (number, period,
# trailing space, nothing else) is a bare answer, not an empty <li>.
_NUMBER = re.compile(r"^(\s*)\d{1,9}[.)]\s+(\S.*)$")
_TABLE_RULE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")

# One pass over a line of prose. A single alternation rather than a chain of
# substitutions, because chained passes re-enter their own output: an autolink
# pass would rewrite the href of a link the previous pass just produced.
# Image is before link. ![alt](src) would otherwise match as a link and leave
# the "!" as text in front of it. The open form is that same mark before the
# closing parenthesis. It is not part of this scanner. Streaming drops a
# trailing open mark before render, and the finished reply leaves it as text.
_IMAGE_ALT = r"[^\]\n]*"
_IMAGE_SRC = r"[^)\s]+"
_IMAGE_CLOSED = rf"!\[{_IMAGE_ALT}\]\({_IMAGE_SRC}\)"
_IMAGE_OPEN = re.compile(rf"!\[{_IMAGE_ALT}(?:\](?:\([^)\s]*)?)?$")
_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    rf"|(?P<image>{_IMAGE_CLOSED})"
    r"|(?P<link>\[[^\]\n]*\]\([^)\s]+\))"
    r"|(?P<auto>(?<![\w/])https?://[^\s<>\"'`\])]+)"
    r"|(?P<strong>\*\*[^\n]+?\*\*|(?<!\w)__[^\n]+?__(?!\w))"
    r"|(?P<strike>~~[^\n]+?~~)"
    r"|(?P<em>\*[^*\n]+?\*|(?<!\w)_[^_\n]+?_(?!\w))"
)
_LINK_PARTS = re.compile(r"^\[([^\]\n]*)\]\(([^)\s]+)\)$")
_IMAGE_PARTS = re.compile(rf"^!\[({_IMAGE_ALT})\]\(({_IMAGE_SRC})\)$")


def _mono() -> str:
    # Theme quotes font names with double quotes, which would close a style
    # attribute the moment they were interpolated into one.
    return FONTS["mono"].replace('"', "'")


def _style_pre() -> str:
    return (
        f"background-color:{COLORS['code_fill']}; font-family:{_mono()}; "
        f"font-size:12px; color:{COLORS['text']}; "
        f"margin:{SPACE['gap']}px 0 {SPACE['gap']}px 0;"
    )


def _style_code() -> str:
    return (
        f"background-color:{COLORS['code_fill']}; font-family:{_mono()}; "
        f"font-size:12px; color:{COLORS['accent']};"
    )


def _style_quote() -> str:
    return (
        f"border-left:2px solid {COLORS['accent']}; color:{COLORS['text_dim']}; "
        f"margin:{SPACE['gap']}px 0 {SPACE['gap']}px {SPACE['micro']}px; "
        f"padding-left:{SPACE['gap']}px;"
    )


def _style_rule() -> str:
    return (
        f"border:none; border-top:1px solid {COLORS['edge_soft']}; "
        f"margin:{SPACE['gap']}px 0 {SPACE['gap']}px 0;"
    )


def _style_link() -> str:
    return f"color:{COLORS['accent2']}; text-decoration:underline;"


def _style_table() -> str:
    return f"border-collapse:collapse; margin:8px 0 10px 0; color:{COLORS['text']};"


def _style_th() -> str:
    return (
        f"border:none; border-bottom:1px solid {COLORS['hairline_faint']}; "
        f"color:{COLORS['accent2']}; font-weight:500;"
    )


_STYLE_TD = "border:none;"
# Cell spacing comes from the cellpadding attribute. Qt reads that rather than
# CSS padding on the cells, so setting it in the style has no effect.
_TABLE_ATTRS = 'border="0" cellspacing="0" cellpadding="6"'
_HEADING_SIZES = {1: 17, 2: 15, 3: 14, 4: 13, 5: 13, 6: 13}


_MATH_TOKEN = re.compile(r"^\[\[ARELIS_MATH_(\d+)\]\]$")
_IMATH = re.compile(r"\[\[ARELIS_IMATH_(\d+)\]\]")
_CODE_SPAN = re.compile(r"`[^`\n]+`")
_STAR = "\ue000"
_SLOTS: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("math_slots", default=())
_RAW: contextvars.ContextVar[tuple[tuple[str, bool], ...]] = contextvars.ContextVar(
    "math_raw", default=()
)
_MATH: contextvars.ContextVar[MathHook | None] = contextvars.ContextVar("math_hook", default=None)
# Absolute paths of charts the transcript is already showing for this reply.
# The model's image target is compared to these. It is never opened.
_SHOWN_CHARTS: contextvars.ContextVar[tuple[Path, ...]] = contextvars.ContextVar(
    "shown_charts", default=()
)


# Zen Kaku has no Greek. IBM Plex and Segoe do, so a formula that stays
# unicode (simple math, or an image the engine refused) is still readable.
_MATH_FACE = "'IBM Plex Sans', 'Segoe UI', sans-serif"


def _style_math() -> str:
    return (
        f"text-align:center; font-style:italic; font-family:{_MATH_FACE}; "
        f"color:{COLORS['text']}; "
        f"margin:{SPACE['gap']}px 0 {SPACE['gap']}px 0;"
    )


def _style_math_image() -> str:
    return (
        f"text-align:center; color:{COLORS['text']}; "
        f"margin:{SPACE['gap']}px 0 {SPACE['gap']}px 0;"
    )


def _fence_is_open(text: str) -> bool:
    """True when a fenced block is still open at the end of text."""
    open_fence = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            open_fence = not open_fence
    return open_fence


def _drop_streaming_image_tail(text: str) -> str:
    """Drop a trailing image mark that has not closed.

    Only the live end of a stream. A newline means that line is finished,
    and an unclosed mark there is text, same as in the finished reply.
    An open code fence keeps its tail, because the fence shows the source.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized or normalized.endswith("\n") or _fence_is_open(normalized):
        return normalized
    split_at = normalized.rfind("\n")
    line = normalized[split_at + 1 :]
    match = _IMAGE_OPEN.search(line)
    if match is None or line[: match.start()].count("`") % 2 == 1:
        return normalized
    return normalized[: split_at + 1 + match.start()]


def render_markdown(
    text: str,
    *,
    math: MathHook | None = None,
    shown_files: Iterable[str] | None = None,
    streaming: bool = False,
) -> str:
    """Render markdown as Qt rich text. Always returns escaped, safe HTML.

    ``math`` is optional. Leave it unset and every formula stays the unicode
    line this function has always returned. Chat passes a hook that may turn
    one span into an image tag; None from the hook keeps the unicode.

    ``shown_files`` are charts this reply is already showing. An image
    reference to one of them is left out. The picture stays the file-ready
    block, so it is not drawn a second time. The reference itself is not
    opened.

    ``streaming`` is for the open bubble. A trailing image mark that has
    not closed yet is left out, because it is still arriving. The finished
    reply leaves the flag unset, and that same mark is shown as text.
    """
    if not text:
        return ""
    # Drop from the source, before math tokens rewrite the tail.
    if streaming:
        text = _drop_streaming_image_tail(text)
    if not text:
        return ""
    raw: list[tuple[str, bool]] | None = [] if math is not None else None
    text, slots = flatten_for_render(text, raw=raw)
    if math is not None:
        from arelis.ui.math_images import begin_reply

        begin_reply()
    shown = _chart_paths(shown_files)
    token = _SLOTS.set(tuple(slots))
    raw_token = _RAW.set(tuple(raw or ()))
    math_token = _MATH.set(math)
    shown_token = _SHOWN_CHARTS.set(shown)
    try:
        return _render_lines(text)
    finally:
        _SLOTS.reset(token)
        _RAW.reset(raw_token)
        _MATH.reset(math_token)
        _SHOWN_CHARTS.reset(shown_token)


def _render_lines(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        math = _MATH_TOKEN.match(line.strip())
        if math:
            idx = int(math.group(1))
            slots = _SLOTS.get()
            body = slots[idx] if 0 <= idx < len(slots) else line.strip()
            image = _formula_html(idx)
            if image:
                out.append(f'<p style="{_style_math_image()}">{image}</p>')
            else:
                out.append(f'<p style="{_style_math()}">{_visible_math(body)}</p>')
            i += 1
            continue

        if _FENCE.match(line):
            i, block = _take_code_block(lines, i)
            out.append(block)
            continue
        if not line.strip():
            i += 1
            continue
        if _RULE.match(line):
            out.append(f'<hr style="{_style_rule()}" />')
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            size = _HEADING_SIZES[len(heading.group(1))]
            out.append(
                f'<p style="font-size:{size}px; font-weight:600; '
                f'color:{COLORS["accent"]}; margin:8px 0 4px 0;">'
                f"{render_inline(heading.group(2))}</p>"
            )
            i += 1
            continue
        if _QUOTE.match(line):
            i, block = _take_quote(lines, i)
            out.append(block)
            continue
        if _is_table(lines, i):
            i, block = _take_table(lines, i)
            out.append(block)
            continue
        if _BULLET.match(line) or (_NUMBER.match(line) and not _lone_sentence_not_a_list(lines, i)):
            i, block = _take_list(lines, i)
            out.append(block)
            continue

        i, block = _take_paragraph(lines, i)
        out.append(block)
    return "".join(out)


def _shield_stars(text: str) -> str:
    """Turn \\* outside code into a placeholder so emphasis cannot eat it."""
    parts: list[str] = []
    pos = 0
    for match in _CODE_SPAN.finditer(text):
        parts.append(text[pos : match.start()].replace("\\*", _STAR))
        parts.append(match.group())
        pos = match.end()
    parts.append(text[pos:].replace("\\*", _STAR))
    return "".join(parts)


def _formula_html(idx: int) -> str | None:
    """Image tag for one math span, or None to keep today's unicode."""
    hook = _MATH.get()
    if hook is None:
        return None
    raws = _RAW.get()
    if idx < 0 or idx >= len(raws):
        return None
    slots = _SLOTS.get()
    plain = slots[idx] if 0 <= idx < len(slots) else ""
    tex, display = raws[idx]
    try:
        html_text = hook(idx, tex, plain, display)
    except Exception:
        log.exception("math image hook failed")
        return None
    if not html_text:
        return None
    return html_text


def _visible_math(body: str) -> str:
    """Unicode math in a face that actually has the glyphs."""
    return f'<span style="font-family:{_MATH_FACE};">{_escape(body)}</span>'


def _put_math(html_text: str) -> str:
    slots = _SLOTS.get()
    if not slots and _MATH.get() is None:
        return html_text

    def put(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        image = _formula_html(idx)
        if image:
            return image
        if 0 <= idx < len(slots):
            return _visible_math(slots[idx])
        return match.group(0)

    return _IMATH.sub(put, html_text)


def render_inline(text: str) -> str:
    """Render one line's inline marks. Text outside a match is escaped as-is."""
    text = _shield_stars(text)
    out: list[str] = []
    pos = 0
    for match in _INLINE.finditer(text):
        out.append(_escape(text[pos : match.start()]))
        out.append(_render_match(match))
        pos = match.end()
    out.append(_escape(text[pos:]))
    return _put_math("".join(out).replace(_STAR, "*"))


def _render_match(match: re.Match[str]) -> str:
    kind = match.lastgroup
    raw = match.group()
    # Emphasis can wrap anything, including code and links, so its body goes
    # back through the scanner. Recursion terminates because the body is always
    # shorter than the match that produced it.
    if kind == "code":
        return f'<code style="{_style_code()}">{_escape(raw[1:-1])}</code>'
    if kind == "image":
        return _render_image(raw)
    if kind == "link":
        parts = _LINK_PARTS.match(raw)
        if parts is None:
            return _escape(raw)
        return _anchor(parts.group(2), render_inline(parts.group(1)) or _escape(parts.group(2)))
    if kind == "auto":
        return _anchor(raw, _escape(raw))
    if kind == "strong":
        return f"<b>{render_inline(raw.strip('*_'))}</b>"
    if kind == "strike":
        return f"<s>{render_inline(raw.strip('~'))}</s>"
    if kind == "em":
        return f"<i>{render_inline(raw.strip('*_'))}</i>"
    return _escape(raw)


def _chart_paths(files: Iterable[str] | None) -> tuple[Path, ...]:
    """Copy the transcript's chart paths. Nothing here is resolved or opened."""
    found: list[Path] = []
    seen: set[str] = set()
    for item in files or ():
        text = str(item or "").strip()
        if not text:
            continue
        path = Path(text)
        if not path.name or path.name in {".", ".."}:
            continue
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        found.append(path)
    return tuple(found)


def _render_image(raw: str) -> str:
    """One image mark.

    A chart this reply already shows contributes nothing. Emitting an image
    tag would paint it twice, and the address the model wrote is not a file
    we load. A path outside the session output folder therefore cannot be
    rendered from the reply. Any other finished image keeps the old reading:
    the bang stays text, and the bracket form is a link only for a safe
    scheme.
    """
    parts = _IMAGE_PARTS.match(raw)
    if parts is None:
        return _escape(raw)
    alt, src = parts.group(1), parts.group(2)
    if _refers_to_shown_chart(src):
        return ""
    label = render_inline(alt) or _escape(src)
    return "!" + _anchor(src, label)


def _refers_to_shown_chart(src: str) -> bool:
    """True when src names a chart already passed in as shown.

    Comparison is textual. Parent segments and schemes do not match, and an
    absolute path matches only when it is one of the known chart paths.
    """
    charts = _SHOWN_CHARTS.get()
    if not charts:
        return False
    raw = (src or "").strip().strip("<>")
    if not raw or "://" in raw or raw.lower().startswith("mailto:"):
        return False
    folded = raw.replace("\\", "/")
    while folded.startswith("./"):
        folded = folded[2:]
    if not folded:
        return False
    if folded.startswith("/") or _windows_abs(folded):
        return _exact_chart(folded, charts)
    parts = [part for part in folded.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return False
    for chart in charts:
        if len(parts) == 1 and parts[0] == chart.name:
            return True
        known = [part for part in chart.as_posix().split("/") if part]
        if len(parts) > 1 and len(parts) <= len(known) and known[-len(parts) :] == parts:
            return True
    return False


def _windows_abs(folded: str) -> bool:
    return len(folded) >= 3 and folded[0].isalpha() and folded[1] == ":" and folded[2] == "/"


def _exact_chart(folded: str, charts: tuple[Path, ...]) -> bool:
    for chart in charts:
        if folded == chart.as_posix() or folded == str(chart).replace("\\", "/"):
            return True
    return False


def _anchor(href: str, label: str) -> str:
    if not href.lower().startswith(_SAFE_SCHEMES):
        return label
    return f'<a href="{_escape(href, quote=True)}" style="{_style_link()}">{label}</a>'


def _escape(text: str, *, quote: bool = False) -> str:
    return html.escape(text, quote=quote)


def _take_code_block(lines: list[str], i: int) -> tuple[int, str]:
    """Consume a fenced block. An unterminated fence runs to end of text, which
    is what a stream cut off mid-block produces."""
    i += 1
    body: list[str] = []
    while i < len(lines) and not _FENCE.match(lines[i]):
        body.append(lines[i])
        i += 1
    i += 1
    code = _escape("\n".join(body))
    return i, f'<pre style="{_style_pre()}">{code}</pre>'


def _take_quote(lines: list[str], i: int) -> tuple[int, str]:
    body: list[str] = []
    while i < len(lines):
        match = _QUOTE.match(lines[i])
        if match is None:
            break
        body.append(render_inline(match.group(1)))
        i += 1
    return i, f'<p style="{_style_quote()}">{"<br/>".join(body)}</p>'


def _take_paragraph(lines: list[str], i: int) -> tuple[int, str]:
    """Consume prose up to the next blank line or block construct.

    Single newlines become breaks rather than spaces. Markdown would join them,
    but models use a bare newline to mean a new line, and reflowing an address
    or a short list of steps into one run reads as a mistake.
    """
    body: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip() or _starts_block(lines, i):
            break
        rendered = render_inline(line.strip())
        # A chart image that is already on screen renders as nothing. Skip
        # the line so the reply does not keep a blank paragraph for it.
        if rendered:
            body.append(rendered)
        i += 1
    if not body:
        return i, ""
    return i, f'<p style="margin:4px 0 4px 0;">{"<br/>".join(body)}</p>'


def _marker_value(line: str) -> int | None:
    if _NUMBER.match(line) is None:
        return None
    digits = re.match(r"\s*(\d+)", line)
    if digits is None:
        return None
    return int(digits.group(1))


def _lone_sentence_not_a_list(lines: list[str], i: int) -> bool:
    """A single "2026. That was..." is a sentence, not item 1 of a list.

    A run that starts at 1, or more than one item, stays a list.
    """
    number = _marker_value(lines[i])
    if number is None or number == 1:
        return False
    nxt = i + 1
    if nxt < len(lines) and not lines[nxt].strip():
        nxt += 1
    if nxt < len(lines) and (_BULLET.match(lines[nxt]) or _NUMBER.match(lines[nxt])):
        return False
    return True


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    numbered = bool(_NUMBER.match(line)) and not _lone_sentence_not_a_list(lines, i)
    return bool(
        _FENCE.match(line)
        or _MATH_TOKEN.match(line.strip())
        or _RULE.match(line)
        or _HEADING.match(line)
        or _QUOTE.match(line)
        or _BULLET.match(line)
        or numbered
        or _is_table(lines, i)
    )


def _take_list(lines: list[str], i: int) -> tuple[int, str]:
    """Consume one list, nesting by indentation.

    kinds and indents are pushed and popped together so the closing tags always
    match what was opened, including when a bulleted sub-list sits under a
    numbered parent.
    """
    kinds: list[str] = []
    indents: list[int] = []
    parts: list[str] = []
    while i < len(lines):
        if not lines[i].strip():
            # A blank line only ends the list if no item follows it.
            if i + 1 < len(lines) and (_BULLET.match(lines[i + 1]) or _NUMBER.match(lines[i + 1])):
                i += 1
                continue
            break
        bullet = _BULLET.match(lines[i])
        number = None if bullet else _NUMBER.match(lines[i])
        if bullet is None and number is None:
            break
        match = bullet or number
        assert match is not None
        kind = "ul" if bullet else "ol"
        indent = len(match.group(1))

        while indents and indent < indents[-1]:
            parts.append(f"</{kinds.pop()}>")
            indents.pop()
        if not kinds or indent > indents[-1]:
            kinds.append(kind)
            indents.append(indent)
            parts.append(_open_list(kind, lines[i]))
        elif kinds[-1] != kind:
            parts.append(f"</{kinds.pop()}>")
            kinds.append(kind)
            parts.append(_open_list(kind, lines[i]))

        parts.append(f"<li>{render_inline(match.group(2))}</li>")
        i += 1
    while kinds:
        parts.append(f"</{kinds.pop()}>")
    return i, "".join(parts)


def _open_list(kind: str, line: str) -> str:
    # Qt's default ul/ol left margin hangs outside the chat bubble.
    list_style = (
        f'style="margin:{SPACE["micro"]}px 0 {SPACE["micro"]}px 0; '
        f'padding-left:{SPACE["plate"]}px; margin-left:0;"'
    )
    start_attr = ""
    if kind == "ol":
        start = _marker_value(line)
        if start is not None and start != 1:
            start_attr = f' start="{start}"'
    return f"<{kind}{start_attr} {list_style}>"


def _is_table(lines: list[str], i: int) -> bool:
    return "|" in lines[i] and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1]) is not None


def _take_table(lines: list[str], i: int) -> tuple[int, str]:
    header = _split_row(lines[i])
    aligns = [_alignment(cell) for cell in _split_row(lines[i + 1])]
    i += 2
    rows: list[list[str]] = []
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        rows.append(_split_row(lines[i]))
        i += 1

    parts = [f'<table {_TABLE_ATTRS} style="{_style_table()}"><tr>']
    for column, cell in enumerate(header):
        parts.append(
            f'<th style="{_style_th()} text-align:{_align_of(aligns, column)};">'
            f"{render_inline(cell)}</th>"
        )
    parts.append("</tr>")
    for row in rows:
        parts.append("<tr>")
        # Pad or trim to the header width: a ragged row would otherwise shift
        # every following cell one column left.
        for column in range(len(header)):
            cell = row[column] if column < len(row) else ""
            parts.append(
                f'<td style="{_STYLE_TD} text-align:{_align_of(aligns, column)};">'
                f"{render_inline(cell)}</td>"
            )
        parts.append("</tr>")
    parts.append("</table>")
    return i, "".join(parts)


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _alignment(rule_cell: str) -> str:
    cell = rule_cell.strip()
    if cell.startswith(":") and cell.endswith(":"):
        return "center"
    if cell.endswith(":"):
        return "right"
    return "left"


def _align_of(aligns: list[str], column: int) -> str:
    return aligns[column] if column < len(aligns) else "left"
