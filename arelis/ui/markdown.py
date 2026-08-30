"""Markdown to the HTML subset QTextEdit understands.

Model answers are markdown. The chat bubble used to insert them as plain text,
so "**Sources:**" reached the screen with its asterisks showing and a fenced
code block arrived as a row of backticks. This renders the subset that actually
turns up in model output: headings, lists, tables, code, quotes, rules, and the
usual inline marks.

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

import html
import re

from arelis.ui.theme import COLORS, FONTS

# Only schemes worth making clickable. Anything else renders as plain text, so a
# link a model invented cannot become a live handler for some other protocol.
_SAFE_SCHEMES = ("http://", "https://", "mailto:")

_FENCE = re.compile(r"^\s*```+\s*[\w+#.-]*\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)\d{1,9}[.)]\s+(.*)$")
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

# The theme quotes font names with double quotes, which would close the style
# attribute the moment it was interpolated into one and drop everything after it.
_MONO = FONTS["mono"].replace('"', "'")
_CODE_BG = COLORS["code_fill"]
_EDGE = COLORS["edge_soft"]

# No border here. Qt's rich text engine keeps borders on table cells but drops
# them on block elements, so declaring one would be styling that never renders.
# The background is what separates a code block from the prose around it.
_STYLE_PRE = (
    f"background-color:{_CODE_BG}; font-family:{_MONO}; "
    f"font-size:12px; color:{COLORS['text']}; margin:6px 0 6px 0;"
)
_STYLE_CODE = (
    f"background-color:{_CODE_BG}; font-family:{_MONO}; "
    f"font-size:12px; color:{COLORS['accent']};"
)
_STYLE_QUOTE = (
    f"border-left:2px solid {COLORS['accent']}; color:{COLORS['text_dim']}; "
    "margin:6px 0 6px 4px; padding-left:8px;"
)
_STYLE_RULE = f"border:none; border-top:1px solid {_EDGE}; margin:8px 0 8px 0;"
_STYLE_LINK = f"color:{COLORS['accent2']}; text-decoration:underline;"
_STYLE_TABLE = f"border-collapse:collapse; margin:8px 0 10px 0; color:{COLORS['text']};"
_STYLE_TH = (
    f"border:none; border-bottom:1px solid {COLORS['hairline_faint']}; "
    f"color:{COLORS['accent2']}; font-weight:500;"
)
_STYLE_TD = "border:none;"
# Cell spacing comes from the cellpadding attribute. Qt reads that rather than
# CSS padding on the cells, so setting it in the style has no effect.
_TABLE_ATTRS = 'border="0" cellspacing="0" cellpadding="6"'
_HEADING_SIZES = {1: 17, 2: 15, 3: 14, 4: 13, 5: 13, 6: 13}


_LATEX_BLOCK = re.compile(r"\\\[(.+?)\\\]", re.S)
_LATEX_INLINE = re.compile(r"\\\((.+?)\\\)")
_LATEX_DOLLARS_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.S)
# Only pair $…$ when it looks like math, so "$5 and $\log x$" keeps the price.
_LATEX_DOLLARS_INLINE = re.compile(
    r"(?<!\$)\$(?![\d\s$])([^$\n]+)\$(?!\$)"
)
_LATEX_FRAC = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_LATEX_SUP = {
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
}
# Named TeX that must stay readable. A bare \\[A-Za-z]+ wipe used to delete
# \\log, so 25x\\log(x-3) rendered as 25x(x-3).
_LATEX_WORDS = (
    (r"\iiint", "∭"),
    (r"\iint", "∬"),
    (r"\int", "∫"),
    (r"\sum", "Σ"),
    (r"\prod", "Π"),
    (r"\partial", "∂"),
    (r"\infty", "∞"),
    (r"\cdot", "·"),
    (r"\times", "×"),
    (r"\pm", "±"),
    (r"\leq", "≤"),
    (r"\geq", "≥"),
    (r"\neq", "≠"),
    (r"\approx", "≈"),
    (r"\pi", "π"),
    (r"\ln", "ln"),
    (r"\log", "log"),
    (r"\sin", "sin"),
    (r"\cos", "cos"),
    (r"\tan", "tan"),
    (r"\exp", "exp"),
    (r"\sqrt", "√"),
    (r"\left", ""),
    (r"\right", ""),
    (r"\mathrm", ""),
    (r"\operatorname", ""),
    (r"\,", " "),
    (r"\;", " "),
    (r"\!", ""),
    (r"\ ", " "),
)


def flatten_latex(text: str) -> str:
    """Turn TeX delimiters into readable chat text without dropping operators."""

    def _plain(src: str) -> str:
        s = (src or "").strip()
        s = _LATEX_FRAC.sub(r"(\1)/(\2)", s)
        for cmd, repl in _LATEX_WORDS:
            s = s.replace(cmd, repl)
        s = re.sub(r"\\([A-Za-z]+)", r"\1", s)
        s = re.sub(
            r"\^\{?(\d+)\}?",
            lambda m: (
                "".join(_LATEX_SUP.get(ch, "^" + ch) for ch in m.group(1))
                if m.group(1).isdigit()
                else "^" + m.group(1)
            ),
            s,
        )
        return re.sub(r"[{}]", "", s).strip()

    def _looks_like_math(src: str) -> bool:
        return bool(re.search(r"[\\^_{]|\\[A-Za-z]", src))

    text = _LATEX_DOLLARS_BLOCK.sub(lambda m: "\n" + _plain(m.group(1)) + "\n", text)
    text = _LATEX_BLOCK.sub(lambda m: "\n" + _plain(m.group(1)) + "\n", text)
    text = _LATEX_INLINE.sub(lambda m: _plain(m.group(1)), text)

    def _dollar(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not _looks_like_math(inner):
            return match.group(0)
        return _plain(inner)

    return _LATEX_DOLLARS_INLINE.sub(_dollar, text)


def render_markdown(text: str) -> str:
    """Render markdown as Qt rich text. Always returns escaped, safe HTML."""
    if not text:
        return ""
    text = flatten_latex(text)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if _FENCE.match(line):
            i, block = _take_code_block(lines, i)
            out.append(block)
            continue
        if not line.strip():
            i += 1
            continue
        if _RULE.match(line):
            out.append(f'<hr style="{_STYLE_RULE}" />')
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
        if _BULLET.match(line) or _NUMBER.match(line):
            i, block = _take_list(lines, i)
            out.append(block)
            continue

        i, block = _take_paragraph(lines, i)
        out.append(block)
    return "".join(out)


def render_inline(text: str) -> str:
    """Render one line's inline marks. Text outside a match is escaped as-is."""
    out: list[str] = []
    pos = 0
    for match in _INLINE.finditer(text):
        out.append(_escape(text[pos : match.start()]))
        out.append(_render_match(match))
        pos = match.end()
    out.append(_escape(text[pos:]))
    return "".join(out)


