"""Apply the personal-data rules to every version of every file, not just the current one.

Why this is separate from the guard
===================================

``tests/test_no_personal_data.py`` reads ``git ls-files``: the tree as it stands. That is
the right scope for a pre-commit hook, which exists to stop the next mistake, and it is the
wrong scope for the question asked before a repository is made public. Making a repository
public publishes its history. A file that was committed once and deleted in the next commit
is still there, still fetchable, and no amount of tidiness at HEAD removes it.

So this walks every blob reachable from every ref and applies the same rules to all of them.
The rules are imported rather than restated, because a second copy of a regex is a second
copy that drifts, and the day they disagree is the day one of them is wrong and nobody knows
which.

What it cannot tell you
=======================

It reads the objects this clone has. That is the same set a ``git push`` sent, so it is the
right set -- but a leak that was pushed and then removed with a force-push may be gone from
here and still present in GitHub's copy, where unreachable objects survive and stay
retrievable by SHA. If this reports clean and a secret was ever force-pushed away, the
honest answer is to rotate the secret rather than to trust this.

It also says nothing about the name rules unless ``data/scrub-names.local.txt`` exists. That
file is generated from the operator's own contacts and is deliberately never committed, so
the most specific rules here are the ones a fresh clone cannot run. It reports loudly when
it had to skip them.

The credential rule keeps the guard's own exemption for the test suite, for the reason given
at ``credentials_apply``. Every other rule runs everywhere.

Nothing matched is ever printed. A report that quoted the value would put a private number
into a terminal that may be recorded, which is a worse leak than the commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# tests/ is a directory rather than a package -- there is no __init__.py and pytest does not
# need one -- so the directory itself goes on the path and the module is imported by name.
sys.path.insert(0, str(REPO_ROOT / "tests"))

import test_no_personal_data as guard

# The files whose job is to describe what is forbidden, and which therefore contain examples
# of it. The guard skips these by name for the same reason. This script is on the list
# because the paragraph above names the rules it runs.
SELF_DESCRIBING = frozenset(
    {
        "test_no_personal_data.py",
        "test_shipped_config_is_impersonal.py",
        "build_scrub_list.py",
        "audit_history.py",
    }
)

# Paths that should never have been committed at all, whatever is inside them. Checked by
# name because the answer does not depend on the contents: if data/secrets.yaml was ever a
# tracked file, the tokens in it are compromised regardless of what they looked like.
FORBIDDEN_PATHS = (
    ("data/profile.yaml", "the operator's own profile"),
    ("data/contacts.yaml", "real contacts"),
    ("data/secrets.yaml", "API keys and tokens"),
    ("data/memory.db", "the memory database"),
    ("data/calendar.ics", "a real calendar"),
    ("data/lessons.yaml", "corrections, which quote real exchanges"),
    ("data/scrub-names.local.txt", "the list of personal terms itself"),
    ("data/scrub-allow.local.txt", "the allow-list beside it"),
    ("data/action_ledger.jsonl", "an audit trail of real actions"),
    (".env", "environment secrets"),
)


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return done.stdout


def every_blob() -> dict[str, str]:
    """Every blob reachable from any ref, mapped to a path it was once stored at.

    ``--objects`` prints ``<sha> <path>`` for blobs and a bare sha for commits and trees.
    One path per blob is enough: the same content at two paths is the same content, and the
    report names a path only so a human can recognise what was found.
    """
    blobs: dict[str, str] = {}
    for line in git("rev-list", "--objects", "--all").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            blobs.setdefault(sha, path)
    return blobs


def stream_blobs(shas: list[str]) -> Iterator[tuple[str, bytes]]:
    """Yield each blob's bytes as `git cat-file --batch` produces it.

    One process for all of them, rather than one per object, because a process per blob took
    minutes and anything that takes minutes gets skipped before a release.

    Yielded rather than collected. Holding every version of every file in a dictionary is
    both unnecessary and actively bad -- fonts, icons and any binary ever committed are in
    there, and the peak is the whole history at once. Streaming keeps one blob in memory and
    lets the caller report progress that means something.
    """
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=REPO_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        bufsize=0,
    )
    assert process.stdin and process.stdout
    try:
        # Written on a thread, because git will not read the whole request before it starts
        # answering: filling the pipe while nobody drains the replies deadlocks both sides.
        import threading

        def feed() -> None:
            try:
                process.stdin.write(("\n".join(shas) + "\n").encode("ascii"))
                process.stdin.flush()
                process.stdin.close()
            except OSError:
                pass

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()

        for sha in shas:
            header = process.stdout.readline().decode("utf-8", "replace").split()
            if len(header) != 3:
                continue
            size = int(header[2])
            remaining = size
            chunks: list[bytes] = []
            while remaining > 0:
                chunk = process.stdout.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            process.stdout.read(1)
            yield sha, b"".join(chunks)
    finally:
        process.stdout.close()
        process.wait()


def commits_holding(sha: str) -> list[str]:
    """Which commits introduced or removed this exact content."""
    try:
        out = git("log", "--all", "--oneline", "--find-object", sha, "--max-count", "4")
    except subprocess.CalledProcessError:
        return []
    return out.splitlines()


def credentials_apply(path: str) -> bool:
    """Whether the credential rule is in scope for this path.

    ``test_no_shipped_file_carries_a_filled_in_credential`` skips the suite, because a test
    that exercises a password reader has to hand it something password-shaped. Repeating that
    exemption here rather than inventing a second answer keeps one decision about scope: the
    fixtures that made this necessary were a Google app password written the way Google
    displays it, in four groups of four, and a token for a loopback server, both of which miss
    the placeholder list only because a space and a hyphen are not word characters.

    Every other rule still runs over the suite. A real phone number or a real name in a test
    is a leak whatever the file is for; only "this string looks like a credential" is not.
    """
    return not path.startswith("tests/")


def text_findings(path: str, text: str, names: re.Pattern[str] | None) -> list[str]:
    """Every rule the guard applies to a text file, reported by rule name.

    Whole file first, then lines. The rules are per-line -- a postal code counts only beside
    a postal key, a coordinate only near a word about position -- but scanning line by line
    from the start meant every rule ran against every line of every version of every file,
    and the first attempt at this had not finished after four minutes. Almost every blob
    matches nothing, so one search over the whole text decides that cheaply, and the line
    numbers are only worth finding for the few that do.
    """
    if Path(path).name in SELF_DESCRIBING:
        return []

    credentials = credentials_apply(path)

    # Cheap enough to be worth doing before anything else, and it rules out most files.
    if not (
        guard.HOME_PATH.search(text)
        or guard.PHONE.search(text)
        or guard.CONSUMER_MAIL.search(text)
        or (credentials and guard.CREDENTIAL.search(text))
        or guard.COORDINATE.search(text)
        or guard.ANY_STATE.search(text)
        or guard.POSTAL_KEY.search(text)
        or (names is not None and names.search(text))
    ):
        return []

    found: list[str] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for who in guard.HOME_PATH.findall(line):
            if who.lower() not in guard.HOME_PLACEHOLDERS:
                found.append(f"a real home directory at line {line_no}")

        scrubbed = guard.HEX_DIGEST.sub(" ", guard.IPV4.sub(" ", line))
        for area, exchange, number in guard.PHONE.findall(scrubbed):
            if not guard._is_reserved(area, exchange, number):
                found.append(f"a dialable phone number at line {line_no}")

        for local, _provider in guard.CONSUMER_MAIL.findall(line):
            if local.lower() not in guard.MAILBOX_PLACEHOLDERS:
                found.append(f"a personal mailbox at line {line_no}")

        if credentials:
            for _key, value in guard.CREDENTIAL.findall(line):
                if not guard.CREDENTIAL_PLACEHOLDERS.match(value.strip()):
                    found.append(f"a filled-in credential at line {line_no}")

        if any(not guard._is_allowed_coordinate(v) for v in guard._coordinates_on(line)):
            found.append(f"a coordinate other than the fixture at line {line_no}")

        if guard.FOREIGN_STATE.search(line):
            found.append(f"a US state other than the fixture at line {line_no}")

        if guard.POSTAL_KEY.search(line) or guard.ANY_STATE.search(line):
            if any(code != guard.FIXTURE_POSTAL for code in guard.POSTAL.findall(line)):
                found.append(f"a postal code other than the fixture at line {line_no}")

        if names is not None:
            match = names.search(line)
            if match:
                found.append(
                    f"a term from your own records at line {line_no} "
                    f"(length {len(match.group(0))})"
                )

    return found


def binary_findings(path: str, blob: bytes, terms: set[str]) -> list[str]:
    """Personal terms inside a file no text rule would read, usually in metadata."""
    if Path(path).name in SELF_DESCRIBING:
        return []
    lowered = blob.lower()
    for term in terms:
        for encoded in (term.encode("ascii", "ignore"), term.encode("utf-16-le", "ignore")):
            if encoded and encoded in lowered:
                return [f"a term from your own records embedded in a binary (length {len(term)})"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_history.py",
        description="Check every version of every file for personal data before going public.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the verdict and the findings, not the progress.",
    )
    args = parser.parse_args(argv)

    def say(message: str) -> None:
        # flush, because stdout is a pipe whenever this is run from anything other than a
        # terminal, and Python buffers a pipe in 8KB blocks. Two runs of this were killed
        # for looking hung when they were working: the progress was in the buffer.
        if not args.quiet:
            print(message, flush=True)

    terms = guard._local_terms(guard.SCRUB_LIST) - guard._local_terms(guard.SCRUB_ALLOW)

    # One alternation rather than one pattern per term, which is what the state rule in the
    # guard already does. Hundreds of separate searches per line is the difference between
    # this finishing and this being abandoned. Longest first so the reported length is the
    # longest term that matched rather than whichever happened to be tried first.
    names = None
    if terms:
        alternation = "|".join(
            re.escape(term) for term in sorted(terms, key=len, reverse=True)
        )
        names = re.compile(rf"(?i)(?<![a-z0-9])(?:{alternation})(?![a-z0-9])")

    say(f"Repository : {REPO_ROOT}")
    say(f"Commits    : {len(git('rev-list', '--all').splitlines()):,}")
    if terms:
        say(f"Name rules : {len(terms):,} terms from your own contacts and profile")
    else:
        say(
            "Name rules : SKIPPED. data/scrub-names.local.txt is absent, so the checks "
            "that know who you are did not run. Generate it with "
            "scripts/build_scrub_list.py before trusting this."
        )

    blobs = every_blob()
    say(f"Blobs      : {len(blobs):,} versions of files across all history")

    findings: dict[str, list[str]] = defaultdict(list)

    for wanted, why in FORBIDDEN_PATHS:
        for sha, path in blobs.items():
            if path == wanted or path.endswith("/" + wanted):
                findings[f"{path} [{sha[:10]}]"].append(f"was committed at all -- {why}")

    shas = list(blobs)
    binary_suffixes = guard.BINARY_SUFFIXES
    long_terms = {t for t in terms if len(t) >= 6}
    say("Scanning   : reading and checking each one in turn...")
    for done, (sha, blob) in enumerate(stream_blobs(shas), 1):
        if not args.quiet and done % 250 == 0:
            print(f"             {done:,} of {len(shas):,}", flush=True)
        path = blobs[sha]
        if Path(path).suffix.lower() in binary_suffixes:
            hits = binary_findings(path, blob, long_terms) if long_terms else []
        else:
            try:
                hits = text_findings(path, blob.decode("utf-8"), names)
            except UnicodeDecodeError:
                hits = binary_findings(path, blob, long_terms) if long_terms else []
        if hits:
            # Deduplicated: one line reported by three rules is one thing to look at.
            findings[f"{path} [{sha[:10]}]"].extend(sorted(set(hits))[:12])

    print("")
    if not findings:
        print("CLEAN: no version of any file matched a rule.")
        if not terms:
            print(
                "  Read as: clean against the shape rules only. The name rules did not run."
            )
            return 2
        return 0

    print(f"FOUND: {len(findings)} file version(s) matched a rule.\n")
    for where, why in sorted(findings.items()):
        print(f"  {where}")
        for reason in why:
            print(f"      {reason}")
        sha = where.split("[")[-1].rstrip("]")
        for commit in commits_holding(sha):
            print(f"      in {commit}")
        print("")

    print(
        "Nothing above is quoted on purpose. Open the blob with `git cat-file -p <sha>` to\n"
        "see it. A match at HEAD is fixable with a commit; a match only in history is not\n"
        "removable without rewriting history, and anything secret in it should be rotated\n"
        "rather than deleted."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
