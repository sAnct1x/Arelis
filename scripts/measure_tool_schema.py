"""How much does Arelis actually tell the model about its own tools?

Companion to `measure_tool_surface_prefill.py`, which measures what the tool
array *costs*. This measures what it *says*. The two together are the evidence
for the schema question: `compact_prompt.py` strips parameter descriptions and
`tool_subset.py:11-31` records the measurement that justified it — a tools
array changing shape per turn invalidates Ollama's prefix cache and costs five
times the steady-state prefill.

That measurement is about a *varying* array. Nobody measured how large a
*constant* one can be, and the array is constant now. So the trade may be
priced wrong, and this script is the before-reading.

    python scripts/measure_tool_schema.py
    python scripts/measure_tool_schema.py --json     # for the ratchet

The registry is built attended and with a router, which is how a real session
builds it. Skip either and `vision` and `camera` go missing.
"""

from __future__ import annotations

import argparse
import json
import statistics
from types import SimpleNamespace
from typing import Any

from arelis.config import load_config
from arelis.tools import build_tool_registry


def _registry() -> Any:
    router = SimpleNamespace(provider=SimpleNamespace(list_models=None))
    return build_tool_registry(load_config(), allow_send=True, attended=True, router=router)


def tool_specs() -> list[dict[str, Any]]:
    """What the model is actually sent, after compact_prompt skinnies it."""
    return list(_registry().ollama_tools())


def authored_parameter_docs() -> tuple[int, int]:
    """(documented, total) on the *source* schemas, before skinnying.

    The gap between this and what the model receives is the whole question.
    The descriptions are not missing — they were written, and
    `compact_prompt.skinny_parameters` strips them on the way out. Closing
    that gap is an edit to one function, not a documentation project.
    """
    registry = _registry()
    total = documented = 0
    for name in registry.names():
        schema = getattr(registry.get(name), "parameters_schema", None) or {}
        props = schema.get("properties") or {}
        total += len(props)
        documented += sum(1 for v in props.values() if (v or {}).get("description"))
    return documented, total


def measure(specs: list[dict[str, Any]]) -> dict[str, Any]:
    blob = json.dumps(specs)
    descriptions: list[int] = []
    total_params = 0
    documented_params = 0
    undocumented: list[tuple[str, int, int]] = []
    enum_free: list[str] = []
    no_required: list[tuple[str, int]] = []

    for spec in specs:
        fn = spec.get("function", spec)
        name = str(fn.get("name") or "")
        descriptions.append(len(fn.get("description") or ""))
        params = fn.get("parameters") or {}
        props = params.get("properties") or {}
        total_params += len(props)
        missing = [k for k, v in props.items() if not (v or {}).get("description")]
        documented_params += len(props) - len(missing)
        if props and missing:
            undocumented.append((name, len(missing), len(props)))
        action = props.get("action") or {}
        if action and not action.get("enum"):
            enum_free.append(name)
        if props and not (params.get("required") or []):
            no_required.append((name, len(props)))

    return {
        "tools": len(specs),
        "schema_chars": len(blob),
        "schema_tokens_approx": len(blob) // 4,
        "description_min": min(descriptions) if descriptions else 0,
        "description_median": int(statistics.median(descriptions)) if descriptions else 0,
        "description_mean": round(statistics.mean(descriptions), 1) if descriptions else 0,
        "description_max": max(descriptions) if descriptions else 0,
        "tools_under_60_chars": sum(1 for d in descriptions if d < 60),
        "total_params": total_params,
        "documented_params": documented_params,
        "undocumented_params": total_params - documented_params,
        "tools_with_undocumented_params": sorted(undocumented, key=lambda x: -x[1]),
        "action_without_enum": sorted(enum_free),
        "tools_with_no_required_field": sorted(no_required),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the tool schema surface.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    stats = measure(tool_specs())
    authored, authored_total = authored_parameter_docs()
    stats["authored_documented_params"] = authored
    stats["authored_total_params"] = authored_total
    if args.json:
        print(json.dumps(stats, indent=2))
        return 0

    print(f"tools                : {stats['tools']}")
    print(
        f"schema size          : {stats['schema_chars']:,} chars "
        f"(~{stats['schema_tokens_approx']:,} tokens)"
    )
    print()
    print(
        f"description length   : min={stats['description_min']} "
        f"median={stats['description_median']} "
        f"mean={stats['description_mean']} "
        f"max={stats['description_max']}"
    )
    print(f"under 60 chars       : {stats['tools_under_60_chars']}/{stats['tools']}")
    print()
    print(
        f"parameters           : {stats['total_params']} total, "
        f"{stats['documented_params']} documented, "
        f"{stats['undocumented_params']} undocumented"
    )
    print(f"authored in source   : {authored}/{authored_total} documented")
    thrown_away = authored - stats["documented_params"]
    if thrown_away > 0:
        print()
        print(
            f"  >> {thrown_away} parameter descriptions exist and are stripped "
            "before the model sees them."
        )
        print("     compact_prompt.skinny_parameters does this to hold the prefix cache. The")
        print("     measurement behind that (tool_subset.py:11-31) was about an array that changes")
        print(
            "     shape per turn. This one does not. Re-price it with "
            "measure_tool_surface_prefill.py."
        )
    if stats["tools_with_undocumented_params"]:
        print()
        print("tools with undocumented parameters (missing/total):")
        for name, missing, total in stats["tools_with_undocumented_params"]:
            print(f"  {name:<22} {missing}/{total}")
    if stats["action_without_enum"]:
        print()
        print("action= with no enum (the model has to guess the verb):")
        for name in stats["action_without_enum"]:
            print(f"  {name}")
    if stats["tools_with_no_required_field"]:
        print()
        print("no required field (every argument optional):")
        for name, count in stats["tools_with_no_required_field"]:
            print(f"  {name:<22} {count} params")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
