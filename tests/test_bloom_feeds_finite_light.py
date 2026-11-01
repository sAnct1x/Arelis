"""Her web bloom only sees finite light, so one overflowed texel cannot cut her off at the chest."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

WEB = Path(__file__).resolve().parents[1] / "arelis" / "ui" / "persona_face" / "web"
BASE = "file:///web/index.html"


def _resolve(spec: str, referrer: str, imports: dict[str, str]) -> str:
    """The browser's import-map lookup: exact URL keys first, then bare prefixes."""
    url = urljoin(referrer, spec) if spec.startswith((".", "/")) else None
    table = {(urljoin(BASE, k) if k.startswith((".", "/")) else k): urljoin(BASE, v) for k, v in imports.items()}
    key = url or spec
    if key in table:
        return table[key]
    for prefix in sorted(table, key=len, reverse=True):
        if prefix.endswith("/") and key.startswith(prefix):
            return table[prefix] + key[len(prefix):]
    return key


def test_the_bloom_pass_loads_a_bright_pass_that_drops_nan_and_clamps() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    imports = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    bloom = _resolve("three/addons/postprocessing/UnrealBloomPass.js", BASE, imports)
    bloom_src = (WEB / bloom.removeprefix("file:///web/")).read_text(encoding="utf-8")
    spec = re.search(r"import \{ LuminosityHighPassShader \} from '([^']+)'", bloom_src).group(1)
    bright = _resolve(spec, bloom, imports)
    src = (WEB / bright.removeprefix("file:///web/")).read_text(encoding="utf-8")
    frag = src[src.index("fragmentShader"):]
    assert re.search(r"isnan\(texel\)\)\)\s*texel = vec4\(0\.0\)", frag)
    assert "texel = clamp(texel" in frag
