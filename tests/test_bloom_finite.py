"""The bloom chain must never carry NaN or Inf: on d3d11 one bad texel blacked her out below a cut."""

from pathlib import Path

BRIGHT = Path(__file__).resolve().parents[1] / "arelis/ui/persona_q3d/bloom/bright.frag"


def test_bright_pass_feeds_only_finite_light():
    src = BRIGHT.read_text(encoding="utf-8")
    body = src[src.index("void MAIN()") :]
    sample = body.index("texture(INPUT")
    out = body.index("FRAGCOLOR")
    guard = body[sample:out]
    assert "isnan(" in guard, "bright pass must drop NaN before the blur"
    assert "clamp(" in guard and "BRIGHT_MAX" in guard, "bright pass must bound Inf before the blur"
