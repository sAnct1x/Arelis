"""Scope-check matching: a path outside the allow list is flagged.

The script exists so a tooling-only pull request cannot quietly pick up
a runtime file. If extra-file flagging is removed, this test fails.
A rename that only lists the new path is the same miss: the old path
has to be checked too.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts.scope_check import extra_paths, load_allow_globs, main, matches


def _git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "tester"
    env["GIT_AUTHOR_EMAIL"] = "you@example.com"
    env["GIT_COMMITTER_NAME"] = "tester"
    env["GIT_COMMITTER_EMAIL"] = "you@example.com"
    subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=tester",
            "-c",
            "user.email=you@example.com",
            *args,
        ],
        cwd=repo,
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def _commit_tree(repo: Path, files: dict[str, str], message: str) -> None:
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        _git(repo, "add", rel)
    _git(repo, "commit", "--no-verify", "-m", message)


def test_scope_check_flags_paths_outside_the_allow_list(tmp_path: Path, capsys) -> None:
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
    # Plain path, no glob and no trailing slash: the folder itself.
    assert matches("scripts/dev/foo.py", "scripts") is True
    assert extra_paths(["scripts/dev/foo.py"], ["scripts"]) == []

    allow_file = tmp_path / "allowed.txt"
    allow_file.write_text(
        "# tooling only\n\nscripts/*\ndocs/*\n",
        encoding="utf-8",
    )
    globs = load_allow_globs(allow_file)
    assert globs == ["scripts/*", "docs/*"]
    assert extra_paths(changed, globs) == ["arelis/main.py", "arelis/tools/web.py"]

    extras_repo = tmp_path / "extras"
    extras_repo.mkdir()
    _git(extras_repo, "init")
    _commit_tree(extras_repo, {"scripts/ok.py": "ok\n"}, "base")
    _commit_tree(extras_repo, {"arelis/main.py": "nope\n"}, "extra")

    assert main(["HEAD~1", "--allow", "scripts/*", "--root", str(extras_repo)]) == 1
    captured = capsys.readouterr()
    assert "arelis/main.py" in captured.out.splitlines()

    assert main(
        [
            "HEAD~1",
            "--allow",
            "scripts/*",
            "--allow",
            "arelis/*",
            "--root",
            str(extras_repo),
        ]
    ) == 0
    assert capsys.readouterr().out == ""

    assert main(["HEAD~1", "--root", str(extras_repo)]) == 2
    assert "pass --allow or --allow-file" in capsys.readouterr().err

    rename_repo = tmp_path / "rename"
    rename_repo.mkdir()
    _git(rename_repo, "init")
    _commit_tree(rename_repo, {"arelis/core.py": "core\n"}, "base")
    (rename_repo / "scripts").mkdir()
    _git(rename_repo, "mv", "arelis/core.py", "scripts/core.py")
    _git(rename_repo, "commit", "--no-verify", "-m", "rename")

    assert main(["HEAD~1", "--allow", "scripts/*", "--root", str(rename_repo)]) == 1
    renamed = capsys.readouterr()
    assert "arelis/core.py" in renamed.out.splitlines()
