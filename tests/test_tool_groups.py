"""The tool group table covers every registered tool exactly once.

Nothing reads the table to build a prompt yet. These tests only pin the
data: membership, a core schema budget, plain menu text, and a golden
copy of the worst-profile tools list taken before any loader exists.
"""

from __future__ import annotations

import json
from pathlib import Path

_PROFILES = ("default", "worst", "mac")
_GOLDEN = Path(__file__).parent / "fixtures" / "worst_profile_tools.json"
_DASHES = ("\u2013", "\u2014")


def test_every_registered_tool_has_exactly_one_group() -> None:
    from arelis.tools.groups import CORE, GROUPS, group_of, tools_in
    from scripts.measure_tool_schema import registry_for_profile, tool_specs

    assert tools_in("core") == tuple(CORE)
    owners: dict[str, str] = {}
    for name in CORE:
        assert name not in owners, name
        owners[name] = "core"
    for group, names in GROUPS.items():
        assert tools_in(group) == tuple(names)
        for name in names:
            assert name not in owners, (name, owners[name], group)
            owners[name] = group

    registered: set[str] = set()
    for profile in _PROFILES:
        specs = tool_specs(registry_for_profile(profile))
        names = {spec["function"]["name"] for spec in specs}
        registered |= names
        for name in sorted(names):
            found = group_of(name)
            assert name in owners and found == owners[name], (profile, name, found)

    extras = sorted(set(owners) - registered)
    assert extras == [], extras


def test_menu_and_keywords_are_plain() -> None:
    from arelis.tools.groups import GROUPS, KEYWORDS, MENU

    assert set(MENU) == set(GROUPS)
    assert set(KEYWORDS) == set(GROUPS)
    for group in GROUPS:
        phrase = MENU[group]
        words = KEYWORDS[group]
        assert phrase.strip()
        assert phrase == phrase.lower(), phrase
        assert not any(mark in phrase for mark in _DASHES), phrase
        assert words
        for word in words:
            assert word.strip()
            assert word == word.lower(), (group, word)
            assert not any(mark in word for mark in _DASHES), (group, word)


def test_flag_free_schema_unchanged() -> None:
    from arelis.tools.groups import GROUPS
    from scripts.measure_tool_schema import registry_for_profile, tool_specs

    assert GROUPS
    actual = json.dumps(tool_specs(registry_for_profile("worst")), indent=2) + "\n"
    assert actual == _GOLDEN.read_text(encoding="utf-8")
