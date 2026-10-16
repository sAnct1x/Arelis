"""Child entry for run_script. The user's script stays the program.

This process must not import arelis. The parent starts this file so a
raised exception is a status line plus the exception type. The traceback
still goes to stderr. A clean exit does not print the status line, so
stdout stays the script's own prints.
"""

from __future__ import annotations

import json
import os
import runpy
import sys
import traceback

_PREFIX = "ARELIS_RUN_STATUS "


def _emit(exc: BaseException) -> None:
    payload = {"status": "bad_args", "error_type": type(exc).__name__}
    sys.stderr.write(_PREFIX + json.dumps(payload) + "\n")
    sys.stderr.flush()


def _script_traceback(exc: BaseException) -> None:
    """Print the script's frames. The host and runpy frames are not the error."""
    tb = exc.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if filename == __file__ or filename.startswith("<frozen"):
            tb = tb.tb_next
            continue
        break
    traceback.print_exception(type(exc), exc, tb)


def main() -> None:
    if len(sys.argv) < 2:
        exc = SystemExit(2)
        _emit(exc)
        raise exc
    script = sys.argv[1]
    sys.argv = sys.argv[1:]
    # A direct `python script.py` puts that file's directory on sys.path.
    # runpy does not, so a sibling import would miss. The approved copy
    # sits beside the original, and that import has to keep working.
    script_dir = os.path.dirname(os.path.abspath(script))
    if sys.path:
        sys.path[0] = script_dir
    else:
        sys.path.append(script_dir)
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            raise
        if not isinstance(code, int):
            sys.stderr.write(str(code) + "\n")
            sys.stderr.flush()
        _emit(exc)
        raise SystemExit(code if isinstance(code, int) else 1) from None
    except BaseException as exc:
        _script_traceback(exc)
        _emit(exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
