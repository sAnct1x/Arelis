"""Tabs as places. List index|title|url. Select by index or title substring."""

from __future__ import annotations

from typing import Any


def parse_tab_select(select: int | str | None) -> tuple[int | None, str]:
    """Split ``select`` into an index or a title needle. Not both."""
    if select is None or select == "":
        return None, ""
    if isinstance(select, bool):
        return None, ""
    if isinstance(select, int):
        return int(select), ""
    raw = str(select).strip()
    if not raw:
        return None, ""
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        return int(raw), ""
    return None, raw


def format_tab_line(
    index: int | str,
    title: str,
    url: str,
    *,
    active: bool = False,
) -> str:
    mark = " *" if active else ""
    return f"{index}|{title}|{url}{mark}"


def format_tab_list(
    rows: list[dict[str, Any]],
    *,
    active: int | None = None,
) -> str:
    if not rows:
        return "Tabs: (none)"
    lines = ["Tabs:"]
    for i, row in enumerate(rows):
        try:
            idx = int(row.get("index", i))
        except (TypeError, ValueError):
            idx = i
        title = str(row.get("title") or "")
        url = str(row.get("url") or "")
        is_active = bool(row.get("active"))
        if not is_active and active is not None:
            is_active = idx == int(active)
        lines.append(format_tab_line(idx, title, url, active=is_active))
    return "\n".join(lines)


def pick_tab(
    rows: list[dict[str, Any]],
    *,
    index: int | None = None,
    title: str = "",
) -> tuple[int | None, str]:
    """Return ``(index, error)``. Title is a casefold substring."""
    if not rows:
        return None, "No tabs."
    if index is not None:
        for i, row in enumerate(rows):
            try:
                row_i = int(row.get("index", i))
            except (TypeError, ValueError):
                row_i = i
            if row_i == index:
                return i, ""
        return None, f"No tab index {index}."
    needle = str(title or "").strip().casefold()
    if not needle:
        return None, ""
    hits: list[int] = []
    for i, row in enumerate(rows):
        blob = str(row.get("title") or "").casefold()
        if needle in blob:
            hits.append(i)
    if not hits:
        return None, f"No tab matching {title!r}."
    if len(hits) > 1:
        return None, (
            f"Ambiguous tab {title!r} — {len(hits)} matches. "
            "Pass select= as an index."
        )
    return hits[0], ""
