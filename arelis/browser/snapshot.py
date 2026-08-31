"""Rank visible controls and match a click / field by the words on the page."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

SNAPSHOT_LIMIT = 40
SNAPSHOT_SCAN = 160

# Keep in sync with SNAPSHOT_STAMP_JS.
SNAPSHOT_SELECTOR = (
    'a[href], button, input, textarea, select, '
    '[role="button"], [role="link"], [role="textbox"], [contenteditable="true"]'
)

# Shared collect: light DOM + one shadow root + same-origin iframes.
# Keep stamp in the same walk so refs still match.
_SKIP_NAV_RE = (
    r"^(go to channel|subscribe|sign in|log in|home|shorts|"
    r"library|sponsored|download)\b"
)
_SKIP_HREF_RE = (
    r"(?:youtube\.com|youtu\.be)/(?:channel/|@|c/|user/|"
    r"feed/|account|results)|pagead|googleadservices|"
    r"ptracking|doubleclick"
)
_SNAPSHOT_WALK_JS = f"""
  const sel = {SNAPSHOT_SELECTOR!r};
  const scan = {SNAPSHOT_SCAN};
  const collectFrom = (root, into) => {{
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll(sel).forEach((el) => into.push(el));
    root.querySelectorAll('*').forEach((el) => {{
      const shadow = el.shadowRoot;
      if (shadow && shadow.querySelectorAll) {{
        shadow.querySelectorAll(sel).forEach((child) => into.push(child));
      }}
    }});
  }};
  const collectAll = () => {{
    const nodes = [];
    collectFrom(document, nodes);
    document.querySelectorAll('iframe').forEach((frame) => {{
      try {{
        const doc = frame.contentDocument;
        if (doc) collectFrom(doc, nodes);
      }} catch (e) {{}}
    }});
    return nodes;
  }};
  const regionOf = (el) => {{
    const host = el.closest(
      'header, nav, footer, aside, main, [role="banner"], '
      + '[role="navigation"], [role="contentinfo"], '
      + '[role="complementary"], [role="main"]'
    );
    if (!host) return 'main';
    const t = (host.tagName || '').toLowerCase();
    const role = (host.getAttribute('role') || '').toLowerCase();
    if (t === 'header' || role === 'banner') return 'header';
    if (t === 'nav' || role === 'navigation') return 'nav';
    if (t === 'footer' || role === 'contentinfo') return 'footer';
    if (t === 'aside' || role === 'complementary') return 'aside';
    return 'main';
  }};
  const isResultLike = (el) => {{
    const region = regionOf(el);
    if (region === 'nav' || region === 'footer' || region === 'header') return false;
    const tag = (el.tagName || '').toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const href = el.href || '';
    const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
    if (tag !== 'a' && role !== 'link') return false;
    if (!href.startsWith('http')) return false;
    if (text.length < 4) return false;
    if (new RegExp({_SKIP_NAV_RE!r}, 'i').test(text)) {{
      return false;
    }}
    if (/\\bsponsored\\b/i.test(text)) return false;
    if (new RegExp({_SKIP_HREF_RE!r}, 'i').test(href)) {{
      return false;
    }}
    const low = href.toLowerCase();
    if ((low.includes('youtube.com') || low.includes('youtu.be'))
        && !low.includes('/watch') && !low.includes('/shorts/')) {{
      return false;
    }}
    return true;
  }};
  const pick = (focus) => {{
    const all = collectAll();
    if ((focus || '') === 'results') {{
      const results = [];
      const rest = [];
      all.forEach((el) => (isResultLike(el) ? results : rest).push(el));
      return results.concat(rest).slice(0, scan);
    }}
    return all.slice(0, scan);
  }};
