"""Overnight live-pass tokens must leave the store; user facts stay."""

from __future__ import annotations

from pathlib import Path

from arelis.eval.live_pass_memory import forget_live_pass_facts, is_live_pass_fact
from arelis.memory import MemoryStore

_ROOT = Path(__file__).resolve().parents[1]

_PROBE_FACTS = (
    "Overnight live pass token 271828.",
    "overnight live pass token 271828",
    "Arelis live-pass ran a real tool bounce.",
)

_USER_FACTS = (
    "Alex Example prefers to be called Alex",
    "Alex loves space and is building a space/solar system simulator within Arelis for simulations and tests",
    "User_location: Springfield, IL 62701, US",
)


def test_is_live_pass_fact_matches_probes() -> None:
    for text in _PROBE_FACTS:
        assert is_live_pass_fact(text)


def test_is_live_pass_fact_ignores_user_facts() -> None:
    for text in _USER_FACTS:
        assert not is_live_pass_fact(text)


def test_forget_live_pass_facts_leaves_real_facts(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    for text in _PROBE_FACTS:
        store.add_fact(text, source="explicit", status="active")
    store.add_fact("Alex loves space", source="explicit", status="active")

    forgotten = forget_live_pass_facts(store)
    remaining = [row["text"] for row in store.list_facts(status="active")]

    assert forgotten == 3
    assert remaining == ["Alex loves space"]
    store.close()


def test_live_pass_scripts_bind_store() -> None:
    for name in ("live_full_pass.py", "live_feature_pass.py"):
        src = (_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "bind_live_pass_store" in src
