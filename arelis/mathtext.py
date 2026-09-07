"""TeX to a readable unicode line.

Chat, PDFs, Word, CSV, and markdown all go through this so a CAS ``latex:``
line lands the same way everywhere. Qt cannot paint MathJax; neither can a
spreadsheet. Unicode is the one form every surface can show.
"""

from __future__ import annotations

import re

# Display math becomes its own paragraph. Inline $…$ stays in the sentence.
_DISPLAY_DOLLARS = re.compile(r"\$\$(.+?)\$\$", re.S)
_DISPLAY_BRACKETS = re.compile(r"\\\[(.+?)\\\]", re.S)
_INLINE_PARENS = re.compile(r"\\\((.+?)\\\)")
# Pair $…$ only when it looks like math, so "$5 and $\log x$" keeps the price.
_INLINE_DOLLARS = re.compile(r"(?<!\$)\$(?![\d\s$])([^$\n]+)\$(?!\$)")

_FENCE = re.compile(r"^```")

_SUP = {
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
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
    "n": "ⁿ",
    "i": "ⁱ",
    "a": "\u1d43",
    "b": "\u1d47",
    "c": "\u1d9c",
    "d": "\u1d48",
    "e": "\u1d49",
    "f": "\u1da0",
    "g": "\u1d4d",
    "h": "\u02b0",
    "k": "\u1d4f",
    "l": "\u02e1",
    "m": "\u1d50",
    "o": "\u1d52",
    "p": "\u1d56",
    "r": "\u02b3",
    "s": "\u02e2",
    "t": "\u1d57",
    "u": "\u1d58",
    "v": "\u1d5b",
    "w": "\u02b7",
    "x": "\u02e3",
    "y": "\u02b8",
    "z": "\u1dbb",
}
_SUB = {
    "0": "\u2080",
    "1": "\u2081",
    "2": "\u2082",
    "3": "\u2083",
    "4": "\u2084",
    "5": "\u2085",
    "6": "\u2086",
    "7": "\u2087",
    "8": "\u2088",
    "9": "\u2089",
    "+": "\u208a",
    "-": "\u208b",
    "=": "\u208c",
    "(": "\u208d",
    ")": "\u208e",
    "a": "\u2090",
    "e": "\u2091",
    "o": "\u2092",
    "x": "\u2093",
    "h": "\u2095",
    "k": "\u2096",
    "l": "\u2097",
    "m": "\u2098",
    "n": "\u2099",
    "p": "\u209a",
    "s": "\u209b",
    "t": "\u209c",
    "i": "\u1d62",
    "j": "\u2c7c",
    "r": "\u1d63",
    "u": "\u1d64",
    "v": "\u1d65",
}

_SYMBOLS: dict[str, str] = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "varpi": "ϖ",
    "rho": "ρ",
    "varrho": "ϱ",
    "sigma": "σ",
    "varsigma": "ς",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "varphi": "ϕ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "infty": "∞",
    "partial": "∂",
    "nabla": "∇",
    "emptyset": "∅",
    "cdot": "·",
    "times": "×",
    "div": "÷",
    "pm": "±",
    "mp": "∓",
    "leq": "≤",
    "le": "≤",
    "geq": "≥",
    "ge": "≥",
    "neq": "≠",
    "ne": "≠",
    "approx": "≈",
    "equiv": "≡",
    "sim": "∼",
    "propto": "∝",
    "in": "∈",
    "notin": "∉",
    "subset": "⊂",
    "subseteq": "⊆",
    "forall": "∀",
    "exists": "∃",
    "neg": "¬",
    "land": "∧",
    "lor": "∨",
    "to": "→",
    "rightarrow": "→",
    "leftarrow": "←",
    "Rightarrow": "⇒",
    "Leftarrow": "⇐",
    "mapsto": "↦",
    "circ": "∘",
    "bullet": "•",
    "ldots": "…",
    "cdots": "⋯",
    "dots": "…",
    "hbar": "ℏ",
    "ell": "ℓ",
    "degree": "°",
    "Re": "Re",
    "Im": "Im",
    "int": "∫",
    "iint": "∬",
    "iiint": "∭",
    "sum": "Σ",
    "prod": "Π",
    "quad": "  ",
    "qquad": "    ",
}