def _render_match(match: re.Match[str]) -> str:
    kind = match.lastgroup
    raw = match.group()
    # Emphasis can wrap anything, including code and links, so its body goes
    # back through the scanner. Recursion terminates because the body is always
    # shorter than the match that produced it.
    if kind == "code":
        return f'<code style="{_STYLE_CODE}">{_escape(raw[1:-1])}</code>'
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
    return f'<a href="{_escape(href, quote=True)}" style="{_STYLE_LINK}">{label}</a>'


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
    return i, f'<pre style="{_STYLE_PRE}">{code}</pre>'


def _take_quote(lines: list[str], i: int) -> tuple[int, str]:
    body: list[str] = []
    while i < len(lines):
        match = _QUOTE.match(lines[i])
        if match is None:
            break
        body.append(render_inline(match.group(1)))
        i += 1
    return i, f'<p style="{_STYLE_QUOTE}">{"<br/>".join(body)}</p>'


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


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        _FENCE.match(line)
        or _RULE.match(line)
        or _HEADING.match(line)
        or _QUOTE.match(line)
        or _BULLET.match(line)
        or _NUMBER.match(line)
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
            if i + 1 < len(lines) and (
                _BULLET.match(lines[i + 1]) or _NUMBER.match(lines[i + 1])
            ):
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
        # Qt's default <ul>/<ol> left margin hangs outside the chat bubble and
        # sits left of the "arelis" label — keep markers inside the glass.
        list_style = (
            'style="margin:4px 0 4px 0; padding-left:18px; margin-left:0;"'
        )
        if not kinds or indent > indents[-1]:
            kinds.append(kind)
            indents.append(indent)
            parts.append(f"<{kind} {list_style}>")
        elif kinds[-1] != kind:
            parts.append(f"</{kinds.pop()}>")
            kinds.append(kind)
            parts.append(f"<{kind} {list_style}>")

        parts.append(f"<li>{render_inline(match.group(2))}</li>")
        i += 1
    while kinds:
        parts.append(f"</{kinds.pop()}>")
    return i, "".join(parts)


def _is_table(lines: list[str], i: int) -> bool:
    return (
        "|" in lines[i]
        and i + 1 < len(lines)
        and _TABLE_RULE.match(lines[i + 1]) is not None
    )


def _take_table(lines: list[str], i: int) -> tuple[int, str]:
    header = _split_row(lines[i])
    aligns = [_alignment(cell) for cell in _split_row(lines[i + 1])]
    i += 2
    rows: list[list[str]] = []
    while i < len(lines) and lines[i].strip() and "|" in lines[i]:
        rows.append(_split_row(lines[i]))
        i += 1

    parts = [f'<table {_TABLE_ATTRS} style="{_STYLE_TABLE}"><tr>']
    for column, cell in enumerate(header):
        parts.append(
            f'<th style="{_STYLE_TH} text-align:{_align_of(aligns, column)};">'
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
