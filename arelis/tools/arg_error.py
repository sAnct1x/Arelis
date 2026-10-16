"""One shape for a tool call that failed with a real exception.

The loop counts ``status`` together with ``exc_message`` (the exception
text). ``error_type`` stays on the payload so a caller can still see the
class. The output is the traceback (or the tool's existing sentence when
the caller passes one).
"""

from __future__ import annotations

import traceback
from typing import Any

from arelis.tools.base import ToolResult


def bad_args_data(
    exc: BaseException | None = None,
    *,
    error_type: str | None = None,
    fail_class: str = "fail:args",
) -> dict[str, Any]:
    """status=bad_args plus the exception class, when that class is a real name."""
    name = error_type if isinstance(error_type, str) else ""
    if not name and exc is not None:
        name = type(exc).__name__
    data: dict[str, Any] = {"status": "bad_args", "fail_class": fail_class}
    if isinstance(name, str) and name.isidentifier() and len(name) <= 64:
        data["error_type"] = name
    return data


def arg_error(
    exc: BaseException | None = None,
    *,
    output: str | None = None,
    error_type: str | None = None,
    fail_class: str = "fail:args",
    extra: dict[str, Any] | None = None,
) -> ToolResult:
    """Tool result the bad-args counter can see.

    Default output is the traceback. A caller that already has the tool's
    own sentence passes it as ``output``.
    """
    if output is None:
        if exc is None:
            output = ""
        else:
            output = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).rstrip() or str(exc)
    data = bad_args_data(exc, error_type=error_type, fail_class=fail_class)
    if extra:
        for key, value in extra.items():
            if key not in {"status", "error_type"}:
                data[key] = value
    if exc is not None and "exc_message" not in data:
        short = str(exc).strip()
        if short:
            data["exc_message"] = short
    return ToolResult(ok=False, output=output, data=data)