_FUNCTIONS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "log",
        "ln",
        "exp",
        "lim",
        "det",
        "min",
        "max",
        "arg",
        "arcsin",
        "arccos",
        "arctan",
        "sinh",
        "cosh",
        "tanh",
    }
)
_NOOP = frozenset(
    {
        "displaystyle",
        "textstyle",
        "scriptstyle",
        "limits",
        "nolimits",
        "mathstrut",
        "!",
    }
)
_TEXT_CMDS = frozenset(
    {"text", "textrm", "mbox", "mathrm", "operatorname", "mathbf", "mathit"}
)
_ACCENTS = {
    "hat": "\u0302",
    "bar": "\u0304",
    "overline": "\u0305",
    "vec": "\u20d7",
    "tilde": "\u0303",
    "dot": "\u0307",
    "ddot": "\u0308",
    "underline": "\u0332",
}
_SIMPLE = re.compile(
    "^[A-Za-z0-9"
    "\u03b1-\u03c9\u0391-\u03a9"
    "\u03c0\u221e\u2202\u2207\u2113\u210f"
    "\u00b9\u00b2\u00b3\u2070\u2074-\u2079\u207a-\u207f"
    "\u2080-\u208e\u2090-\u209c\u1d62-\u1d65\u2c7c"
    "]+$"
)
_TEX_CMDS = (
    frozenset(_SYMBOLS)
    | _FUNCTIONS
    | _TEXT_CMDS
    | frozenset(_ACCENTS)
    | _NOOP
    | frozenset(
        {
            "frac",
            "dfrac",
            "tfrac",
            "cfrac",
            "sqrt",
            "binom",
            "left",
            "right",
            "begin",
            "end",
            ",",
            ":",
            ";",
            "!",
            " ",
        }
    )
)
# A letter, digit, dot, or colon before \ is a path (C:\input, folder\log).
# Letters and drive punctuation, not digits — `2\right]` is TeX, not a path.
_PATH_BEFORE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.:")
_TEX_AFTER = frozenset("{[_^ \t\n,.;:!)]}") | {"("}


def tex_to_plain(src: str, *, unknown: str = "strip") -> str:
    """Convert a TeX math body (no delimiters) to unicode."""
    return _convert((src or "").strip(), unknown=unknown).strip()


def flatten_latex(text: str) -> str:
    """Turn TeX delimiters — and leftover named commands — into unicode."""
    if not text:
        return text
    parts: list[str] = []
    for kind, chunk in _split_protected(text):
        if kind == "code":
            parts.append(chunk)
        else:
            parts.append(_flatten_prose(chunk))
    return "".join(parts)


def flatten_for_render(text: str) -> tuple[str, list[str]]:
    """Flatten TeX and lift display spans into numbered tokens for styling."""
    if not text:
        return text, []
    slots: list[str] = []
    parts: list[str] = []

    def hold(match: re.Match[str]) -> str:
        slots.append(tex_to_plain(match.group(1)))
        return f"\n\n[[ARELIS_MATH_{len(slots) - 1}]]\n\n"

    for kind, chunk in _split_protected(text):
        if kind == "code":
            parts.append(chunk)
            continue
        chunk = _DISPLAY_DOLLARS.sub(hold, chunk)
        chunk = _DISPLAY_BRACKETS.sub(hold, chunk)
        parts.append(_flatten_prose(chunk))
    return "".join(parts), slots


def display_math_plain(chunk: str) -> str | None:
    """If a markdown chunk is only a display-math span, return the unicode."""
    text = (chunk or "").strip()
    if not text:
        return None
    for pattern in (_DISPLAY_DOLLARS, _DISPLAY_BRACKETS):
        match = pattern.fullmatch(text)
        if match and match.group(1).strip():
            return tex_to_plain(match.group(1))
    return None


def _split_protected(text: str) -> list[tuple[str, str]]:
    """Keep fenced and inline code away from the TeX pass."""
    out: list[tuple[str, str]] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    buf: list[str] = []

    def flush_text() -> None:
        if buf:
            out.append(("text", "\n".join(buf)))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line.strip()):
            flush_text()
            fence = [line]
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                fence.append(lines[i])
                i += 1
            if i < len(lines):
                fence.append(lines[i])
                i += 1
            out.append(("code", "\n".join(fence)))
            continue
        buf.append(line)
        i += 1
    flush_text()
    split: list[tuple[str, str]] = []
    for kind, chunk in out:
        if kind == "code":
            split.append((kind, chunk))
            continue
        split.extend(_split_inline_code(chunk))
    return split


