"""Write a short markdown report from free static tools.

This is a read-only scan. It does not change application code, tool
definitions, or prompts. Ruff and vulture come from the dev extra.
Import cycles are a small graph walk over ``arelis/``, so that check
does not need another package.

``--out`` writes the report. Omit it and the same text goes to stdout.
Findings are listed, not gated: a dirty report still exits 0 so this
stays a data dump, not a second CI job.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOP = 15
SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
    ".tmp_pdfium",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def _write(path: Path | None, text: str) -> None:
    if path is None:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cwd=cwd, args=cmd, capture_output=True, text=True, check=False)


def _iter_py_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _module_name(package_root: Path, path: Path) -> str:
    rel = path.relative_to(package_root.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_parts(module: str, is_package: bool, level: int) -> list[str]:
    """Package path that a relative import of ``level`` dots starts from."""
    parts = module.split(".")
    if not is_package:
        parts = parts[:-1]
    cut = max(level - 1, 0)
    if cut:
        parts = parts[:-cut] if cut <= len(parts) else []
    return parts


def _resolve_from(module: str, is_package: bool, node: ast.ImportFrom) -> list[str]:
    """Turn a relative or absolute ``from`` import into module names."""
    names: list[str] = []
    if node.level:
        prefix = ".".join(_package_parts(module, is_package, node.level))
        if node.module:
            target = f"{prefix}.{node.module}" if prefix else node.module
        else:
            target = prefix
        if target:
            names.append(target)
        if node.module is None:
            for alias in node.names:
                if alias.name != "*":
                    names.append(f"{target}.{alias.name}" if target else alias.name)
        return names
    if node.module:
        names.append(node.module)
        for alias in node.names:
            if alias.name != "*":
                names.append(f"{node.module}.{alias.name}")
    return names


def import_graph(package_dir: Path) -> dict[str, set[str]]:
    """First-party import graph for ``arelis`` modules only."""
    package = package_dir.name
    known: dict[str, Path] = {}
    packages: set[str] = set()
    for path in _iter_py_files(package_dir):
        name = _module_name(package_dir, path)
        known[name] = path
        if path.name == "__init__.py":
            packages.add(name)
    graph: dict[str, set[str]] = {name: set() for name in known}
    for name, path in known.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.update(_resolve_from(name, name in packages, node))
        for imported in found:
            if imported == name or not (
                imported == package or imported.startswith(package + ".")
            ):
                continue
            candidate = imported
            while candidate and candidate not in known:
                if "." not in candidate:
                    candidate = ""
                    break
                candidate = candidate.rsplit(".", 1)[0]
            if candidate and candidate != name:
                graph[name].add(candidate)
    return graph


def strongly_connected(graph: dict[str, set[str]]) -> list[list[str]]:
    nodes = set(graph)
    for dests in graph.values():
        nodes.update(dests)
    adj = {node: set(graph.get(node, ())) for node in nodes}
    visited: set[str] = set()
    order: list[str] = []

    def dfs(start: str) -> None:
        stack: list[tuple[str, Iterator[str]]] = [(start, iter(adj[start]))]
        visited.add(start)
        while stack:
            node, iterator = stack[-1]
            try:
                nxt = next(iterator)
            except StopIteration:
                order.append(node)
                stack.pop()
                continue
            if nxt not in visited:
                visited.add(nxt)
                stack.append((nxt, iter(adj[nxt])))

    for node in sorted(nodes):
        if node not in visited:
            dfs(node)

    rev: dict[str, set[str]] = {node: set() for node in nodes}
    for src, dests in adj.items():
        for dest in dests:
            rev[dest].add(src)

    visited.clear()
    groups: list[list[str]] = []

    def dfs_rev(start: str, acc: list[str]) -> None:
        stack = [start]
        visited.add(start)
        acc.append(start)
        while stack:
            node = stack.pop()
            for nxt in rev[node]:
                if nxt not in visited:
                    visited.add(nxt)
                    acc.append(nxt)
                    stack.append(nxt)

    for node in reversed(order):
        if node not in visited:
            acc: list[str] = []
            dfs_rev(node, acc)
            groups.append(sorted(acc))
    return groups


def cycle_groups(graph: dict[str, set[str]]) -> list[list[str]]:
    found: list[list[str]] = []
    for group in strongly_connected(graph):
        if len(group) > 1:
            found.append(group)
            continue
        name = group[0]
        if name in graph.get(name, ()):
            found.append(group)
    return found


def package_edges(graph: dict[str, set[str]]) -> list[tuple[str, str, int]]:
    """Counts of top-level package hops (arelis.ui -> arelis.core, ...)."""
    counts: Counter[tuple[str, str]] = Counter()
    for src, dests in graph.items():
        src_pkg = ".".join(src.split(".")[:2])
        for dest in dests:
            dest_pkg = ".".join(dest.split(".")[:2])
            if src_pkg != dest_pkg:
                counts[(src_pkg, dest_pkg)] += 1
    return [(src, dest, n) for (src, dest), n in counts.most_common()]


def _line_count(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def biggest_modules(package_dir: Path, limit: int = TOP) -> list[tuple[str, int]]:
    rows = [
        (path.relative_to(package_dir.parent).as_posix(), _line_count(path))
        for path in _iter_py_files(package_dir)
    ]
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows[:limit]


def run_ruff(root: Path) -> tuple[str, list[str]]:
    """Return (summary, top finding lines). Missing ruff is a note, not a crash."""
    probe = _run([sys.executable, "-m", "ruff", "--version"], root)
    if probe.returncode != 0:
        return "ruff is not installed. `pip install -e \".[dev]\"` adds it.", []
    result = _run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format=json"],
        root,
    )
    raw = (result.stdout or "").strip()
    if not raw:
        if result.returncode == 0:
            return "0 findings.", []
        err = (result.stderr or "ruff failed").strip()
        return f"ruff failed: {err}", []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return f"ruff returned non-JSON (exit {result.returncode}).", []
    if not isinstance(items, list):
        return "ruff returned an unexpected payload.", []
    if not items:
        return "0 findings.", []
    codes = Counter(str(item.get("code") or "?") for item in items)
    top_rules = ", ".join(f"{code} ({n})" for code, n in codes.most_common(8))
    summary = f"{len(items)} finding(s) across {len({item.get('filename') for item in items})} file(s)."
    if top_rules:
        summary += f" Top rules: {top_rules}."
    lines: list[str] = []
    for item in items[:TOP]:
        filename = str(item.get("filename") or "")
        try:
            rel = Path(filename).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = filename
        loc = item.get("location") or {}
        row = loc.get("row", "?")
        code = item.get("code") or "?"
        message = (item.get("message") or "").strip()
        lines.append(f"`{rel}:{row}` {code} {message}")
    leftover = len(items) - len(lines)
    if leftover > 0:
        lines.append(f"... {leftover} more")
    return summary, lines


def run_vulture(package_dir: Path) -> tuple[str, list[str]]:
    probe = _run([sys.executable, "-m", "vulture", "--version"], package_dir.parent)
    if probe.returncode != 0:
        return "vulture is not installed. `pip install -e \".[dev]\"` adds it.", []
    result = _run(
        [sys.executable, "-m", "vulture", str(package_dir), "--min-confidence", "80"],
        package_dir.parent,
    )
    rows = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    # vulture prints one finding per line; stderr is noise we ignore.
    if result.returncode not in {0, 1, 3}:
        err = (result.stderr or "vulture failed").strip()
        return f"vulture failed (exit {result.returncode}): {err}", []
    summary = f"{len(rows)} unused name(s) at confidence 80+."
    lines = []
    for row in rows[:TOP]:
        lines.append(f"`{row}`")
    leftover = len(rows) - len(lines)
    if leftover > 0:
        lines.append(f"... {leftover} more")
    return summary, lines


def _md_list(items: list[str]) -> str:
    if not items:
        return "None.\n"
    return "".join(f"- {item}\n" for item in items)


def build_report(root: Path) -> str:
    package = root / "arelis"
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    ruff_summary, ruff_lines = run_ruff(root)
    vulture_summary, vulture_lines = run_vulture(package)
    graph = import_graph(package) if package.is_dir() else {}
    cycles = cycle_groups(graph)
    edges = package_edges(graph)
    modules = biggest_modules(package) if package.is_dir() else []
    py_files = _iter_py_files(package) if package.is_dir() else []
    total_lines = sum(_line_count(path) for path in py_files)

    cycle_lines: list[str] = []
    for group in cycles[:TOP]:
        cycle_lines.append(", ".join(f"`{name}`" for name in group[:12]))
        if len(group) > 12:
            cycle_lines[-1] += f", ... ({len(group)} modules)"
    leftover_cycles = len(cycles) - len(cycle_lines)
    if leftover_cycles > 0:
        cycle_lines.append(f"... {leftover_cycles} more groups")

    edge_lines = [
        f"`{src}` -> `{dest}` ({n})" for src, dest, n in edges[:TOP]
    ]
    leftover_edges = len(edges) - len(edge_lines)
    if leftover_edges > 0:
        edge_lines.append(f"... {leftover_edges} more")

    module_lines = [f"`{path}` ({n} lines)" for path, n in modules]

    parts = [
        "# Repo scan",
        "",
        f"Scanned `{root}` at {now}. Report only; nothing here fails a build.",
        "",
        "## Summary",
        "",
        f"- Ruff: {ruff_summary}",
        f"- Vulture: {vulture_summary}",
        f"- Import cycles: {len(cycles)} strongly connected group(s) in `arelis/`.",
        f"- Modules: {len(py_files)} files, {total_lines} lines under `arelis/`.",
        "",
        "## Ruff",
        "",
        ruff_summary,
        "",
        _md_list(ruff_lines).rstrip(),
        "",
        "## Vulture (dead code in `arelis/`)",
        "",
        vulture_summary,
        "",
        _md_list(vulture_lines).rstrip(),
        "",
        "## Import cycles",
        "",
        f"{len(cycles)} group(s) where modules can reach each other.",
        "",
        _md_list(cycle_lines).rstrip(),
        "",
        "## Package edges",
        "",
        "Cross-package imports, counted at the `arelis.<pkg>` layer.",
        "",
        _md_list(edge_lines).rstrip(),
        "",
        "## Biggest modules",
        "",
        _md_list(module_lines).rstrip(),
        "",
    ]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan the checkout and write a short markdown report.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write the report here. Default is stdout.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO,
        help="Repository root to scan.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    _write(args.out, build_report(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
