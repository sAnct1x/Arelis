"""python_exec had no tests at all, and three real sandbox escapes.

Found 2026-09-17 by listing tools that no test file so much as names. Three
came back: `html_text`, `image_io`, and this one — a tool whose whole job is
**executing code the model wrote**. It shipped with an AST whitelist, an import
allowlist, a forbidden-call list, a locked `__builtins__`, and zero tests to
say whether any of it held.

It did not. Probing it found three escapes, in descending order of severity:

1. **`sympy.sympify` is `eval`.** `sp.sympify("__import__('os').name")`
   returned `nt`. That is arbitrary import and attribute access, which is one
   short step from `.system(...)`. The AST gate never saw it because the
   payload is a *string constant*, and the gate inspects `Attribute` and
   `Name` nodes. Exactly the vulnerability proven by mutation in `plot.py`
   the same day — except there it was hypothetical and here it was live.

2. **`operator.attrgetter("__class__")` walks straight past the dunder rule**,
   for the same reason: a dunder spelled inside a string is a `Constant`.
   `attrgetter` is reachable because `operator` is preloaded in the namespace.

3. **`numpy.savetxt` writes files.** The module docstring says "os,
   subprocess, sockets, and files stay out". The probe wrote a real file to
   the repo root.

The fixes are two general rules rather than a longer denylist of modules:
string literals may not contain `__`, and a small set of attribute names that
mean "evaluate this text" or "touch the disk" may not be called. Both are
checked on the AST, before anything runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.tools.python_exec import PythonTool


async def _run(code: str) -> tuple[bool, str]:
    result = await PythonTool().run(code=code)
    return bool(result.ok), str(result.output)


# --------------------------------------------------------------------------
# It has to actually work, or the hardening below is just breaking a tool
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_kinematics_cell_runs() -> None:
    ok, out = await _run(
        "g = 9.81\nv = 20.0\nth = radians(45)\n"
        "rng = v*v*sin(2*th)/g\nprint(round(rng, 2))"
    )
    assert ok, out
    assert "40.77" in out


@pytest.mark.asyncio
async def test_the_last_expression_is_shown() -> None:
    ok, out = await _run("a = 6\nb = 7\na * b")
    assert ok, out
    assert "42" in out


@pytest.mark.asyncio
async def test_sympy_still_does_symbolic_work() -> None:
    """The hardening must not cost the reason the tool exists."""
    ok, out = await _run(
        "import sympy as sp\nx = sp.Symbol('x')\nprint(sp.diff(x**3, x))"
    )
    assert ok, out
    assert "3*x**2" in out


@pytest.mark.asyncio
async def test_sympy_solve_and_integrate_survive() -> None:
    ok, out = await _run(
        "import sympy as sp\n"
        "x = sp.Symbol('x')\n"
        "print(sp.solve(x**2 - 4, x))\n"
        "print(sp.integrate(2*x, x))"
    )
    assert ok, out
    assert "-2" in out and "x**2" in out


@pytest.mark.asyncio
async def test_numpy_arithmetic_survives() -> None:
    ok, out = await _run(
        "import numpy as np\nprint(np.array([1.0, 2.0, 3.0]).mean())"
    )
    assert ok, out
    assert "2.0" in out


@pytest.mark.asyncio
async def test_a_regex_can_still_be_compiled() -> None:
    """re.compile is a normal thing to do and shares a name with the builtin."""
    ok, out = await _run("import re\nprint(bool(re.compile(r'\\d+').search('a1')))")
    assert ok, out
    assert "True" in out


# --------------------------------------------------------------------------
# Escape 1: sympify is eval
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sympify_cannot_be_used_as_an_eval_gadget() -> None:
    ok, out = await _run("import sympy as s\nprint(s.sympify(\"1+1\"))")
    assert not ok, f"sympify still runs: {out}"


@pytest.mark.asyncio
async def test_sympify_cannot_import_os() -> None:
    """The live escape. This returned 'nt' before the fix."""
    ok, out = await _run(
        "import sympy as s\nprint(s.sympify(\"__import__('os').name\"))"
    )
    assert not ok, f"ARBITRARY IMPORT REACHED: {out}"
    assert "nt" not in out and "posix" not in out


@pytest.mark.parametrize(
    "gadget",
    [
        "import sympy as s\nprint(s.S('1+1'))",
        "import sympy as s\nx = s.Symbol('x')\nprint(s.lambdify(x, x))",
        "from sympy import sympify\nprint(sympify('1'))",
        "from sympy.parsing.sympy_parser import parse_expr\nprint(parse_expr('1'))",
        # Two ways round a rule that only looks at call sites: rename it on the
        # way in, or bind it to a name the checker has never heard of.
        "from sympy import sympify as f\nprint(f('1'))",
        "import sympy as s\nf = s.sympify\nprint(f('1'))",
        "import numpy as n\nw = n.savetxt\nprint(w)",
    ],
)
@pytest.mark.asyncio
async def test_the_other_codegen_doors_are_shut(gadget: str) -> None:
    ok, out = await _run(gadget)
    assert not ok, f"codegen reachable: {out}"


@pytest.mark.asyncio
async def test_sympy_singletons_still_work() -> None:
    """Blocking S() as a call must not break sp.S.Half, which is ordinary."""
    ok, out = await _run("import sympy as sp\nprint(sp.S.Half)")
    assert ok, out
    assert "1/2" in out


# --------------------------------------------------------------------------
# Escape 2: a dunder hidden in a string
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attrgetter_cannot_smuggle_a_dunder() -> None:
    ok, out = await _run(
        "import operator\nprint(operator.attrgetter('__class__')([]))"
    )
    assert not ok, f"dunder reached through a string: {out}"


@pytest.mark.parametrize(
    "payload",
    [
        "print('__class__')",
        "x = '__subclasses__'\nprint(x)",
        "print(f'{1}__globals__')",
        "import operator\nprint(operator.methodcaller('__str__')(1))",
    ],
)
@pytest.mark.asyncio
async def test_a_dunder_in_any_string_is_refused(payload: str) -> None:
    """Blanket rule. A scientific cell has no legitimate use for one, and
    enumerating the functions that take an attribute name as text is a
    denylist that will be shorter than the attack surface."""
    ok, out = await _run(payload)
    assert not ok, f"dunder string survived: {out}"


@pytest.mark.asyncio
async def test_the_direct_dunder_route_is_still_shut() -> None:
    for code in ("print([].__class__)", "print(object.__subclasses__())"):
        ok, out = await _run(code)
        assert not ok, out


# --------------------------------------------------------------------------
# Escape 3: the filesystem
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_numpy_cannot_write_a_file(tmp_path: Path) -> None:
    target = tmp_path / "escape.txt"
    ok, out = await _run(
        f"import numpy as n\nn.savetxt(r'{target}', [1.0])\nprint('wrote')"
    )
    assert not ok, f"the cell wrote to disk: {out}"
    assert not target.exists(), "a file was created by a tool that forbids files"


@pytest.mark.parametrize(
    "code",
    [
        "import numpy as n\nprint(n.load('x.npy'))",
        "import numpy as n\nprint(n.loadtxt('x.txt'))",
        "import numpy as n\nn.save('x', n.array([1]))",
        "import numpy as n\nn.array([1]).tofile('x.bin')",
        "import json\nprint(json.load('x'))",
    ],
)
@pytest.mark.asyncio
async def test_the_disk_is_out_of_reach(code: str) -> None:
    ok, out = await _run(code)
    assert not ok, f"filesystem reachable: {out}"


@pytest.mark.asyncio
async def test_json_round_trips_in_memory() -> None:
    """loads/dumps are fine; only the file-shaped calls are blocked."""
    ok, out = await _run("import json\nprint(json.loads(json.dumps({'a': 1})))")
    assert ok, out
    assert "'a': 1" in out


# --------------------------------------------------------------------------
# The guards that already existed, now actually tested
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import os\nprint(os.name)",
        "import subprocess",
        "import socket",
        "from os import path",
        "print(open('x'))",
        "print(eval('1'))",
        "print(exec('x=1'))",
        "print(__import__('os'))",
        "print(globals())",
        "print(getattr([], 'append'))",
    ],
)
@pytest.mark.asyncio
async def test_the_original_refusals_hold(code: str) -> None:
    ok, out = await _run(code)
    assert not ok, f"{code!r} was allowed: {out}"


@pytest.mark.asyncio
async def test_matplotlib_is_refused_with_the_route_to_plot() -> None:
    """The refusal has to teach, or the model just tries again."""
    ok, out = await _run("import matplotlib.pyplot as plt")
    assert not ok
    assert "plot" in out.lower()


@pytest.mark.asyncio
async def test_an_endless_loop_is_stopped() -> None:
    ok, out = await _run("while True:\n    pass")
    assert not ok
    assert "timed out" in out.lower()


@pytest.mark.asyncio
async def test_an_empty_cell_says_what_to_do() -> None:
    ok, out = await _run("   ")
    assert not ok
    assert "code" in out.lower()


@pytest.mark.asyncio
async def test_a_syntax_error_is_a_message_not_a_traceback() -> None:
    ok, out = await _run("def (:")
    assert not ok
    assert "syntax" in out.lower()


@pytest.mark.asyncio
async def test_output_is_capped() -> None:
    ok, out = await _run("print('x' * 50000)")
    assert ok, out
    assert len(out) < 20000
    assert "truncated" in out.lower()
