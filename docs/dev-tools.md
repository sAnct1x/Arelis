# Developer tools

Two scripts for people working on the checkout. Neither one runs in the
app. They do not change runtime code, tool definitions, or prompts.

Install the extras they need with `pip install -e ".[dev]"`. Ruff is
already there. Vulture is in the same extra. The Windows installer lock
does not include them.

## Repo scan

`scripts/repo_scan.py` runs ruff over the tree, vulture over `arelis/`,
and a small import-cycle / package-edge walk over `arelis/`. It also
lists the biggest modules by line count. The result is a short markdown
report.

```bash
python scripts/repo_scan.py
python scripts/repo_scan.py --out scan.md
```

`--out` writes the file. Omit it and the same text goes to stdout.

This is a report, not a gate. A dirty tree still exits 0. Use it before
a pull request when you want counts, not when you want CI to go red.

## Scope check

`scripts/scope_check.py` looks at
`git diff --name-status --no-renames base...HEAD` and prints every
changed path that is not covered by the allow list, including the old
path of a rename. Exit 1 if anything extra showed up.

The allow list is globs. Pass them with repeated `--allow`, or put one
glob per line in a file (`--allow-file`). Blank lines and `#` comments
in that file are ignored.

```bash
python scripts/scope_check.py main --allow 'scripts/*' --allow 'docs/*'
python scripts/scope_check.py origin/main --allow-file allowed.txt
```

A tooling-only pull request can keep itself honest this way: if a
runtime file slipped in, the script names it.

## What this is not

These scripts are not part of the installed program. CI does not run
them. Adding them does not change how Arelis talks, what tools she has,
or what she is allowed to do.
