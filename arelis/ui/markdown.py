"""Markdown to the HTML subset QTextEdit understands.

Model answers are markdown. The chat bubble used to insert them as plain text,
so "**Sources:**" reached the screen with its asterisks showing and a fenced
code block arrived as a row of backticks. This renders the subset that actually
turns up in model output: headings, lists, tables, code, quotes, rules, TeX
math, and the usual inline marks. Math goes through ``flatten_latex`` so a
CAS ``latex:`` line reads as unicode here and in every file she writes.

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
import re

from arelis.mathtext import flatten_for_render
from arelis.mathtext import flatten_latex as flatten_latex
from arelis.ui.theme import COLORS, FONTS, SPACE

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
_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<link>\[[^\]\n]*\]\([^)\s]+\))"
    r"|(?P<auto>(?<![\w/])https?://[^\s<>\"'`\])]+)"
    r"|(?P<strong>\*\*[^\n]+?\*\*|(?<!\w)__[^\n]+?__(?!\w))"
    r"|(?P<strike>~~[^\n]+?~~)"
    r"|(?P<em>\*[^*\n]+?\*|(?<!\w)_[^_\n]+?_(?!\w))"
)
_LINK_PARTS = re.compile(r"^\[([^\]\n]*)\]\(([^)\s]+)\)$")


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


def _style_math() -> str:
    return (
        f"text-align:center; font-style:italic; color:{COLORS['text']}; "
        f"margin:{SPACE['gap']}px 0 {SPACE['gap']}px 0;"
    )


def render_markdown(text: str) -> str:
    """Render markdown as Qt rich text. Always returns escaped, safe HTML."""
    if not text:
        return ""
    text, slots = flatten_for_render(text)
    token = _SLOTS.set(tuple(slots))
    try:
        return _render_lines(text)
    finally:
        _SLOTS.reset(token)


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
            out.append(f'<p style="{_style_math()}">{_escape(body)}</p>')
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


def _put_math(html_text: str) -> str:
    slots = _SLOTS.get()
    if not slots:
        return html_text

    def put(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        if 0 <= idx < len(slots):
            return _escape(slots[idx])
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
        body.append(render_inline(line.strip()))
        i += 1
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