def _split_inline_code(text: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        start = text.find("`", pos)
        if start < 0:
            if pos < len(text):
                parts.append(("text", text[pos:]))
            break
        if start > pos:
            parts.append(("text", text[pos:start]))
        end = text.find("`", start + 1)
        if end < 0 or "\n" in text[start + 1 : end]:
            parts.append(("text", text[start:]))
            break
        parts.append(("code", text[start : end + 1]))
        pos = end + 1
    return parts


def _flatten_prose(text: str) -> str:
    def as_display(match: re.Match[str]) -> str:
        return "\n" + tex_to_plain(match.group(1)) + "\n"

    text = _DISPLAY_DOLLARS.sub(as_display, text)
    text = _DISPLAY_BRACKETS.sub(as_display, text)
    text = _INLINE_PARENS.sub(lambda m: tex_to_plain(m.group(1)), text)

    def _dollar(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not re.search(r"[\\^_{]|[A-Za-z]", inner):
            return match.group(0)
        return tex_to_plain(inner)

    text = _INLINE_DOLLARS.sub(_dollar, text)
    if "\\" in text:
        text = _flatten_bare(text)
    return text


def _is_tex_site(src: str, i: int) -> bool:
    """True when ``\\cmd`` is TeX, not a Windows path fragment."""
    if i >= len(src) or src[i] != "\\":
        return False
    if i > 0 and src[i - 1] in _PATH_BEFORE:
        return False
    cmd, j = _read_cmd(src, i)
    if cmd not in _TEX_CMDS:
        return False
    if j >= len(src):
        return True
    if cmd in {",", ":", ";", "!", " "}:
        return True
    return src[j] in _TEX_AFTER


def _flatten_bare(text: str) -> str:
    """Convert leftover TeX commands without eating ``C:\\input`` or ``folder\\log``."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and _is_tex_site(text, i):
            piece, i = _command(text, i, unknown="keep")
            while i < n and text[i] in "^_":
                mark = text[i]
                grp, i = _read_group(text, i + 1)
                table = _SUP if mark == "^" else _SUB
                piece += _script(_convert(grp, unknown="keep"), table, mark)
            out.append(piece)
            continue
        if i + 1 < n and text[i + 1] == "^" and text[i].isalnum():
            grp, j = _read_group(text, i + 2)
            out.append(text[i])
            out.append(_script(_convert(grp, unknown="keep"), _SUP, "^"))
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _convert(src: str, *, unknown: str) -> str:
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "\\":
            piece, i = _command(src, i, unknown=unknown)
            out.append(piece)
            continue
        if ch == "^":
            grp, i = _read_group(src, i + 1)
            out.append(_script(_convert(grp, unknown=unknown), _SUP, "^"))
            continue
        if ch == "_":
            grp, i = _read_group(src, i + 1)
            out.append(_script(_convert(grp, unknown=unknown), _SUB, "_"))
            continue
        if ch == "{":
            grp, i = _read_group(src, i)
            out.append(_convert(grp, unknown=unknown))
            continue
        if ch == "}":
            i += 1
            continue
        if ch == "&":
            out.append("  ")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _command(src: str, i: int, *, unknown: str) -> tuple[str, int]:
    cmd, i = _read_cmd(src, i)
    if cmd in _NOOP:
        return "", i
    if cmd in {",", ":", ";"}:
        return " ", i
    if cmd in {" ", "quad", "qquad"}:
        return _SYMBOLS.get(cmd, " "), i
    if cmd == "\\":
        return "; ", i
    if cmd in {"{", "}", "%", "$", "#", "_", "&"}:
        return cmd, i
    if cmd in _TEXT_CMDS:
        grp, i = _read_group(src, i)
        if cmd in {"mathrm", "operatorname", "mathbf", "mathit"}:
            return _convert(grp, unknown=unknown), i
        return grp, i
    if cmd in {"frac", "dfrac", "tfrac", "cfrac"}:
        num, i = _read_group(src, i)
        den, i = _read_group(src, i)
        return (
            f"{_paren(_convert(num, unknown=unknown))}/"
            f"{_paren(_convert(den, unknown=unknown))}"
        ), i
    if cmd == "sqrt":
        root = ""
        j = _skip_space(src, i)
        if j < len(src) and src[j] == "[":
            root, i = _read_bracket(src, j)
            root = _script(_convert(root, unknown=unknown), _SUP, "^")
        else:
            i = j
        inner, i = _read_group(src, i)
        body = _convert(inner, unknown=unknown)
        return f"{root}√{_paren(body)}", i
    if cmd == "binom":
        n, i = _read_group(src, i)
        k, i = _read_group(src, i)
        return (
            f"C({_convert(n, unknown=unknown)}, {_convert(k, unknown=unknown)})"
        ), i
    if cmd in _ACCENTS:
        grp, i = _read_group(src, i)
        body = _convert(grp, unknown=unknown)
        if len(body) == 1:
            return body + _ACCENTS[cmd], i
        return f"{body}{_ACCENTS[cmd]}", i
    if cmd in {"left", "right"}:
        j = _skip_space(src, i)
        if j >= len(src):
            return "", i
        delim = src[j]
        if delim == ".":
            return "", j + 1
        if delim == "\\":
            inner, j = _read_cmd(src, j)
            mapped = _SYMBOLS.get(inner, inner if unknown == "strip" else "\\" + inner)
            return mapped, j
        return delim, j + 1
    if cmd == "begin":
        env, i = _read_group(src, i)
        body, i = _read_until_end(src, i, env)
        return _environment(env, body, unknown=unknown), i
    if cmd == "end":
        _grp, i = _read_group(src, i)
        return "", i
    if cmd in _FUNCTIONS:
        return cmd, i
    if cmd in _SYMBOLS:
        return _SYMBOLS[cmd], i
    if unknown == "keep":
        return "\\" + cmd, i
    return cmd, i


def _environment(env: str, body: str, *, unknown: str) -> str:
    name = (env or "").strip().rstrip("*")
    rows = [
        [_convert(cell.strip(), unknown=unknown) for cell in row.split("&")]
        for row in re.split(r"\\\\", body)
        if row.strip()
    ]
    if not rows:
        return _convert(body, unknown=unknown)
    if name == "cases":
        bits = []
        for row in rows:
            if len(row) >= 2:
                bits.append(f"{row[0]} ({row[1]})")
            else:
                bits.append(row[0])
        return "{ " + "; ".join(bits) + " }"
    joined = "; ".join("  ".join(cell for cell in row if cell) for row in rows)
    if name in {"bmatrix", "Bmatrix"}:
        return f"[{joined}]"
    if name == "pmatrix":
        return f"({joined})"
    if name == "vmatrix":
        return f"|{joined}|"
    if name in {"matrix", "aligned", "align", "eqnarray"}:
        return joined
    return joined


def _script(body: str, table: dict[str, str], mark: str) -> str:
    text = body.strip()
    if not text:
        return ""
    if all(ch in table or ch.isspace() for ch in text):
        return "".join(ch if ch.isspace() else table[ch] for ch in text)
    return f"{mark}({text})" if len(text) > 1 else f"{mark}{text}"


def _paren(body: str) -> str:
    text = body.strip()
    if not text:
        return text
    if _SIMPLE.fullmatch(text):
        return text
    if text[0] == "(" and text[-1] == ")" and _balanced(text[1:-1]):
        return text
    return f"({text})"


def _balanced(src: str) -> bool:
    depth = 0
    for ch in src:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _read_cmd(src: str, i: int) -> tuple[str, int]:
    i += 1
    if i >= len(src):
        return "\\", i
    ch = src[i]
    if ch.isalpha():
        j = i + 1
        while j < len(src) and src[j].isalpha():
            j += 1
        return src[i:j], j
    return ch, i + 1


def _skip_space(src: str, i: int) -> int:
    while i < len(src) and src[i].isspace():
        i += 1
    return i


def _read_group(src: str, i: int) -> tuple[str, int]:
    i = _skip_space(src, i)
    if i >= len(src):
        return "", i
    if src[i] == "{":
        depth = 1
        i += 1
        start = i
        while i < len(src) and depth:
            if src[i] == "\\":
                i += 2
                continue
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        return src[start : i - 1] if depth == 0 else src[start:], i
    if src[i] == "\\":
        cmd, j = _read_cmd(src, i)
        return "\\" + cmd, j
    return src[i], i + 1


def _read_bracket(src: str, i: int) -> tuple[str, int]:
    i += 1
    start = i
    depth = 1
    while i < len(src) and depth:
        if src[i] == "[":
            depth += 1
        elif src[i] == "]":
            depth -= 1
        i += 1
    return src[start : i - 1] if depth == 0 else src[start:], i


def _read_until_end(src: str, i: int, env: str) -> tuple[str, int]:
    needle = r"\end{" + env + "}"
    at = src.find(needle, i)
    if at < 0:
        return src[i:], len(src)
    return src[i:at], at + len(needle)
