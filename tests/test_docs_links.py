"""Every link in the documentation points at something that exists.

The README is the first thing a stranger reads, and it had six links to
documents that had been deleted — which reads either as neglect or as a
download that is missing pieces. Neither impression is recoverable from a first
visit, and neither is worth a human proofreading the file every time a document
is renamed.

Only relative links are checked. An external URL can rot too, but finding out
would need a network call, and a test suite that fails because someone else's
web server is down is a test suite people learn to ignore.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# [text](target) — the target group stops at whitespace or the closing paren so
# that a title, as in [text](target "Title"), does not become part of the path.
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)")

SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def _markdown_files() -> list[Path]:
    """Tracked prose. Excludes the working notes, which are not published."""
    roots = [PROJECT_ROOT / "README.md", PROJECT_ROOT / "CONTRIBUTING.md"]
    roots.extend(sorted((PROJECT_ROOT / "docs").glob("*.md")))
    return [path for path in roots if path.is_file()]


def test_every_relative_link_in_the_docs_resolves() -> None:
    broken: list[str] = []
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            for target in MARKDOWN_LINK.findall(line):
                if target.startswith(SKIP_PREFIXES):
                    continue
                # Strip any in-page anchor: docs/x.md#section is still docs/x.md.
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                if not (path.parent / relative).resolve().exists():
                    broken.append(
                        f"{path.relative_to(PROJECT_ROOT)}:{line_no} -> {target}"
                    )

    assert not broken, (
        "A link points at a file that is not there. Either the file moved and "
        "the link needs updating, or the link describes something that was "
        "never written:\n  " + "\n  ".join(broken)
    )


def test_the_readme_does_not_promise_an_installer_that_does_not_exist() -> None:
    """Honesty about the current state, checked rather than remembered.

    The README is written for a stranger, and the packaged installer is several
    phases away. Saying "download the installer" before one exists would be the
    single most damaging sentence in the file. When the installer ships, this
    test is what tells whoever updates the README that the caveat above the
    install steps also has to go.
    """
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    installer_dir = PROJECT_ROOT / "installer"
    if installer_dir.is_dir():
        return  # An installer exists now; the caveat is free to go.

    assert "not ready yet" in text.lower(), (
        "There is no installer in the tree, so the README must still say so. A "
        "reader who follows install instructions that cannot work concludes the "
        "whole project is broken, and they are not wrong to."
    )
