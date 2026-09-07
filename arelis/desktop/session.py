"""Facade: launch, windows, type, UIA snapshot, screenshot."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from arelis.browser.hold import cooperative_wait
from arelis.desktop.aliases import resolve_app
from arelis.desktop.input import (
    click_xy,
    cursor_pos,
    mouse_moved_since,
    press_hotkey,
    press_key,
    scroll,
    type_text,
)
from arelis.desktop.launch import open_app
from arelis.desktop.pixels import (
    format_screens,
    grab_screen,
    grab_window,
    list_screens,
    looks_like_monitor_token,
    resolve_screen,
)
from arelis.desktop.sanctuary import refuse_secret_type
from arelis.desktop.snapshot import DeskRef, find_ref, read_window, snapshot_window
from arelis.desktop.walls import YOUR_TURN, Wall, label_wall, wall_message
from arelis.desktop.windows import (
    focus_window,
    foreground_title,
    format_windows,
    list_windows,
    match_reader_window,
    match_window,
)
from arelis.paths import display_path


@dataclass
class DeskResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)


class DesktopSession:
    def __init__(self, *, aliases: dict[str, str] | None = None) -> None:
        self.aliases = dict(aliases or {})
        self.refs: dict[str, DeskRef] = {}
        self._hands_origin: tuple[int, int] | None = None

    def _hands(self) -> DeskResult | None:
        if sys.platform != "win32":
            return None
        try:
            if self._hands_origin is None:
                self._hands_origin = cursor_pos()
                return None
            if mouse_moved_since(self._hands_origin):
                self._hands_origin = cursor_pos()
                return DeskResult(
                    ok=False,
                    output=wall_message("hands"),
                    data={"code": YOUR_TURN, "wall": "hands"},
                )
        except Exception:
            return None
        self._hands_origin = cursor_pos()
        return None

    def _label_wall(self, label: str) -> DeskResult | None:
        hit = label_wall(label, window_title=foreground_title())
        if hit is None:
            return None
        return _wall_result(hit)

    async def open(self, target: str) -> DeskResult:
        receipt, err = open_app(target, aliases=self.aliases)
        if err:
            return DeskResult(ok=False, output=err)
        await cooperative_wait(0.35)
        return DeskResult(ok=True, output=receipt or "Opened.", data={"target": target})

    async def windows(self) -> DeskResult:
        rows = list_windows()
        return DeskResult(
            ok=True,
            output=format_windows(rows),
            data={"count": len(rows)},
        )

    async def focus(self, target: str) -> DeskResult:
        key, _ = resolve_app(target, aliases=self.aliases)
        hit = match_window(target) or match_window(key or "")
        if hit is None:
            return DeskResult(ok=False, output=f"No window matching {target!r}.")
        if not focus_window(hit.hwnd):
            return DeskResult(ok=False, output=f"Could not focus {hit.title!r}.")
        return DeskResult(ok=True, output=f"Focused {hit.title}.", data={"title": hit.title})

    async def snapshot(self) -> DeskResult:
        text, refs, err = snapshot_window()
        if err:
            return DeskResult(ok=False, output=err)
        self.refs = refs
        title = foreground_title()
        head = f"window: {title}\n" if title else ""
        return DeskResult(
            ok=True,
            output=head + text,
            data={"title": title, "refs": list(refs)},
        )

    async def read(self) -> DeskResult:
        text = read_window(self.refs)
        title = foreground_title()
        return DeskResult(
            ok=True,
            output=(f"window: {title}\n{text}" if title else text),
            data={"title": title},
        )

    async def type_into(
        self,
        text: str,
        *,
        into: str = "",
        ref: str = "",
    ) -> DeskResult:
        hands = self._hands()
        if hands is not None:
            return hands
        secret = refuse_secret_type(into=into, name="")
        if secret:
            return DeskResult(
                ok=False,
                output=secret,
                data={"code": "SECRET_FIELD", "wall": "password"},
            )
        target = find_ref(self.refs, ref=ref, text=into)
        if target is not None:
            if target.is_password:
                return DeskResult(
                    ok=False,
                    output=refuse_secret_type(is_password=True) or "",
                    data={"code": "SECRET_FIELD", "wall": "password"},
                )
            wall = self._label_wall(target.name)
            if wall is not None:
                return wall
            await click_xy(target.x, target.y)
        try:
            await type_text(text)
        except Exception as exc:
            return DeskResult(ok=False, output=str(exc))
        return DeskResult(ok=True, output="Typed.", data={"label": into or ref})

    async def press(self, key: str) -> DeskResult:
        hands = self._hands()
        if hands is not None:
            return hands
        wall = self._label_wall(key)
        if wall is not None:
            return wall
        err = await press_key(key)
        if err:
            return DeskResult(ok=False, output=err)
        return DeskResult(ok=True, output=f"Pressed {key}.")

    async def hotkey(self, combo: str) -> DeskResult:
        hands = self._hands()
        if hands is not None:
            return hands
        err = await press_hotkey(combo)
        if err:
            return DeskResult(ok=False, output=err)
        return DeskResult(ok=True, output=f"Pressed {combo}.")

    async def click(
        self,
        *,
        ref: str = "",
        text: str = "",
        nth: int = 0,
        x: float | None = None,
        y: float | None = None,
        pixel_ok: bool = False,
    ) -> DeskResult:
        hands = self._hands()
        if hands is not None:
            return hands
        label = text
        if x is not None and y is not None:
            if not pixel_ok:
                from arelis.desktop.pixels import xy_refused

                return DeskResult(ok=False, output=xy_refused(), data={"code": "PIXEL_GATE"})
            wall = self._label_wall(label)
            if wall is not None:
                return wall
            await click_xy(x, y)
            return DeskResult(ok=True, output="Clicked.", data={"label": label})
        if not self.refs:
            snapped = await self.snapshot()
            if not snapped.ok:
                return snapped
        hit = find_ref(self.refs, ref=ref, text=text, nth=nth)
        if hit is None:
            return DeskResult(
                ok=False,
                output="No matching control. Snapshot again, or screenshot then vision.",
                data={"code": YOUR_TURN, "wall": "stuck"},
            )
        wall = self._label_wall(hit.name)
        if wall is not None:
            return wall
        if hit.is_password:
            return DeskResult(
                ok=False,
                output=wall_message("password"),
                data={"code": "SECRET_FIELD", "wall": "password"},
            )
        await click_xy(hit.x, hit.y)
        return DeskResult(ok=True, output=f"Clicked {hit.name}.", data={"label": hit.name})

    async def scroll(self, direction: str = "down", *, amount: int = 3) -> DeskResult:
        hands = self._hands()
        if hands is not None:
            return hands
        await scroll(direction, amount=amount)
        return DeskResult(ok=True, output="Scrolled.")

    async def monitors(self) -> DeskResult:
        rows = list_screens()
        return DeskResult(
            ok=True,
            output=format_screens(rows),
            data={"count": len(rows)},
        )

    async def screenshot(
        self,
        target: str = "",
        *,
        find: str = "",
        reader: Any | None = None,
    ) -> DeskResult:
        raw = (target or "").strip()
        label = "primary monitor"
        try:
            if not raw:
                dest = grab_screen()
            elif looks_like_monitor_token(raw):
                dest = grab_screen(target=raw)
                rows = list_screens()
                hit = resolve_screen(raw, rows)
                if hit is not None:
                    label = f"monitor {hit.index} ({hit.side})"
            else:
                win = match_reader_window(raw)
                if win is not None:
                    dest = grab_window(win.hwnd)
                    label = win.title
                else:
                    return DeskResult(
                        ok=False,
                        output=(
                            f"No window matching {raw!r}. "
                            "Say the title (Kindle, Adobe) or a side "
                            f"(left/right).\nWindows:\n{format_windows(list_windows())}"
                        ),
                    )
        except Exception as exc:
            extra = ""
            if raw and not looks_like_monitor_token(raw):
                extra = f"\nWindows:\n{format_windows(list_windows())}"
            return DeskResult(ok=False, output=f"{exc}{extra}")
        shown = display_path(dest)
        from arelis.look_scratch import note_look_scratch

        note_look_scratch(dest)
        from arelis.desktop.observe import format_observe, look_needles, read_still

        needles = look_needles(find) or look_needles(raw)
        try:
            seen = read_still(dest, needles=needles, ocr=reader)
            read_out = format_observe(seen)
            data = {
                "path": str(dest),
                "target": label,
                "found": list(seen.found),
                "missed": list(seen.missed),
            }
        except Exception as exc:
            read_out = (
                f"Could not read the still ({exc}). "
                "Call vision for a diagram. Do not invent the page."
            )
            data = {"path": str(dest), "target": label}
        return DeskResult(
            ok=True,
            output=(
                f"Screenshot of {label}.\nSaved: {shown}\n{read_out}\n"
                "Answer from that text. Call vision only for a diagram."
            ),
            data=data,
        )

    async def wait(self, seconds: float = 1.0) -> DeskResult:
        cap = max(0.2, min(float(seconds or 1.0), 8.0))
        await cooperative_wait(cap)
        return DeskResult(ok=True, output=f"Waited {cap:.1f}s.")


def _wall_result(hit: Wall) -> DeskResult:
    return DeskResult(
        ok=False,
        output=hit.message,
        data={"code": YOUR_TURN, "wall": hit.kind},
    )
