"""Padding is a named step, not a sitting's taste.

METRICS already locked control heights because a third tier appeared.
SPACE is the same lock for air. A new 10 / 14 / 18 is how plates drifted.
"""

from __future__ import annotations

import re
from pathlib import Path

from arelis.ui.theme import METRICS, SPACE, control_pad_y, space_allowed, stylesheet

_UI = Path(__file__).resolve().parents[1] / "arelis"
_CALL = re.compile(
    r"\.(?:setContentsMargins|setSpacing|setHorizontalSpacing|"
    r"setVerticalSpacing|addSpacing)\(\s*([^)]*)\)",
    re.S,
)
_INT = re.compile(r"(?<![\w.])(\d+)(?![\w.])")
_CSS_PAD = re.compile(r"padding(?:-[a-z]+)?:\s*([^;]+)")
_CSS_PX = re.compile(r"(\d+)px")

# Computed gutters (orbit park, notify stack) — not a scale choice.
_SKIP_FILES = {
    "theme_tokens.py",
    "theme_qss.py",
}


def test_space_is_six_named_steps() -> None:
    assert SPACE == {
        "hair": 2,
        "micro": 4,
        "gap": 8,
        "inset": 12,
        "plate": 16,
        "stage": 24,
    }
    assert control_pad_y() == (METRICS["row"] - 13 - 2) // 2
    assert control_pad_y() == 6


def test_stylesheet_padding_stays_on_the_scale() -> None:
    """New QSS padding is a SPACE step, a stroke, or the combo arrow lane."""
    allowed = space_allowed() | {METRICS["icon"] - 2}
    offenders: list[str] = []
    for match in _CSS_PAD.finditer(stylesheet()):
        for raw in _CSS_PX.findall(match.group(1)):
            px = int(raw)
            if px not in allowed:
                offenders.append(f"{px}px in {match.group(0).strip()}")
    assert not offenders, "off-scale stylesheet padding:\n  " + "\n  ".join(offenders)


def test_layout_calls_stay_on_the_scale() -> None:
    """Layout air literals must be SPACE (or 0 / 1 / 6)."""
    allowed = space_allowed()
    offenders: list[str] = []
    for path in sorted(_UI.rglob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_UI.parent).as_posix()
        for call in _CALL.finditer(text):
            args = call.group(1)
            if any(name in args for name in ("SPACE", "SHELL", "box(", "control_pad_y")):
                continue
            for raw in _INT.findall(args):
                px = int(raw)
                if px not in allowed:
                    snippet = re.sub(r"\s+", " ", args).strip()
                    offenders.append(f"{rel}: {px} in ({snippet})")
    assert not offenders, "off-scale layout padding:\n  " + "\n  ".join(offenders)