"""

SNAPSHOT_COLLECT_JS = f"""(focus) => {{
{_SNAPSHOT_WALK_JS}
  const heading = ((document.querySelector('h1') || {{}}).innerText || '')
    .trim().slice(0, 120);
  const nodes = pick(focus || '');
  const vh = window.innerHeight || 800;
  const vw = window.innerWidth || 1200;
  const visibleOf = (el) => {{
    try {{
      const st = window.getComputedStyle(el);
      if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) {{
        return false;
      }}
    }} catch (e) {{
      return false;
    }}
    if (el.getAttribute('aria-hidden') === 'true') return false;
    const r = el.getBoundingClientRect();
    return r.width >= 2 && r.height >= 2;
  }};
  return {{
    heading: heading,
    nodes: nodes.map((el, i) => {{
      const r = el.getBoundingClientRect();
      const text = (el.innerText || el.value || el.getAttribute('aria-label')
        || el.getAttribute('placeholder') || '').trim().slice(0, 80);
      return {{
        index: i,
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role') || '',
        type: (el.getAttribute('type') || '').toLowerCase(),
        name: el.getAttribute('name') || '',
        text: text,
        href: el.href || '',
        autocomplete: el.getAttribute('autocomplete') || '',
        visible: visibleOf(el),
        in_view: r.top < vh && r.bottom > 0 && r.left < vw && r.right > 0,
        region: regionOf(el),
      }};
    }}),
  }};
}}"""

SNAPSHOT_STAMP_JS = f"""(payload) => {{
{_SNAPSHOT_WALK_JS}
  const focus = (payload && payload.focus) || '';
  const pairs = (payload && payload.pairs) || [];
  const nodes = pick(focus);
  document.querySelectorAll('[data-arelis-ref]').forEach((el) => {{
    el.removeAttribute('data-arelis-ref');
  }});
  try {{
    document.querySelectorAll('iframe').forEach((frame) => {{
      const doc = frame.contentDocument;
      if (doc) doc.querySelectorAll('[data-arelis-ref]').forEach((el) => {{
        el.removeAttribute('data-arelis-ref');
      }});
    }});
  }} catch (e) {{}}
  for (const pair of pairs) {{
    const el = nodes[pair.index];
    if (el) el.setAttribute('data-arelis-ref', pair.ref);
  }}
  return true;
}}"""


def _node_label(node: dict[str, Any]) -> str:
    return " ".join(str(node.get("text") or node.get("name") or "").split())


def score_snapshot_node(node: dict[str, Any]) -> int:
    """Higher is a better click target. Footer chrome and empty nodes lose."""
    if not node.get("visible", True):
        return -100
    text = _node_label(node)
    href = str(node.get("href") or "")
    typ = str(node.get("type") or "")
    if not text and not href and typ not in {"search", "text", "email", "url"}:
        return -50
    score = 0
    if node.get("in_view", True):
        score += 8
    region = str(node.get("region") or "main")
    if region == "header":
        score += 6
    elif region == "main":
        score += 5
    elif region == "nav":
        score += 1
    elif region == "footer":
        score -= 8
    if text:
        score += min(4, len(text) // 8 + 1)
    if len(text) > 56:
        score -= 3
    tag = str(node.get("tag") or "")
    role = str(node.get("role") or "")
    if tag in {"button", "input", "select", "textarea"} or role in {
        "button",
        "textbox",
    }:
        score += 2
    if typ in {"search", "text", "email"}:
        score += 2
    return score


def rank_snapshot_nodes(
    nodes: Iterable[dict[str, Any]],
    *,
    limit: int = SNAPSHOT_LIMIT,
) -> list[dict[str, Any]]:
    """Keep the controls a person would actually click. Refs are e1… in rank order."""
    scored: list[tuple[int, int, dict[str, Any]]] = []
    for i, raw in enumerate(nodes):
        node = dict(raw or {})
        if "index" not in node:
            node["index"] = i
        score = score_snapshot_node(node)
        if score < 0:
            continue
        scored.append((score, int(node["index"]), node))
    scored.sort(key=lambda row: (-row[0], row[1]))
    out: list[dict[str, Any]] = []
    for rank, (score, _index, node) in enumerate(scored[: max(1, limit)], start=1):
        item = dict(node)
        item["ref"] = f"e{rank}"
        item["score"] = score
        out.append(item)
    return out


def match_click_targets(elements: Any, text: str) -> list[Any]:
    """Prefer an exact visible label, then a short contains-match."""
    needle = " ".join((text or "").split()).lower()
    if not needle:
        return []
    if isinstance(elements, dict):
        items = list(elements.values())
    else:
        items = list(elements or [])
    exact: list[Any] = []
    prefix: list[Any] = []
    contain: list[Any] = []
    for info in items:
        label = " ".join(
            str(getattr(info, "text", "") or getattr(info, "name", "") or "").split()
        ).lower()
        if not label:
            continue
        if label == needle:
            exact.append(info)
        elif label.startswith(needle) or (
            needle.startswith(label) and len(label) >= 4
        ):
            prefix.append(info)
        elif needle in label and len(label) < 48:
            contain.append(info)
    return exact or prefix or contain


_ORDINAL_WORD = {
    "first": 1,
    "1st": 1,
    "1": 1,
    "second": 2,
    "2nd": 2,
    "2": 2,
    "third": 3,
    "3rd": 3,
    "3": 3,
    "fourth": 4,
    "4th": 4,
    "4": 4,
    "fifth": 5,
    "5th": 5,
    "5": 5,
}
_ORDINAL_PHRASE = re.compile(
    r"(?i)^(?:the\s+)?(?P<n>first|1st|second|2nd|third|3rd|fourth|4th|"
    r"fifth|5th|[1-5])(?:\s+(?:one|result|video|link|hit|item))?$"
)


def parse_ordinal(text: str) -> int | None:
    """1-based index when the ask is 'first' / 'the first video', else None."""
    raw = " ".join((text or "").split()).lower()
    if not raw:
        return None
    if raw in _ORDINAL_WORD:
        return _ORDINAL_WORD[raw]
    hit = _ORDINAL_PHRASE.match(raw)
    if hit:
        return _ORDINAL_WORD.get(hit.group("n"))
    return None


def _as_list(elements: Any) -> list[Any]:
    if isinstance(elements, dict):
        return list(elements.values())
    return list(elements or [])


def info_label(info: Any) -> str:
    return " ".join(
        str(getattr(info, "text", "") or getattr(info, "name", "") or "").split()
    )


def is_typeable(info: Any) -> bool:
    secret = getattr(info, "is_secret_field", None)
    if callable(secret) and secret():
        return False
    tag = str(getattr(info, "tag", "") or "").lower()
    role = str(getattr(info, "role", "") or "").lower()
    typ = str(getattr(info, "type", "") or "").lower()
    if typ in {"password", "hidden", "submit", "button", "checkbox", "radio", "file"}:
        return False
    return tag in {"input", "textarea"} or role == "textbox" or typ in {
        "search",
        "text",
        "email",
        "url",
    }


def is_select(info: Any) -> bool:
    tag = str(getattr(info, "tag", "") or "").lower()
    role = str(getattr(info, "role", "") or "").lower()
    return tag == "select" or role == "combobox"


_SKIP_RESULT_LABEL = re.compile(
    r"(?i)^(go to channel|subscribe|sign in|log in|home|shorts|library|"
    r"sponsored|download|watch)\b"
)
_SKIP_RESULT_HREF = re.compile(
    r"(?i)(?:youtube\.com|youtu\.be)/(?:channel/|@|c/|user/|feed/|account|"
    r"results|hashtag)|pagead|googleadservices|/ptracking|doubleclick"
)


def href_is_result_page(href: str, text: str = "") -> bool:
    """True for a watch / article link — not a channel chip, ad, or Sign in."""
    if not (href or "").startswith("http"):
        return False
    if _SKIP_RESULT_HREF.search(href or ""):
        return False
    if _SKIP_RESULT_LABEL.search((text or "").strip()):
        return False
    if re.search(r"(?i)\bsponsored\b", text or ""):
        return False
    low = (href or "").lower()
    if "youtube.com" in low or "youtu.be" in low:
        if "/watch" not in low and "/shorts/" not in low:
            return False
    return True


def prefer_result_nodes(
    nodes: Iterable[dict[str, Any]],
    *,
    limit: int = SNAPSHOT_SCAN,
) -> list[dict[str, Any]]:
    """Put result-region links first so header chips do not eat the scan budget."""
    results: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for raw in nodes:
        node = dict(raw or {})
        region = str(node.get("region") or "main").lower()
        tag = str(node.get("tag") or "").lower()
        role = str(node.get("role") or "").lower()
        href = str(node.get("href") or "")
        text = _node_label(node)
        result = (
            region not in {"nav", "footer", "header"}
            and (tag == "a" or role == "link")
            and href_is_result_page(href, text)
            and len(text) >= 4
        )
        (results if result else rest).append(node)
    return (results + rest)[: max(1, limit)]


def is_result_like(info: Any) -> bool:
    region = str(getattr(info, "region", "") or "main").lower()
    if region in {"nav", "footer", "header"}:
        return False
    tag = str(getattr(info, "tag", "") or "").lower()
    role = str(getattr(info, "role", "") or "").lower()
    href = str(getattr(info, "href", "") or "")
    text = info_label(info)
    if tag != "a" and role != "link":
        return False
    if len(text) < 4:
        return False
    return href_is_result_page(href, text)


def match_type_targets(elements: Any, into: str) -> list[Any]:
    """Search / text fields. Empty into prefers the one search box."""
    items = [info for info in _as_list(elements) if is_typeable(info)]
    needle = " ".join((into or "").split()).lower()
    if not needle:
        search = [
            info
            for info in items
            if str(getattr(info, "type", "") or "").lower() == "search"
            or "search" in str(getattr(info, "name", "") or "").lower()
            or "search" in info_label(info).lower()
        ]
        if len(search) == 1:
            return search
        if len(items) == 1:
            return items
        return search or items
    labeled = match_click_targets(items, needle)
    if labeled:
        return labeled
    return [
        info
        for info in items
        if needle in str(getattr(info, "name", "") or "").lower()
    ]


def format_result_lines(elements: Any, *, max_n: int = 12) -> str:
    """Short result list for search — not the full control phone book."""
    lines = ["results:"]
    n = 0
    for info in _as_list(elements):
        if not is_result_like(info):
            continue
        n += 1
        line = getattr(info, "line", None)
        lines.append(line() if callable(line) else info_label(info))
        if n >= max_n:
            break
    if n == 0:
        return ""
    return "\n".join(lines)


def resolve_target_ref(
    elements: Any,
    *,
    text: str = "",
    nth: int = 0,
    kind: str = "click",
) -> tuple[str | None, str | None, list[Any]]:
    """Return (ref, error, matches). nth is 1-based."""
    items = _as_list(elements)
    needle = " ".join((text or "").split())
    ordinal = parse_ordinal(needle) if needle else None
    use_nth = int(nth) if int(nth or 0) > 0 else (ordinal or 0)
    if kind == "type":
        matches = match_type_targets(elements, needle if not ordinal else "")
    elif kind == "select":
        pool = [info for info in items if is_select(info)]
        matches = match_click_targets(pool, needle) if needle else list(pool)
        if not matches and needle:
            matches = [
                info
                for info in pool
                if needle.lower() in str(getattr(info, "name", "") or "").lower()
            ]
    elif kind == "result" or (use_nth and (not needle or ordinal)):
        matches = [info for info in items if is_result_like(info)]
        if needle and not ordinal:
            labeled = match_click_targets(matches, needle)
            if labeled:
                matches = labeled
    else:
        matches = match_click_targets(elements, needle) if needle else []

    if use_nth:
        if use_nth > len(matches) or use_nth < 1:
            return None, f"No #{use_nth} match on this tab.", matches
        return str(matches[use_nth - 1].ref), None, matches
    if len(matches) == 1:
        return str(matches[0].ref), None, matches
    if not matches:
        return None, (
            f"No visible control matching {needle or kind!r}. "
            "Call snapshot and use a ref."
        ), matches
    return None, f"Several matches for {needle or kind!r}. Pick one by ref.", matches
