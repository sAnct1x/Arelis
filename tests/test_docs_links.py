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


def test_the_readme_offers_the_published_installer() -> None:
    """The front door must lead with the setup .exe, not a developer install.

    This used to pin the opposite sentence — "an installer is coming, and it is
    not ready yet" — because that was true, and promising a download before one
    existed would have been the most damaging line on the page. The installer
    shipped. The damage now is the old caveat surviving. win-installer/ is the
    proof it can be built; the README has to tell a stranger where to get it,
    that it is unsigned, and how to check the published digest.
    """
    assert (PROJECT_ROOT / "win-installer" / "build.py").is_file()
    assert (PROJECT_ROOT / "win-installer" / "arelis.iss").is_file()

    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "not ready yet" not in lower, (
        "The README still says the installer is not ready. It is published. "
        "A stranger who reads that walks away from a working download."
    )
    assert "an installer is coming" not in lower, (
        "The README still talks about an installer in the future tense."
    )
    assert "releases/latest" in lower or "setup.exe" in lower, (
        "The README does not point at the published setup .exe or the releases "
        "page, so a stranger has no way in except from source."
    )
    assert "unsigned" in lower or "smartscreen" in lower, (
        "The installer is not code-signed. The README has to say so, rather "
        "than leaving SmartScreen as a surprise that reads as malware."
    )
    assert "sha-256" in lower or "sha256" in lower, (
        "The README tells someone the installer is unsigned but does not tell "
        "them the digest they can actually check."
    )


def test_every_top_level_doc_is_linked_from_the_readme() -> None:
    """A page under docs/ that the README never mentions is invisible.

    Subfolders (releases, testing) are working notes for a version, not the
    front door, so they are not required here.
    """
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    missing = []
    for path in sorted((PROJECT_ROOT / "docs").glob("*.md")):
        needle = f"docs/{path.name}"
        if needle not in readme.replace("\\", "/"):
            missing.append(path.name)
    assert not missing, (
        "These documents are not linked from the README, so a stranger will "
        "not find them:\n  " + "\n  ".join(missing)
    )


def test_readme_role_models_match_shipped_defaults() -> None:
    """The role table on the front door has to name the models the code uses.

    Three tags, copied by hand, is how a README quietly describes an assistant
    that no longer exists after someone retunes default.yaml.
    """
    import yaml

    config = yaml.safe_load(
        (PROJECT_ROOT / "arelis" / "config" / "default.yaml").read_text(
            encoding="utf-8"
        )
    )
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    missing = []
    for role in ("fast", "research", "code"):
        tag = str((config.get("models") or {}).get(role) or "").strip()
        assert tag, f"default.yaml has no models.{role}"
        if tag not in readme:
            missing.append(f"{role} -> {tag}")
    assert not missing, (
        "The README does not name these shipped models:\n  " + "\n  ".join(missing)
    )


def test_readme_named_scripts_exist() -> None:
    """A command the README tells someone to run has to be in the tree."""
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    named = re.findall(r"scripts[/\\][\w.-]+", readme)
    missing = []
    seen: set[str] = set()
    for raw in named:
        rel = raw.replace("\\", "/")
        if rel in seen:
            continue
        seen.add(rel)
        if not (PROJECT_ROOT / rel).is_file():
            missing.append(rel)
    assert named, "The README names no scripts; the check cannot bind."
    assert not missing, (
        "The README tells someone to run a script that is not there:\n  "
        + "\n  ".join(missing)
    )
