"""Deterministic arithmetic, so the model does not invent numbers.

Arithmetic runs on `Fraction`, not `float`. The docstring above has always said
"exactly", and on binary floats it was not: `0.1 + 0.2` came back as
`0.30000000000000004`, `100 * 1.1` as `110.00000000000001`, and
`0.1 + 0.2 - 0.3` as `5.55e-17` rather than zero. Those are the answers this
tool exists to stop the model producing, and it was producing them itself. A
decimal literal is read as the decimal that was written, `Fraction(str(0.1))`
is one tenth, so the sums come out right and money stops growing a tail.

Floats are still used the moment a real function is involved: `sqrt`, `sin` and
`log` have no rational answer and pretending otherwise would be a different
lie. What is refused outright is `inf` and `nan`, which used to be returned as
successful results.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from datetime import date
from fractions import Fraction
from typing import Any

from arelis.tools.base import ToolResult

# Binary / unary ops only. No attribute access, no calls except safe math names.
_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: _divide(a, b),
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# send_sms argument names. Nothing here is ever part of an expression.
_SEND_KEYS = frozenset({"to", "body", "recipient", "phone", "message", "sms"})

_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "ln": math.log,
    "factorial": math.factorial,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
    "e": math.e,
    "radians": math.radians,
    "degrees": math.degrees,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "hypot": math.hypot,
}


class CalculatorTool:
    name = "calculator"
    description = (
        "Evaluate a math expression exactly, decimals are exact, so money "
        "does not grow a floating-point tail. Use for arithmetic, percentages, "
        "units of count, and simple science functions (sqrt, sin, log, …). "
        "Understands '15% of 84', '30% off 59.99', '$4.50 + $2', '1,250 + 300'. "
        "Pass a plain expression like '2*(3+4)' or 'sqrt(2)*pi'. No import, no "
        "assignments. Unit conversion is the units tool, not this one. "
        "For a Python script (projectile motion, named variables) "
        "use the python tool. This is not a CAS, it cannot integrate or solve "
        "symbolically. Do not guess numeric answers when this tool can compute them."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression to evaluate.",
            },
        },
        "required": ["expression"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        expression = str(kwargs.get("expression") or "").strip()
        if not expression:
            # A leftover SMS draft arriving as calculator(to=…, body=…) is not a
            # missing argument, it is the wrong tool. Saying so is the difference
            # between the model correcting itself and retrying the same call.
            stray = sorted(k for k in kwargs if k.lower() in _SEND_KEYS)
            if stray:
                return ToolResult(
                    ok=False,
                    output=(
                        f"Wrong tool: {', '.join(stray)} are send_sms arguments. "
                        "calculator only evaluates an arithmetic `expression`. "
                        "Call send_sms to text someone."
                    ),
                )
            return ToolResult(ok=False, output="Missing expression.")
        try:
            value = evaluate_expression(expression)
        except ZeroDivisionError:
            return ToolResult(ok=False, output="Division by zero.")
        except Exception as exc:
            hint = _script_hint(expression)
            return ToolResult(ok=False, output=f"Could not evaluate: {exc}{hint}")
        shown, exact = present(value)
        note = f" (exactly {exact})" if exact else ""
        # Echo what was evaluated, not what was typed, when normalisation
        # changed it. "3 + 4 = = 7" reads like a bug; showing the rewrite also
        # lets the reader check that "30% off 59.99" was understood the way
        # they meant it.
        echo = normalize_expression(expression)
        if echo.strip() == expression.strip():
            echo = expression
        return ToolResult(
            ok=True,
            output=f"{echo} = {shown}{note}",
            data={"expression": expression, "value": shown},
        )


def present(value: Any) -> tuple[Any, str]:
    """Turn the internal number into what the model should read.

    Returns the value to show and, for a repeating fraction, the exact form
    alongside it. `1/3 = 0.3333333333333333 (exactly 1/3)` stops the model
    treating the decimal as the whole truth and rounding it into a wrong
    third place, which is the arithmetic mistake it makes most often.
    """
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return int(value), ""
        # A denominator made only of 2s and 5s terminates in base ten, so it
        # can be written out in full with nothing lost.
        residue = value.denominator
        for factor in (2, 5):
            while residue % factor == 0:
                residue //= factor
        if residue == 1:
            from decimal import Decimal

            exact = Decimal(value.numerator) / Decimal(value.denominator)
            return float(exact), ""
        return float(value), f"{value.numerator}/{value.denominator}"
    if isinstance(value, float) and value.is_integer():
        # Only where a float really is that integer. `hypot(1e308, 1e308)`
        # satisfies is_integer(), and int() on it spells out 309 digits —
        # every one after the seventeenth invented by the binary
        # representation. Printing them claims a precision the number does not
        # have, which is the same failure as returning nan with ok=True.
        if abs(value) < 2**53:
            return int(value), ""
        return value, ""
    return value, ""


_BANG_FACT = re.compile(r"(?<![\w.])(\d+)\s*!")


# The shapes people and models actually type. Each one used to come back as
# "invalid expression (invalid syntax)", which tells the model nothing it can
# act on, so it either retried the same call or answered from its own head.
_LEAD_WORDS = re.compile(
    r"(?i)^\s*(?:what\s+is|what\s+was|whats|what's|how\s+much\s+is|"
    r"how\s+much\s+does|calculate|compute|eval)\b[:\s]*"
)
_TRAILING_EQ = re.compile(r"\s*=\s*\??\s*$")
_TRAILING_Q = re.compile(r"\?+\s*$")
_TRAILING_FILLER = re.compile(
    r"(?i)\s+(?:please|thanks|thank\s+you|for\s+the\s+tip|for\s+me|"
    r"real\s+quick|quickly|back\s+then|now\s+and\s+then)\s*$"
)
# Calendar-shaped M/D and M/D/Y are dates or events, not division, unless the
# ask carries an explicit math cue ("as a fraction", "times", "% of", …).
_CALENDAR_SLASH = re.compile(
    r"(?i)^\s*"
    r"(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])"
    r"(/(?:[1-9]\d{1,3}|0\d{2,3}))?"
    r"\s*$"
)
_MATH_INTENT = re.compile(
    r"(?i)(?:%|\*|\^|\bof\b|\btimes\b|\bplus\b|\bminus\b|"
    r"\bsqrt\b|\bas\s+a\s+(?:decimal|fraction|percent)\b|"
    r"[+\-](?=\s*\d))"
)
_AS_FORM = re.compile(r"(?i)\s+as\s+a\s+(?:decimal|fraction|percent)\s*$")
_CURRENCY = re.compile(r"[$£€¥]")
_PERCENT_OFF = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*%\s*off\s+(\S+)")
_PERCENT_OF = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*%\s*of\s+")
_TIMES_X = re.compile(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])")
_SPOKEN_TIMES = re.compile(r"(?i)(?<=[\d)])\s*(?:times|multiplied\s+by)\s*(?=[\d(])")
_SPOKEN_PLUS = re.compile(r"(?i)(?<=[\d)])\s*plus\s*(?=[\d(])")
_SPOKEN_MINUS = re.compile(r"(?i)(?<=[\d)])\s*minus\s*(?=[\d(])")
_SPOKEN_DIV = re.compile(r"(?i)(?<=[\d)])\s*(?:divided\s+by|over)\s*(?=[\d(])")
_SPOKEN_SQUARED = re.compile(r"(?i)(?<=[\d)])\s*squared\b")
_SPOKEN_CUBED = re.compile(r"(?i)(?<=[\d)])\s*cubed\b")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

# Spoken year length / years↔days. Anonymous "a planet at N AU" uses
# Kepler III in AU and Julian years: P^2 = a^3, so P_yr = sqrt(a^3),
# and days are that times 365.25. Named bodies use NASA sidereal
# orbital periods (Earth days) from
# https://nssdc.gsfc.nasa.gov/planetary/factsheet/ instead of mean-a
# Kepler, which is tens of days off for the outer planets.
_JULIAN_YEAR_DAYS = "365.25"
_EARTH_SIDEREAL_DAYS = "365.256"
_PLANET_SIDEREAL_DAYS: dict[str, str] = {
    "mercury": "87.969",
    "venus": "224.701",
    "mars": "686.980",
    "jupiter": "4332.589",
    "saturn": "10759.22",
    "uranus": "30685.4",
    "neptune": "60189",
    "pluto": "90560",
}
_PLANET_NAME = re.compile(
    r"(?i)\b(mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto)\b"
)
_AU_AMOUNT = re.compile(
    r"(?i)(\d+(?:\.\d+)?)\s*(?:au|astronomical\s+units?)\b"
)
_WANTS_DAYS = re.compile(r"(?i)\b(?:earth\s+)?days?\b")
_YEARS_IN_DAYS = re.compile(
    r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*years?\s*(?:in|to|into|as)\s+"
    r"(?:earth\s+)?days?\b"
)
_HOW_MANY_DAYS_IS_YEARS = re.compile(
    r"(?i)\b(?:how\s+many|how\s+long)\b.{0,48}\b(?:earth\s+)?days?\b"
    r".{0,24}\b(?:is|in|are)\b.{0,24}(?<![\d.])(\d+(?:\.\d+)?)\s*years?\b"
)
_MATH_FUNC_NAMES = (
    r"sqrt|sin|cos|tan|log|log10|ln|exp|abs|floor|ceil|factorial|"
    r"min|max|round|pi|e|radians|degrees|asin|acos|atan|atan2|hypot"
)
_MATH_FUNCS = re.compile(rf"(?i)\b(?:{_MATH_FUNC_NAMES})\b")
_RAW_MATH_REST = re.compile(r"^[\d\s+\-*/^().,]+$")
_AGE_IN_PLANET = re.compile(
    r"(?i)\b(?:how\s+old|age|old\s+am\s+i)\b.{0,80}\b(?:mars|jupiter|mercury|"
    r"venus|saturn|uranus|neptune|pluto)\s+years?\b"
)
_MONTH_NAME = (
    r"january|february|march|april|may|june|july|august|september|"
    r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|"
    r"oct|nov|dec"
)
_DATE_MDY = re.compile(
    rf"(?i)\b({_MONTH_NAME})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b"
)
_DATE_DMY = re.compile(
    rf"(?i)\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAME})\s+(\d{{4}})\b"
)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_INDEX = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}


def _is_raw_math_expression(text: str) -> bool:
    """True when the model already passed arithmetic, not user prose."""
    sample = (text or "").strip()
    if not sample:
        return False
    stripped = _MATH_FUNCS.sub("", sample)
    return bool(_RAW_MATH_REST.fullmatch(stripped))


def rewrite_spoken_duration(text: str) -> str | None:
    """Turn a spoken year/day/orbit ask into one arithmetic expression.

    Returns None when the line is not that shape, so the ordinary
    normaliser still runs. Raw expressions the model wrote itself
    (``11.86*365.25``, ``sqrt(5.2**3)``) are left alone.
    """
    raw = text or ""
    if not raw.strip() or _is_raw_math_expression(raw):
        return None
    age = _rewrite_planet_age(raw)
    if age is not None:
        return age
    au = _AU_AMOUNT.search(raw)
    planet = _PLANET_NAME.search(raw)
    wants_days = bool(_WANTS_DAYS.search(raw))
    if au is not None and re.search(r"(?i)\b(?:year|orbit)\b", raw):
        a = au.group(1)
        period = f"sqrt({a}**3)"
        return f"{period}*{_JULIAN_YEAR_DAYS}" if wants_days else period
    if planet is not None and re.search(r"(?i)\b(?:year|orbit)\b", raw):
        period_days = _PLANET_SIDEREAL_DAYS[planet.group(1).lower()]
        if wants_days:
            return period_days
        return f"({period_days})/{_EARTH_SIDEREAL_DAYS}"
    years_in = _YEARS_IN_DAYS.search(raw)
    if years_in is not None:
        return f"{years_in.group(1)}*{_JULIAN_YEAR_DAYS}"
    how_many = _HOW_MANY_DAYS_IS_YEARS.search(raw)
    if how_many is not None:
        return f"{how_many.group(1)}*{_JULIAN_YEAR_DAYS}"
    return None


def _rewrite_planet_age(text: str) -> str | None:
    if not _AGE_IN_PLANET.search(text) and not re.search(
        r"(?i)\bborn\b.{0,80}\b(?:mercury|venus|mars|jupiter|saturn|"
        r"uranus|neptune|pluto)\s+years?\b",
        text,
    ):
        return None
    planet = _PLANET_NAME.search(text)
    born = _parse_birthdate(text)
    if planet is None or born is None:
        return None
    days = (date.today() - born).days
    period_days = _PLANET_SIDEREAL_DAYS[planet.group(1).lower()]
    return f"{days}/{period_days}"


def _parse_birthdate(text: str) -> date | None:
    hit = _DATE_MDY.search(text or "")
    if hit:
        month = _MONTH_INDEX[hit.group(1).lower()]
        try:
            return date(int(hit.group(3)), month, int(hit.group(2)))
        except ValueError:
            return None
    hit = _DATE_DMY.search(text or "")
    if hit:
        month = _MONTH_INDEX[hit.group(2).lower()]
        try:
            return date(int(hit.group(3)), month, int(hit.group(1)))
        except ValueError:
            return None
    hit = _DATE_ISO.search(text or "")
    if hit:
        try:
            return date(int(hit.group(1)), int(hit.group(2)), int(hit.group(3)))
        except ValueError:
            return None
    return None


# "5 miles in km" is a real question with a real tool behind it.
_UNIT_ASK = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s*[a-z°]+\s*(?:in|to|into|as)\s+[a-z°]",
)


def _calendar_slash_without_math(text: str) -> bool:
    """True when the line is only a calendar slash and has no math cue."""
    raw = text or ""
    if _MATH_INTENT.search(raw):
        return False
    stripped = _LEAD_WORDS.sub("", raw)
    stripped = _TRAILING_Q.sub("", stripped)
    stripped = _TRAILING_FILLER.sub("", stripped)
    stripped = _TRAILING_EQ.sub("", stripped)
    stripped = _AS_FORM.sub("", stripped)
    return bool(_CALENDAR_SLASH.fullmatch(stripped.strip()))


def normalize_expression(text: str) -> str:
    """Rewrite the common surface forms into something ast can parse.

    None of this changes what the arithmetic means. `15% of 84` has exactly one
    reading, and refusing it bought nothing except a wasted round trip.
    Spoken operators ("times", "plus", "divided by") and tip/please filler
    are stripped here so the first calculator call does not fail on ordinary
    talk.
    """
    spoken = rewrite_spoken_duration(text)
    if spoken is not None:
        return spoken
    source = _LEAD_WORDS.sub("", text or "")
    # Drop "?" before filler so "for the tip?" still matches.
    source = _TRAILING_Q.sub("", source)
    source = _TRAILING_FILLER.sub("", source)
    source = _AS_FORM.sub("", source)
    source = _TRAILING_EQ.sub("", source)
    source = _CURRENCY.sub("", source)
    if "(" not in source:
        # Only outside a call. `max(1,250)` is two arguments and stripping the
        # comma there would silently change the answer, which is far worse than
        # failing to read a thousands separator.
        source = _THOUSANDS.sub("", source)
    source = _PERCENT_OFF.sub(r"(\2) * (1 - \1/100)", source)
    source = _PERCENT_OF.sub(r"(\1/100) * ", source)
    source = _TIMES_X.sub("*", source)
    source = _SPOKEN_TIMES.sub("*", source)
    source = _SPOKEN_PLUS.sub("+", source)
    source = _SPOKEN_MINUS.sub("-", source)
    source = _SPOKEN_DIV.sub("/", source)
    source = _SPOKEN_SQUARED.sub("**2", source)
    source = _SPOKEN_CUBED.sub("**3", source)
    # People write 17^2. Python wants **. This tool has no bitwise XOR.
    source = source.replace("^", "**")
    return _BANG_FACT.sub(r"factorial(\1)", source)


def expression_is_evaluable(text: str) -> bool:
    """True when normalize + whitelist eval would succeed for this line."""
    try:
        evaluate_expression(text)
    # Silence is the answer here: any failure just means the line is not
    # math we can arm up front, so the model writes the call itself.
    except Exception:
        return False
    return True


def evaluate_expression(expression: str) -> float | int:
    """Eval a whitelist AST. Raises ValueError on anything unsafe."""
    if _calendar_slash_without_math(expression):
        raise ValueError(
            "that looks like a calendar date or event, not a division. "
            "Ask about the date, or write the arithmetic with a clear math cue "
            "such as 'as a fraction' or 'as a decimal'."
        )
    source = normalize_expression(expression)
    # Spoken "divided by" rewrites to a slash. Bare calendar M/D stays refused
    # unless the raw line had a strong math cue (as a fraction, %, of, …).
    if _CALENDAR_SLASH.fullmatch((source or "").strip()) and not _MATH_INTENT.search(
        expression or ""
    ):
        raise ValueError(
            "that looks like a calendar date or event, not a division. "
            "Ask about the date, or write the arithmetic with a clear math cue "
            "such as 'as a fraction' or 'as a decimal'."
        )
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression ({exc.msg})") from exc
    value = _eval_node(tree.body)
    if isinstance(value, (int, Fraction)):
        # Exact arithmetic has no overflow, which is a new problem rather than
        # a solved one: `1e308 * 10` used to be `inf` and is now a genuinely
        # correct 309-digit integer. Correct, and useless — it is three hundred
        # tokens of prompt that no one can read. Bounded here rather than in
        # `present`, so the refusal says why instead of silently truncating.
        digits = len(str(abs(int(value)))) if _is_whole_number(value) else 0
        if digits > _MAX_DIGITS or _denominator(value) > 10**_MAX_DIGITS:
            raise ValueError(
                f"the exact result has about {max(digits, _MAX_DIGITS)} digits, "
                "which is too long to be a useful answer. Use the python tool "
                "if you need it, and do not round it from memory."
            )
    if isinstance(value, float) and not math.isfinite(value):
        # This used to be returned with ok=True. `2e400 - 2e400 = nan` is not a
        # computed answer, and handing it to a model that was called precisely
        # so it would not invent a number is the worst possible result.
        raise ValueError(
            "the result overflowed to "
            + ("infinity" if math.isinf(value) else "an undefined value")
            + "- the numbers are too large for exact arithmetic. "
            "Say the result is out of range; do not report a number."
        )
    return value


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numbers are allowed")
        if isinstance(node.value, int):
            return node.value
        if not math.isfinite(node.value):
            # `1e400` parses to inf before a single operator has run. The same
            # "do not report a number" wording as the overflow check below, on
            # purpose: both end with the model holding no answer, and that is
            # exactly when it reaches for one of its own.
            raise ValueError(
                "that number is too large to represent. Say it is out of "
                "range; do not report a number."
            )
        # str() first, deliberately. Fraction(0.1) is the exact binary value,
        # 3602879701896397/36028797018963968, which is the problem rather than
        # the fix. Python's float repr round-trips to the shortest decimal that
        # reads back the same, so str() recovers the literal as written.
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(float(left)) > 1e6 or abs(float(right)) > 1000:
                raise ValueError("exponent too large")
            return _power(left, right)
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCS and not callable(_SAFE_FUNCS[node.id]):
            return _SAFE_FUNCS[node.id]
        raise ValueError(f"unknown name {node.id!r}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple function calls are allowed")
        fn = _SAFE_FUNCS.get(node.func.id)
        if not callable(fn):
            raise ValueError(f"unknown function {node.func.id!r}")
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        args = [_eval_node(a) for a in node.args]
        if node.func.id == "factorial":
            # math.factorial refuses a Fraction even when it is a whole number.
            args = [int(a) if _is_whole(a) else a for a in args]
        return fn(*args)
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def _divide(left: Any, right: Any) -> Any:
    """`1/3` stays a third rather than becoming 0.3333333333333333.

    Integer literals are kept as `int` so that `factorial`, indices and the
    exponent rule keep working, which means plain `int / int` would fall
    through to Python's float division. Division is where precision is lost, so
    it is the one operator worth converting for.
    """
    if isinstance(left, (int, Fraction)) and isinstance(right, (int, Fraction)):
        if right == 0:
            raise ZeroDivisionError("division by zero")
        return Fraction(left) / Fraction(right)
    return operator.truediv(left, right)


# Generous — factorial(170) is 307 digits and is a real answer someone wants —
# but bounded, so an exact result cannot become a page of prompt.
_MAX_DIGITS = 500


def _is_whole(value: Any) -> bool:
    return isinstance(value, Fraction) and value.denominator == 1


def _is_whole_number(value: Any) -> bool:
    return isinstance(value, int) or _is_whole(value)


def _denominator(value: Any) -> int:
    return value.denominator if isinstance(value, Fraction) else 1


def _power(left: Any, right: Any) -> Any:
    """Keep an exact base exact when the exponent is a whole number.

    `Fraction ** Fraction` falls back to float even for `(1/2) ** 2`, so the
    integer case is pulled out by hand. It is the common one: `1.1 ** 2` is a
    compound-interest question, and `1.2100000000000002` is the wrong shape of
    answer for it.
    """
    if isinstance(left, Fraction) and _is_whole(right):
        return left ** int(right)
    if isinstance(left, Fraction) and isinstance(right, int):
        return left**right
    return operator.pow(left, right)


def _script_hint(expression: str) -> str:
    """Name the tool that can do it, rather than only refusing.

    The same move `analyze` makes for a PDF. A bare "invalid syntax" leaves the
    model with no next step but to answer from memory, which is the one
    outcome this tool exists to prevent.
    """
    if _UNIT_ASK.search(expression):
        return (
            " That is a unit conversion, not arithmetic. "
            "Call units(action=convert, expression=…) instead."
        )
    if re.search(r"(?i)\b(solve|integrate|derivative|differentiate|simplify)\b", expression):
        return " That is symbolic maths. Call cas with the matching action."
    if re.search(r"(?i)\bchoose\b|\bnCr\b|\bpermutations?\b", expression):
        return " For combinations write it out: factorial(n) / (factorial(k) * factorial(n-k))."
    # The script check comes before the '=' rule below, because an assignment
    # is the most common reason a script contains one and "call cas
    # action=solve" is useless advice for `v = 3; print(v*2)`.
    try:
        ast.parse(expression, mode="eval")
        return ""
    except SyntaxError:
        pass
    try:
        ast.parse(expression, mode="exec")
    except SyntaxError:
        pass
    else:
        return (
            " This looks like a Python script, not one expression. "
            "Call the python tool with that code."
        )
    if "=" in expression and not expression.rstrip().endswith("="):
        return (
            " There is an '=' in the middle. This tool evaluates one "
            "expression; it does not solve equations. Call cas action=solve."
        )
    return ""
