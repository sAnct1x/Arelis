"""Scope-check matching: a path outside the allow list is flagged.

The script exists so a tooling-only pull request cannot quietly pick up
a runtime file. If extra-file flagging is removed, this test fails.
"""

from __future__ import annotations

from pathlib import Path

from scripts.scope_check import extra_paths, load_allow_globs


def test_scope_check_flags_paths_outside_the_allow_list(tmp_path: Path) -> None:
    changed = [
        "scripts/repo_scan.py",
        "docs/dev-tools.md",
        "arelis/main.py",
        "arelis/tools/web.py",
    ]
    extras = extra_paths(changed, ["scripts/*", "docs/*"])
    assert extras == ["arelis/main.py", "arelis/tools/web.py"]

    assert extra_paths(["README.md", "docs/a.md"], ["docs/*"]) == ["README.md"]
    assert extra_paths(["tests/test_scope_check.py"], ["tests/test_scope_check.py"]) == []
    assert extra_paths(["scripts/dev/foo.py"], ["scripts/"]) == []
    assert extra_paths(["arelis/ui/app.py"], ["scripts", "docs"]) == ["arelis/ui/app.py"]

    allow_file = tmp_path / "allowed.txt"
    allow_file.write_text(
        "# tooling only\n\nscripts/*\ndocs/*\n",
        encoding="utf-8",
    )
    globs = load_allow_globs(allow_file)
    assert globs == ["scripts/*", "docs/*"]
    assert extra_paths(changed, globs) == ["arelis/main.py", "arelis/tools/web.py"]
