""""Analyze this: <a physics question>" does not owe the analyze tool."""

from __future__ import annotations

from types import SimpleNamespace

from arelis.core.turn_scratch import named_tools_owed


def _owed(text: str) -> list[str]:
    ctx = SimpleNamespace(
        text=text, typed_text=None, staged_files=(), available_all={"analyze", "calculator"}
    )
    return named_tools_owed(SimpleNamespace(tools_used=[]), ctx)


def test_analyze_is_owed_only_when_the_ask_has_a_file() -> None:
    ask = (
        "Analyze this: if a star's parallax is 0.01 arcsec and apparent mag is 8, "
        "what's its absolute magnitude and likely type?"
    )
    assert _owed(ask) == []
    assert _owed("analyze work/sales.csv and give the mean revenue") == ["analyze"]
