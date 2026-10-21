"""Turn string arguments into the types a tool's JSON schema declares.

the model server's qwen3.5 parser types a tool call only when that name is in the
request tools array. A tool loaded later is missing from the array, so
every argument comes back as a string, including numbers, bools, and
JSON arrays or objects. The same conversion runs for every call. A value that is
already an int, float, bool, list, or object is not rebuilt. A string
that does not parse is left as it arrived so the tool can say why.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

_INT = re.compile(r"[+-]?\d+")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
# Tool arguments are a few levels deep. Past this, json.loads either
# raises RecursionError or, on a large stack, returns a value whose next
# walk crashes the turn. The text stays as it arrived.
_MAX_JSON_DEPTH = 32


def coerce_arguments(
    schema: dict[str, Any] | None, args: dict[str, Any]
) -> dict[str, Any]:
    """Return args with string values converted where the schema asks.

    The same dict comes back when nothing changed, and unchanged values
    stay the same objects.
    """
    if not isinstance(schema, dict) or not isinstance(args, dict):
        return args
    props = schema.get("properties")
    if not isinstance(props, dict):
        return args
    updated = args
    for key, value in args.items():
        spec = props.get(key)
        if not isinstance(spec, dict):
            continue
        coerced = coerce_value(spec, value)
        if coerced is not value:
            if updated is args:
                updated = dict(args)
            updated[key] = coerced
    return updated


def coerce_value(spec: dict[str, Any], value: Any) -> Any:
    """Convert one value. Already-typed values come back unchanged."""
    if not isinstance(spec, dict):
        return value
    typ = spec.get("type")
    kind = typ.strip().lower() if isinstance(typ, str) else ""

    if kind == "array" and isinstance(value, list):
        return _accept(spec, _coerce_list(spec, value), value)
    if kind == "object" and isinstance(value, dict):
        return _accept(spec, _coerce_object(spec, value), value)
    if not isinstance(value, str):
        return value

    converted = _from_string(kind, value, spec)
    return _accept(spec, converted, value)


def _accept(spec: dict[str, Any], converted: Any, original: Any) -> Any:
    enum = spec.get("enum")
    if isinstance(enum, list) and converted not in enum:
        return original
    return converted


def _from_string(kind: str, value: str, spec: dict[str, Any]) -> Any:
    if kind == "integer":
        parsed = _parse_int(value)
        return value if parsed is None else parsed
    if kind == "number":
        parsed_num = _parse_number(value)
        return value if parsed_num is None else parsed_num
    if kind == "boolean":
        token = value.strip().lower()
        if token == "true":
            return True
        if token == "false":
            return False
        return value
    if kind == "array":
        parsed_list = _parse_json(value, list)
        if parsed_list is None:
            return value
        return _coerce_list(spec, parsed_list)
    if kind == "object":
        parsed_obj = _parse_json(value, dict)
        if parsed_obj is None:
            return value
        return _coerce_object(spec, parsed_obj)
    if not kind:
        enum = spec.get("enum")
        if isinstance(enum, list):
            matched = _match_enum(enum, value)
            if matched is not None:
                return matched
    return value


def _coerce_list(spec: dict[str, Any], value: list[Any]) -> list[Any]:
    items = spec.get("items")
    if not isinstance(items, dict):
        return value
    changed = False
    out: list[Any] = []
    for item in value:
        coerced = coerce_value(items, item)
        if coerced is not item:
            changed = True
        out.append(coerced)
    return out if changed else value


def _coerce_object(spec: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    props = spec.get("properties")
    if not isinstance(props, dict):
        return value
    updated = value
    for key, item in value.items():
        sub = props.get(key)
        if not isinstance(sub, dict):
            continue
        coerced = coerce_value(sub, item)
        if coerced is not item:
            if updated is value:
                updated = dict(value)
            updated[key] = coerced
    return updated


def _parse_int(text: str) -> int | None:
    token = text.strip()
    if _INT.fullmatch(token) is None:
        return None
    try:
        return int(token)
    except ValueError:
        return None


def _parse_number(text: str) -> int | float | None:
    token = text.strip()
    if _INT.fullmatch(token) is not None:
        return _parse_int(token)
    if _NUMBER.fullmatch(token) is None:
        return None
    try:
        parsed = float(token)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _nesting_deeper_than(text: str, limit: int = _MAX_JSON_DEPTH) -> bool:
    """True when brackets nest past limit. Brackets inside strings do not count."""
    depth = 0
    in_string = False
    escape = False
    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch in "[{":
            depth += 1
            if depth > limit:
                return True
            continue
        if ch in "]}":
            if depth:
                depth -= 1
    return False


def _parse_json(text: str, kind: type[Any]) -> Any | None:
    token = text.strip()
    if kind is list and not token.startswith("["):
        return None
    if kind is dict and not token.startswith("{"):
        return None
    if _nesting_deeper_than(token):
        return None
    try:
        parsed = json.loads(token)
    except (ValueError, RecursionError):
        # JSONDecodeError is a ValueError. Deep nesting raises
        # RecursionError instead, and that must not escape a tool call.
        return None
    if not isinstance(parsed, kind):
        return None
    return parsed


def _match_enum(enum: list[Any], text: str) -> Any | None:
    """Match a string to an enum member when the property has no type."""
    if text in enum:
        return text
    as_int = _parse_int(text)
    if as_int is not None and as_int in enum:
        return as_int
    token = text.strip().lower()
    if token == "true" and any(item is True for item in enum):
        return True
    if token == "false" and any(item is False for item in enum):
        return False
    as_num = _parse_number(text)
    if isinstance(as_num, float) and as_num in enum:
        return as_num
    return None
