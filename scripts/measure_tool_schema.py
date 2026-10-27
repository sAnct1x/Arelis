"""How much does Arelis actually tell the model about its own tools?

Companion to `measure_tool_surface_prefill.py`, which measures what the tool
array *costs*. This measures what it *says*. The two together are the evidence
for the schema question: `compact_prompt.py` strips parameter descriptions and
`tool_subset.py:11-31` records the measurement that justified it — a tools
array changing shape per turn invalidates the model server's prefix cache and costs five
times the steady-state prefill.

That measurement is about a *varying* array. Nobody measured how large a
*constant* one can be, and the array is constant now. So the trade may be
priced wrong, and this script is the before-reading.

    python scripts/measure_tool_schema.py
    python scripts/measure_tool_schema.py --json     # for the ratchet

The registry is built attended and with a router, which is how a real session
builds it. Vision and camera also need the VL model. Desktop needs Windows.
`--profile worst` turns every optional tool on. `--profile mac` keeps vision
and leaves desktop out.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from arelis.config import load_config
from arelis.mail import MailAccount
from arelis.sms_android import SmsGateAccount
from arelis.tools import build_tool_registry
from arelis.tools.groups import CORE, GROUPS

# 0.33 s per 100 tokens, cold prefill on the card the budget was measured on.
# Warm reuse of this block is 0. The CI ceiling was 6,536 Qwen tokens.
# +500 tokens is 1.65 s, recorded as +1.7 s on a cold turn only.
COLD_SECONDS_PER_100_TOKENS = 0.33
CAP_RAISE_TOKENS = 500
CAP_RAISE_COLD_SECONDS = 1.7
# Ratcheted down after the surface shrank (issue 291). On main 03a92aa:
# default 6,171 here, about 6,391 with Windows desktop; worst 7,216.
SCHEMA_TOKEN_CAP = {
    "default": 6_600,
    "worst": 7_450,
}

_EXAMPLE_MAIL = MailAccount(address="person@example.com", password="example-password")
_EXAMPLE_SMS = SmsGateAccount(
    base_url="http://127.0.0.1:9",
    username="user",
    password="secret",
)


def _router() -> SimpleNamespace:
    return SimpleNamespace(provider=SimpleNamespace(list_models=None))


def registry_for_profile(profile: str) -> Any:
    """Build one session registry for a named profile.

    default: this machine, no VL model, no mail, no SMS. Desktop follows
    the host (Windows only).
    worst: every optional tool on, including Windows desktop.
    mac: VL model installed, desktop off.
    """
    config = load_config()
    if profile == "default":
        config["_vl_model_installed"] = False
    elif profile == "worst":
        config["_vl_model_installed"] = True
        config["_session_platform"] = "win32"
    elif profile == "mac":
        config["_vl_model_installed"] = True
        config["_session_platform"] = "darwin"
    else:
        raise ValueError(f"unknown profile {profile}")

    import arelis.tools as tools_mod

    saved_mail = tools_mod.load_account
    saved_sms = tools_mod.load_sms_account
    try:
        if profile == "worst":
            tools_mod.load_account = lambda path=None: _EXAMPLE_MAIL
            tools_mod.load_sms_account = lambda path=None: _EXAMPLE_SMS
        return build_tool_registry(
            config, allow_send=True, attended=True, router=_router()
        )
    finally:
        tools_mod.load_account = saved_mail
        tools_mod.load_sms_account = saved_sms


def _registry() -> Any:
    return registry_for_profile("default")


def tool_specs(registry: Any | None = None) -> list[dict[str, Any]]:
    """What the model is actually sent, after compact_prompt skinnies it."""
    reg = _registry() if registry is None else registry
    return list(reg.chat_tools())


def tokenizer_json_path() -> Path | None:
    """Real Qwen tokenizer, when somebody has dropped it next to the repo."""
    env = os.environ.get("ARELIS_TOKENIZER_JSON", "").strip()
    root = Path(__file__).resolve().parents[1]
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            root / "schema-budget-data" / "tokenizer.json",
            root / "tool-descriptions-data" / "tok" / "tokenizer.json",
            root / "tokenizer.json",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


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


# Qwen3.5-9B hello-profile tool block at 738c021: 23,570 chars, 7,132 tokens.
# chars/4 undercounted that JSON by about 20%. No tokenizer at runtime.
_QWEN_BLOCK_CHARS = 23_570
_QWEN_BLOCK_TOKENS = 7_132


def schema_token_estimate(n_chars: int) -> int:
    """Qwen3.5-9B tokens for schema JSON, from the fixed chars/token ratio."""
    return (n_chars * _QWEN_BLOCK_TOKENS + _QWEN_BLOCK_CHARS // 2) // _QWEN_BLOCK_CHARS


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
        "schema_tokens_approx": schema_token_estimate(len(blob)),
        "schema_tokens_chars4": len(blob) // 4,
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


_TOKENIZER: Any | None = None
_TOKENIZER_TRIED = False


def _qwen_tokenizer() -> Any | None:
    """Real Qwen tokenizer when tokenizers and tokenizer.json are both present."""
    global _TOKENIZER, _TOKENIZER_TRIED
    if _TOKENIZER_TRIED:
        return _TOKENIZER
    _TOKENIZER_TRIED = True
    path = tokenizer_json_path()
    if path is None:
        return None
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None
    _TOKENIZER = Tokenizer.from_file(str(path))
    return _TOKENIZER


def group_token_report(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Token totals for core, each group, and the full loaded list.

    Counts use schema_token_estimate. When a real tokenizer is available,
    each row also carries schema_tokens_real. Tools not loaded in this
    profile are left out of that group's row.
    """
    by_name = {
        str((spec.get("function") or spec).get("name") or ""): spec for spec in specs
    }
    tokenizer = _qwen_tokenizer()

    def row(label: str, chosen: list[dict[str, Any]]) -> dict[str, Any]:
        blob = json.dumps(chosen)
        item: dict[str, Any] = {
            "group": label,
            "tools": len(chosen),
            "schema_chars": len(blob),
            "schema_tokens_approx": schema_token_estimate(len(blob)),
        }
        if tokenizer is not None:
            item["schema_tokens_real"] = len(tokenizer.encode(blob).ids)
        return item

    rows = [row("core", [by_name[name] for name in CORE if name in by_name])]
    for name, tools in GROUPS.items():
        rows.append(row(name, [by_name[tool] for tool in tools if tool in by_name]))
    rows.append(row("all_loaded", list(specs)))
    return rows


