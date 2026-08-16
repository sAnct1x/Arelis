"""Move a person's Arelis profile from a source checkout into an installed copy.

Why this exists
===============

``user_data_dir()`` sends a checkout to the repository root and an install to
``%LOCALAPPDATA%\\Arelis``, on markers a wheel cannot have. That separation is deliberate
and good -- two copies of Arelis on one machine do not tread on each other -- but it has
one consequence nobody enjoys discovering: installing does not bring your profile with it.
The installed Arelis opens as a stranger's. Whoever ran from source before there was an
installer has to move house exactly once, and this is the moving van.

What it does not copy, and why that is the point
================================================

The temptation is to copy the data directory wholesale. That is wrong, and not only for
size. A checkout's data directory accumulates three things a new install should not
inherit:

* caches, which exist to be thrown away and whose only cost is being rebuilt;
* test residue, because the suite historically wrote into the live profile;
* a document index whose every row is a file path *inside the checkout*, which in an
  installed copy is stale at best and misleading at worst.

So this copies an allow-list and states a reason for every entry. Nothing arrives here by
being in the source directory; things arrive by being named, which means the list can be
read and argued with. Anything unrecognised is reported as skipped rather than copied
silently, so a file added later shows up as a question instead of vanishing.

memory.db in particular
=======================

It is the file people most want to bring and the one most misleading to copy. Of roughly
24,500 rows in a working database, about 460 are memory -- facts, preferences, goals,
decisions, episodes, summaries, conversations -- and the rest is a rebuildable index over
documents on disk, which is where nearly all of the size lives. So this copies the memory
and leaves the index to rebuild itself against whatever the install actually points at.

The schema is created by ``MemoryStore`` rather than by SQL written here, because there is
already one authority on what an Arelis database looks like and a second one would drift
from it. Both sides are then checked against ``SCHEMA_VERSION``: copying rows between two
schemas that disagree is how you get a database that opens fine and is wrong.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arelis.memory.store import SCHEMA_VERSION, MemoryStore

# Files under data/, each with the reason it is worth carrying. A file not named here is
# not copied, and is reported so that the omission is visible rather than assumed.
FILES: tuple[tuple[str, str], ...] = (
    ("profile.yaml", "who you are; the one file that makes this your Arelis"),
    ("contacts.yaml", "the people it can reach"),
    ("secrets.yaml", "API keys and tokens, without which most of it cannot run"),
    ("lessons.yaml", "corrections you have already had to make once"),
    ("jobs.yaml", "your scheduled jobs, so the install owns the timers"),
    ("calendar.ics", "your calendar"),
    ("config.local.yaml", "settings you changed away from the defaults"),
    (
        "sms_inbound_seen.json",
        "which inbound messages have been handled. Not a cache: without it every old "
        "message looks new, and Arelis acts on them again",
    ),
    ("pending_confirms.json", "actions waiting on your yes or no"),
    ("token_ratios.json", "budget calibration, small and annoying to relearn"),
    ("ui_layout.ini", "your window layout"),
)

DIRECTORIES: tuple[tuple[str, str], ...] = (("drops", "files you handed to Arelis"),)

# Named so that the dry run can explain the absences. Every one of these is either
# rebuildable, test residue, or a template already inside the wheel.
SKIP: tuple[tuple[str, str], ...] = (
    (
        "browser-profile",
        "189MB of Chromium profile, nearly all of it browser cache. The few megabytes "
        "that matter are logged-in sessions, and a fresh install is better off logging "
        "in once than inheriting stale session tokens",
    ),
    ("tool_cache", "a cache; deleting it costs one rebuild"),
    ("backups", "old memory.db snapshots, still in the checkout if ever wanted"),
    ("calendar_cache.db", "rebuilt from calendar.ics on first use"),
    (
        "action_ledger.jsonl",
        "an audit trail of what the checkout did, including test runs that wrote into "
        "the live profile. The install should start its own",
    ),
    ("active_project", "a pointer into the checkout's workspace, wrong once installed"),
    ("scrub-allow.local.txt", "pre-commit tooling, not something the app reads"),
    ("scrub-names.local.txt", "pre-commit tooling, not something the app reads"),
    ("ui_layout.ini.bak_ghost", "a stray backup"),
    (
        "memory.db-wal",
        "SQLite's write-ahead log. Nothing is lost by leaving it: the migration reads "
        "through SQLite rather than copying bytes, so anything committed to the log is "
        "already counted in the rows above",
    ),
    ("memory.db-shm", "SQLite's shared-memory index for the log above, valid only while open"),
)

# Suffix and prefix rules for the same purpose, kept apart from the exact names so the
# reason can be stated once instead of per file.
SKIP_PATTERNS: tuple[tuple[str, str], ...] = (
    ("e2e_", "end-to-end test output"),
    (".example.", "a template, already shipped inside the wheel"),
)

# Insert order is foreign-key order: sessions before anything referencing a session,
# messages before their embeddings, goals before the tasks that may point at one.
# messages_fts and its siblings are absent on purpose -- they are maintained by triggers,
# so inserting a message rebuilds its search index as a side effect.
MEMORY_TABLES: tuple[str, ...] = (
    "sessions",
    "messages",
    "summaries",
    "facts",
    "embeddings",
    "goals",
    "tasks",
    "episodes",
    "preferences",
    "decisions",
)

# Left behind deliberately. Rows here name files by path inside the source checkout, and
# they are the overwhelming majority of the file's size.
MEMORY_TABLES_REBUILT: tuple[str, ...] = (
    "documents",
    "document_chunks",
    "document_embeddings",
)


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return ""


def tree_size(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def installed_data_root() -> Path:
    """Where an installed Arelis on this machine keeps its data.

    Duplicating the Windows branch of ``user_data_dir()`` rather than calling it, because
    calling it from inside the checkout would answer for the checkout. The whole job here
    is to talk about the other copy.
    """
    if sys.platform != "win32":
        raise SystemExit("--to is required off Windows; there is no install root to guess")
    base = os.environ.get("LOCALAPPDATA", "").strip()
    return (Path(base) if base else Path.home() / "AppData" / "Local") / "Arelis"


def skip_reason(name: str) -> str | None:
    for skipped, reason in SKIP:
        if name == skipped:
            return reason
    for fragment, reason in SKIP_PATTERNS:
        if name.startswith(fragment) or fragment in name:
            return reason
    return None


def copy_file(src: Path, dst: Path, apply: bool, overwrite: bool) -> str:
    if not src.exists():
        return "absent in the source"
    if dst.exists() and not overwrite:
        return "already there, left alone"
    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return f"{human(src.stat().st_size)}"


def copy_directory(src: Path, dst: Path, apply: bool, overwrite: bool) -> str:
    if not src.is_dir():
        return "absent in the source"
    count, size = tree_size(src)
    if dst.exists() and not overwrite:
        return "already there, left alone"
    if apply:
        shutil.copytree(src, dst, dirs_exist_ok=True)
    return f"{count} files, {human(size)}"


def memory_row_counts(path: Path, tables: tuple[str, ...]) -> dict[str, int]:
    """Row counts for tables that exist, opened strictly read-only.

    ``mode=ro`` rather than a plain connect: this runs against a database the person is
    still using, and a tool whose job is to read must not be able to create a journal
    beside it, let alone write.
    """
    if not path.exists():
        return {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        present = {r[0] for r in con.execute("select name from sqlite_master where type=?", ("table",))}
        return {t: con.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables if t in present}
    finally:
        con.close()


def migrate_memory(src: Path, dst: Path, apply: bool, overwrite: bool) -> None:
    if not src.exists():
        print("  memory.db      absent in the source")
        return

    src_counts = memory_row_counts(src, MEMORY_TABLES)
    rebuilt = memory_row_counts(src, MEMORY_TABLES_REBUILT)
    carried = sum(src_counts.values())
    left = sum(rebuilt.values())
    print(f"  memory.db      {human(src.stat().st_size)} in the source")
    print(f"                 {carried} rows of memory to carry, {left} rows of index to rebuild")

    existing = memory_row_counts(dst, MEMORY_TABLES)
    if sum(existing.values()) and not overwrite:
        occupied = ", ".join(f"{t}={n}" for t, n in existing.items() if n)
        raise SystemExit(
            f"\n{dst} already holds memory ({occupied}).\n"
            "Refusing to merge two histories into one database. Move it aside, or pass "
            "--overwrite to add these rows to it."
        )

    if not apply:
        for table, n in src_counts.items():
            if n:
                print(f"                   {table:14} {n:6}")
        return

    # Let the application create the schema, then close it and do the bulk copy over a
    # plain connection. Two reasons: the store is the only authority on the schema, and
    # borrowing its private connection to run inserts would be a worse dependency than
    # opening our own.
    store = MemoryStore(dst)
    version = store.schema_version
    store.close()
    if version != SCHEMA_VERSION:
        raise SystemExit(f"{dst} came out at schema {version}, expected {SCHEMA_VERSION}")

    src_con = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    src_version = int(src_con.execute("PRAGMA user_version").fetchone()[0])
    if src_version != SCHEMA_VERSION:
        src_con.close()
        raise SystemExit(
            f"{src} is schema {src_version} and this build is {SCHEMA_VERSION}. Open it "
            "with a matching Arelis first so its migrations run; copying rows across a "
            "schema gap produces a database that opens fine and is wrong."
        )

    dst_con = sqlite3.connect(dst)
    dst_con.execute("PRAGMA foreign_keys=ON")
    try:
        for table in MEMORY_TABLES:
            columns = [c[1] for c in dst_con.execute(f'PRAGMA table_info("{table}")')]
            available = {c[1] for c in src_con.execute(f'PRAGMA table_info("{table}")')}
            missing = [c for c in columns if c not in available]
            if missing:
                raise SystemExit(f"{table} in the source has no {', '.join(missing)}")
            quoted = ", ".join(f'"{c}"' for c in columns)
            rows = src_con.execute(f"SELECT {quoted} FROM \"{table}\"").fetchall()
            if not rows:
                continue
            placeholders = ", ".join("?" * len(columns))
            dst_con.executemany(
                f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', rows
            )
            print(f"                   {table:14} {len(rows):6} copied")
        dst_con.commit()
        # The search index is populated by triggers, so this is a check that they fired
        # rather than a step. A silent zero here would mean memory that cannot be found.
        indexed = dst_con.execute("select count(*) from messages_fts").fetchone()[0]
        print(f"                   {'messages_fts':14} {indexed:6} rebuilt by trigger")
    finally:
        dst_con.close()
        src_con.close()


def move_models(src: Path, dst: Path, apply: bool) -> None:
    if not src.is_dir():
        print("  models         absent in the source")
        return
    count, size = tree_size(src)
    print(f"  models         {count} files, {human(size)} -- moved, not copied")
    for child in sorted(src.iterdir()):
        target = dst / child.name
        if target.exists():
            print(f"                   {child.name:14} already there, left in place")
            continue
        print(f"                   {child.name:14} -> {target}")
        if apply:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.move(str(child), str(target))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy an Arelis profile from a source checkout into an installed copy.",
    )
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        default=REPO_ROOT,
        help="Source data root. Defaults to this checkout, which is its own data root.",
    )
    parser.add_argument(
        "--to",
        dest="destination",
        type=Path,
        default=None,
        help="Destination data root. Defaults to the installed copy's, %%LOCALAPPDATA%%\\Arelis.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually copy. Without it this prints the plan and changes nothing, which "
            "is the default because the subject is somebody's profile."
        ),
    )
    parser.add_argument(
        "--move-models",
        action="store_true",
        help=(
            "Also move the models directory. A move rather than a copy: these are large, "
            "immutable downloads, and the copy that is used every day should hold them."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace files that already exist at the destination instead of leaving them.",
    )
    args = parser.parse_args(argv)

    source = args.source.expanduser().resolve()
    destination = (args.destination or installed_data_root()).expanduser().resolve()

    if source == destination:
        raise SystemExit("the source and destination are the same directory")
    if destination.is_relative_to(source) and (source / "pyproject.toml").is_file():
        raise SystemExit(f"{destination} is inside the checkout; that is not a migration")
    if not (source / "data").is_dir():
        raise SystemExit(f"{source} has no data directory, so it is not a data root")

    print(f"from {source}")
    print(f"to   {destination}")
    print("DRY RUN -- nothing is written. Pass --apply to do it.\n" if not args.apply else "")

    print("Carried:")
    for name, reason in FILES:
        result = copy_file(source / "data" / name, destination / "data" / name, args.apply, args.overwrite)
        print(f"  {name:22} {result:28} {reason}")
    for name, reason in DIRECTORIES:
        result = copy_directory(source / "data" / name, destination / "data" / name, args.apply, args.overwrite)
        print(f"  {name:22} {result:28} {reason}")

    print("\nMemory:")
    migrate_memory(source / "data" / "memory.db", destination / "data" / "memory.db", args.apply, args.overwrite)

    if args.move_models:
        print("\nModels:")
        move_models(source / "models", destination / "models", args.apply)

    print("\nLeft behind:")
    for name, reason in SKIP:
        if (source / "data" / name).exists():
            print(f"  {name:22} {reason}")

    named = {n for n, _ in FILES} | {n for n, _ in DIRECTORIES} | {n for n, _ in SKIP}
    unknown = [
        p.name
        for p in sorted((source / "data").iterdir())
        if p.name not in named and skip_reason(p.name) is None and p.name != "memory.db"
    ]
    if unknown:
        print("\nNot in either list, so not copied. Add them above if they matter:")
        for name in unknown:
            print(f"  {name}")

    if not args.apply:
        print("\nNothing was written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