def _print_group_tokens(stats: dict[str, Any]) -> None:
    rows = stats.get("group_tokens") or []
    if not rows:
        return
    real = "schema_tokens_real" in rows[0]
    print()
    print(f"group tokens, {stats['profile']} (loaded tools only):")
    for row in rows:
        label = "all loaded" if row["group"] == "all_loaded" else str(row["group"])
        line = (
            f"  {label:<12} tools {row['tools']:>3}   "
            f"~{row['schema_tokens_approx']:,} Qwen tokens"
        )
        if real:
            line += f"   real {row['schema_tokens_real']:,}"
        print(line)


def _print_profile(name: str, stats: dict[str, Any]) -> None:
    cap = SCHEMA_TOKEN_CAP.get(name)
    cap_bit = f"  cap {cap:,}" if cap is not None else ""
    print(
        f"{name:<8} tools {stats['tools']:>3}   "
        f"{stats['schema_chars']:,} chars   "
        f"~{stats['schema_tokens_approx']:,} Qwen tokens"
        f"{cap_bit}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure the tool schema surface.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--profile",
        choices=("default", "worst", "mac", "all"),
        default="all",
        help="which session profile to measure (default: default and worst)",
    )
    args = parser.parse_args()

    profiles = ("default", "worst") if args.profile == "all" else (args.profile,)
    rows = []
    for name in profiles:
        registry = registry_for_profile(name)
        specs = tool_specs(registry)
        stats = measure(specs)
        stats["profile"] = name
        if name == "default":
            authored, authored_total = authored_parameter_docs()
            stats["authored_documented_params"] = authored
            stats["authored_total_params"] = authored_total
        stats["group_tokens"] = group_token_report(specs)
        rows.append(stats)
    if args.json:
        payload: Any = rows[0] if len(rows) == 1 else rows
        print(json.dumps(payload, indent=2))
        return 0

    if args.profile == "all":
        print(
            "CI ceiling "
            f"{SCHEMA_TOKEN_CAP['default']:,} Qwen tokens "
            f"(+{CAP_RAISE_TOKENS}, +{CAP_RAISE_COLD_SECONDS}s cold, 0 warm). "
            f"Worst-case ceiling {SCHEMA_TOKEN_CAP['worst']:,}."
        )
        for stats in rows:
            _print_profile(str(stats["profile"]), stats)
        for stats in rows:
            _print_group_tokens(stats)
        return 0

    stats = rows[0]
    if "authored_documented_params" not in stats:
        authored, authored_total = authored_parameter_docs()
        stats["authored_documented_params"] = authored
        stats["authored_total_params"] = authored_total
    else:
        authored = stats["authored_documented_params"]
        authored_total = stats["authored_total_params"]
    print(f"profile              : {stats['profile']}")
    print(f"tools                : {stats['tools']}")
    print(
        f"schema size          : {stats['schema_chars']:,} chars "
        f"(~{stats['schema_tokens_approx']:,} Qwen tokens, "
        f"{stats['schema_tokens_chars4']:,} at chars/4)"
    )
    print()
    print(
        f"description length   : min={stats['description_min']} "
        f"median={stats['description_median']} "
        f"mean={stats['description_mean']} "
        f"max={stats['description_max']}"
    )
    print(
        f"under 60 chars       : {stats['tools_under_60_chars']}/{stats['tools']}"
    )
    print()
    print(
        f"parameters           : {stats['total_params']} total, "
        f"{stats['documented_params']} documented, "
        f"{stats['undocumented_params']} undocumented"
    )
    print(
        f"authored in source   : {authored}/{authored_total} documented"
    )
    thrown_away = authored - stats["documented_params"]
    if thrown_away > 0:
        print()
        print(
            f"  >> {thrown_away} parameter descriptions exist and are stripped "
            "before the model sees them."
        )
        print(
            "     compact_prompt.skinny_parameters does this to hold the prefix "
            "cache. The"
        )
        print(
            "     measurement behind that (tool_subset.py:11-31) was about an "
            "array that changes"
        )
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
    _print_group_tokens(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
