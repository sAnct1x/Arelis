"""Open and drive the user's real browser (no credential entry)."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from arelis.browser.aliases import resolve_target
from arelis.browser.session import BrowserSession
from arelis.core.preflight import rewrite_browser_action
from arelis.paths import display_path as _project_rel
from arelis.paths import outputs_dir
from arelis.tools.base import ToolResult

log = logging.getLogger(__name__)

_ACTIONS = (
    "open",
    "navigate",
    "snapshot",
    "read",
    "maps",
    "search",
    "reserve",
    "click",
    "type",
    "tabs",
    "relaunch",
    "screenshot",
    "scroll",
    "press",
    "select",
    "wait",
    "back",
    "forward",
    "reload",
    "find",
    "download",
    "upload",
    "pdf",
    "hover",
    "dblclick",
    "right_click",
    "drag",
    "watch",
)


class BrowserTool:
    name = "browser"
    description = (
        "Drive Arelis' own Chrome window (data/browser-profile/), not the "
        "daily browser. You watch it. Prefer this when they ask to pull up / "
        "open / go to a site or click around a page. Use search/scrape when "
        "YOU need to read the web without opening a window. Never type "
        "passwords or OTP codes. If a captcha, sign-in, or Book/Pay/Order "
        "screen appears, stop and tell the user it is their turn — do not "
        "solve captchas or click Pay. "
        "Actions: open (alias or https URL in her window), navigate (same "
        "window), snapshot (visible click targets, ranked — not footer "
        "chrome), read (compact text of the tab she is on — not scrape), "
        "maps (directions in her window + a phone link), "
        "search (Google / YouTube / Amazon results in her window), "
        "reserve (OpenTable / Resy / Google — fills party/date/time; you click Book), "
        "click(ref) or click(text='Sign in') or click(nth=1) for the first "
        "result (glows first), type(text=…, into='search') or type(ref), "
        "type(who=Mom, into=email|phone|name|work_phone) fills that "
        "contacts.yaml field (no street address), "
        "scroll, press(key), select(ref or into, text=option), "
        "wait(seconds) or wait(url=/home) / wait(text=…) / wait(heading=…) "
        "(poll the tab, cap 8s, then snapshot), "
        "back, forward, reload, find(text) lists matches, "
        "tabs (no args lists index|title|url; select=Gmail or select=0; "
        "tab=new|close — close is the current tab only), "
        "screenshot (PNG under outputs/images/ — then vision to describe), "
        "download (ref of the save link → outputs/downloads/), "
        "upload (path under workspace roots or outputs/, confirm; "
        "type=file is refused on type), "
        "pdf (this tab → outputs/documents/), "
        "hover / dblclick / right_click / drag on a snapshot ref "
        "(glow beat; walls still apply). x,y only after screenshot "
        "then vision this turn — not computer-use by default. "
        "watch (poll title/url/text while Arelis is open; Drive says "
        "Watching; Stop cancels; notify on hit), "
        "relaunch (restarts HER window only; optional url opens after). "
        "You plan the drive: search, click the first result, read, go back. "
        "Prefer open when they only asked to pull up a site. Prefer read "
        "when they ask what is on this tab/page. Prefer maps when they ask "
        "for directions — opens Maps in her window and returns a phone link. "
        "Do not scrape for directions. Prefer search when they ask to look "
        "something up on YouTube / Google / Amazon in her window. Add to "
        "cart is fine; stop before Checkout / Pay / Buy now. "
        "Sign in on the current page: click(text='Sign in') or snapshot then "
        "click by ref. There is no goto_sign_in action. Username they "
        "provide can be typed into a non-secret field; never type passwords "
        "or OTP. Prefer reserve when they ask to book a table. That opens "
        "OpenTable (or Resy / Google) with party, date, and time in the URL. "
        "Type remaining non-secret fields. Never click Book / Reserve / "
        "Confirm reservation — that is their turn. "
        "Optional browser=default|chrome|edge|firefox; "
        "private=true for Firefox private; full_page=true for screenshot."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS),
                "description": (
                    "open / navigate / snapshot / read / maps / search / "
                    "reserve / click / type / scroll / press / select / wait / "
                    "back / forward / reload / find / tabs / screenshot / "
                    "download / upload / pdf / hover / dblclick / "
                    "right_click / drag / watch / relaunch"
                ),
            },
            "url": {
                "type": "string",
                "description": (
                    "https URL or alias for open/navigate/relaunch "
                    "(youtube, gmail, …). On relaunch, opens after restart."
                ),
            },
            "target": {
                "type": "string",
                "description": "Alias for url (open/navigate/relaunch)",
            },
            "ref": {
                "type": "string",
                "description": "Element ref from snapshot (e.g. e3) for click/type",
            },
            "text": {
                "type": "string",
                "description": (
                    "click/find: visible label (e.g. Sign in). "
                    "type: the string to type. select: the option to pick."
                ),
            },
            "into": {
                "type": "string",
                "description": (
                    "type/select: field label (search, email, party). "
                    "Empty type prefers the search box. "
                    "With who=: name / phone / email / work_phone."
                ),
            },
            "who": {
                "type": "string",
                "description": (
                    "type: contact in contacts.yaml. Fills name, phone, "
                    "email, or work_phone into that field. No street address."
                ),
            },
            "heading": {
                "type": "string",
                "description": "wait: visible h1 / title needle to poll for",
            },
            "nth": {
                "type": "integer",
                "description": "click/find: 1-based result (1 = first)",
            },
            "select": {
                "description": (
                    "tabs: 0-based index or title substring. "
                    "Close is the current tab only — not a title."
                ),
            },
            "tab": {
                "type": "string",
                "description": "tabs: new / close (optional url on new)",
            },
            "focus": {
                "type": "string",
                "description": "snapshot: results = short result links only",
            },
            "browser": {
                "type": "string",
                "enum": ["default", "chrome", "edge", "firefox"],
                "description": "Which browser; default = system default",
            },
            "private": {
                "type": "boolean",
                "description": "Firefox private / ephemeral profile only",
            },
            "full_page": {
                "type": "boolean",
                "description": "For screenshot: capture full scrollable page",
            },
            "direction": {
                "type": "string",
                "description": "scroll: up / down / left / right / page",
            },
            "amount": {
                "type": "integer",
                "description": "scroll pixels (default 600)",
            },
            "key": {
                "type": "string",
                "description": "press: Enter, Escape, Tab, arrows, Space",
            },
            "seconds": {
                "type": "number",
                "description": (
                    "wait: cap 0.2-8s. Default 1s to sleep, 8s when "
                    "url/text/heading is set"
                ),
            },
            "destination": {
                "type": "string",
                "description": "maps: place or address to route to",
            },
            "origin": {
                "type": "string",
                "description": "maps: optional start (home, a place). Phone link omits this.",
            },
            "mode": {
                "type": "string",
                "description": "maps: driving / walking / transit / bicycling",
            },
            "query": {
                "type": "string",
                "description": "search: what to look up on Google / YouTube / Amazon",
            },
            "site": {
                "type": "string",
                "description": (
                    "search: google / youtube / amazon; "
                    "reserve: opentable (default) / resy / google"
                ),
            },
            "place": {
                "type": "string",
                "description": "reserve: restaurant or venue name",
            },
            "date": {
                "type": "string",
                "description": "reserve: YYYY-MM-DD (or M/D/YYYY)",
            },
            "time": {
                "type": "string",
                "description": "reserve: HH:MM or 7pm",
            },
            "party": {
                "type": "integer",
                "description": "reserve: party size (default 2)",
            },
            "name": {
                "type": "string",
                "description": "reserve: guest name to type into a non-secret field",
            },
            "phone": {
                "type": "string",
                "description": "reserve: callback number to type (never a card number)",
            },
            "notes": {
                "type": "string",
                "description": "reserve: special requests to type if a notes field exists",
            },
            "path": {
                "type": "string",
                "description": (
                    "upload: file under workspace roots or outputs/. "
                    "download/pdf choose their own dest."
                ),
            },
            "x": {
                "type": "number",
                "description": (
                    "Pixel X. Only after screenshot then vision this turn."
                ),
            },
            "y": {
                "type": "number",
                "description": (
                    "Pixel Y. Only after screenshot then vision this turn."
                ),
            },
            "to": {
                "type": "string",
                "description": "drag: destination snapshot ref",
            },
            "to_x": {
                "type": "number",
                "description": "drag: destination pixel X (with x,y)",
            },
            "to_y": {
                "type": "number",
                "description": "drag: destination pixel Y (with x,y)",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        session: BrowserSession,
        *,
        aliases: dict[str, str] | None = None,
        event_sink: Any | None = None,
        workspace: Any | None = None,
    ) -> None:
        self.session = session
        self.aliases = dict(aliases or {})
        # Optional callable(kind: str, **payload) for Thinking telemetry.
        self._event_sink = event_sink
        self.workspace = workspace
        self._revived = False
        self._playwright_missing = False
        self.pixel_ok = False

    def _emit(self, kind: str, **payload: Any) -> None:
        if self._event_sink is None:
            return
        try:
            self._event_sink(kind, **payload)
        except Exception:
            log.debug("browser event sink failed", exc_info=True)

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        browser = str(kwargs.get("browser") or "default").strip().lower()
        private = bool(kwargs.get("private"))
        rewritten = rewrite_browser_action(action)
        invented_note = ""
        if rewritten is not None:
            invented_note = (
                f"There is no action {action!r}. Snapshot of the current tab. "
                "Next: click the Sign in / Log in control by ref. Do not invent "
                "a receipt. Password/OTP fields are their turn."
            )
            action = rewritten
        if action not in _ACTIONS:
            return ToolResult(
                ok=False,
                output=(
                    f"Unknown action {action!r}. Use: " + ", ".join(_ACTIONS) + "."
                ),
            )

        self._revived = False

        if action == "relaunch":
            ensured = await self.session.ensure(
                browser, private=private, relaunch=True
            )
            self._emit(
                "browser_relaunch",
                browser=self.session.last_browser or browser,
                ok=ensured.ok,
            )
            if not ensured.ok:
                return _to_tool(ensured)
            target = str(kwargs.get("url") or kwargs.get("target") or "").strip()
            if not target:
                return _to_tool(ensured)
            # Optional: open the original ask after restart (relaunch-then-open).
            return await self._open_or_navigate(
                "open",
                target,
                browser=browser,
                private=private,
                already_ensured=True,
                prefix=ensured.output,
            )

        if action == "snapshot":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                if await self._revive_once(browser, private, ensured):
                    ensured = await self._ensure(browser, private)
            if not ensured.ok:
                if invented_note:
                    return ToolResult(
                        ok=False,
                        output=invented_note + "\n" + (ensured.output or ""),
                        data=dict(ensured.data or {}),
                    )
                return ensured
            result = await self.session.snapshot(
                focus=str(kwargs.get("focus") or "").strip()
            )
            if not result.ok and await self._revive_once(
                browser, private, _to_tool(result)
            ):
                result = await self.session.snapshot(
                    focus=str(kwargs.get("focus") or "").strip()
                )
            self._emit("browser_snapshot", ok=result.ok)
            tool = _to_tool(result)
            if invented_note:
                return ToolResult(
                    ok=tool.ok,
                    output=invented_note + "\n" + (tool.output or ""),
                    data=dict(tool.data or {}),
                )
            return tool

        if action == "read":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            result = await self.session.read()
            self._emit("browser_read", ok=result.ok)
            return _to_tool(result)

        if action == "tabs":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            raw_select = kwargs.get("select")
            if raw_select is None or str(raw_select).strip() == "":
                sel: int | str | None = None
            elif isinstance(raw_select, bool):
                sel = None
            elif isinstance(raw_select, int):
                sel = raw_select
            else:
                sel = str(raw_select).strip()
            tab_op = str(kwargs.get("tab") or kwargs.get("op") or "").strip().lower()
            tab_url = str(kwargs.get("url") or kwargs.get("target") or "").strip()
            result = await self.session.tabs(select=sel, op=tab_op, url=tab_url)
            self._emit("browser_tabs", ok=result.ok)
            return _to_tool(result)

        if action == "click":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                if await self._revive_once(browser, private, ensured):
                    ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            ref = str(kwargs.get("ref") or "").strip()
            text = str(kwargs.get("text") or "").strip()
            try:
                nth = int(kwargs.get("nth") or 0)
            except (TypeError, ValueError):
                nth = 0
            if not ref and not text and nth < 1:
                return ToolResult(
                    ok=False,
                    output=(
                        "click needs ref, text (the visible label), or nth=1 "
                        "for the first result."
                    ),
                )
            result = await self.session.click(ref, text=text, nth=nth)
            if not result.ok and await self._revive_once(
                browser, private, _to_tool(result)
            ):
                result = await self.session.click(ref, text=text, nth=nth)
            self._emit("browser_click", ref=ref or text or f"nth={nth}", ok=result.ok)
            return _to_tool(result)

        if action == "type":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            ref = str(kwargs.get("ref") or "").strip()
            text = str(kwargs.get("text") or "")
            into = str(kwargs.get("into") or kwargs.get("target") or "").strip()
            who = str(kwargs.get("who") or "").strip()
            if ref and not _looks_like_ref(ref) and not into:
                into, ref = ref, ""
            fill_data: dict[str, Any] = {}
            if who:
                from arelis.browser.fill import fill_from_who

                filled, fill_data = fill_from_who(who, into=into)
                if fill_data.get("error"):
                    return ToolResult(
                        ok=False,
                        output=str(fill_data["error"]),
                        data=fill_data,
                    )
                text = filled
            elif text == "" and "text" not in kwargs:
                return ToolResult(ok=False, output="type needs text.")
            result = await self.session.type_text(ref, text, into=into)
            if result.ok and fill_data:
                data = dict(result.data or {})
                data.update(
                    {k: v for k, v in fill_data.items() if k != "error"}
                )
                result.data = data
            self._emit("browser_type", ref=ref or into or "field", ok=result.ok)
            return _to_tool(result)

        if action == "screenshot":
            # Never write a PNG until the session is connected (R10 / S12).
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                code = str((ensured.data or {}).get("code") or "")
                if code == "PROFILE_LOCKED":
                    return ToolResult(
                        ok=False,
                        output=(
                            ensured.output
                            + "\nScreenshot skipped — connect or Allow relaunch first "
                            "(no image file written)."
                        ),
                        data=dict(ensured.data or {}),
                    )
                return ensured
            full_page = bool(kwargs.get("full_page"))
            out_dir = str(outputs_dir() / "images")
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = os.path.join(
                out_dir, f"browser_{stamp}_{uuid4().hex[:8]}.png"
            )
            result = await self.session.screenshot(path, full_page=full_page)
            self._emit(
                "browser_screenshot",
                path=path,
                full_page=full_page,
                ok=result.ok,
            )
            tool = _to_tool(result)
            if tool.ok:
                # Built under the outputs directory, so this shortens rather than
                # falling back to an absolute path.
                tool.data["path"] = _project_rel(str(tool.data.get("path") or path))
                tool.output = (
                    f"{tool.output}\nSaved: {tool.data['path']}\n"
                    "Call vision with this path to describe what is on screen."
                )
            return tool

        if action == "scroll":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            result = await self.session.scroll(
                direction=str(kwargs.get("direction") or "down"),
                amount=int(kwargs.get("amount") or 600),
                ref=str(kwargs.get("ref") or "").strip(),
            )
            self._emit("browser_scroll", ok=result.ok)
            return _to_tool(result)

        if action == "press":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            key = str(kwargs.get("key") or kwargs.get("text") or "").strip()
            if not key:
                return ToolResult(ok=False, output="press needs key (Enter, Escape, Tab).")
            result = await self.session.press(key)
            self._emit("browser_press", key=key, ok=result.ok)
            return _to_tool(result)

        if action == "select":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            ref = str(kwargs.get("ref") or "").strip()
            value = str(kwargs.get("text") or kwargs.get("value") or "").strip()
            into = str(kwargs.get("into") or "").strip()
            if ref and not _looks_like_ref(ref) and not into:
                into, ref = ref, ""
            if not value:
                return ToolResult(ok=False, output="select needs text (the option).")
            result = await self.session.select_option(ref, value, into=into)
            self._emit("browser_select", ref=ref or into or "select", ok=result.ok)
            return _to_tool(result)

        if action == "wait":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            want_url = str(kwargs.get("url") or kwargs.get("target") or "").strip()
            want_text = str(kwargs.get("text") or "").strip()
            want_heading = str(kwargs.get("heading") or "").strip()
            from arelis.browser.wait_for import has_wait_needle

            has = has_wait_needle(
                url=want_url, text=want_text, heading=want_heading
            )
            try:
                seconds = float(
                    kwargs.get("seconds")
                    if kwargs.get("seconds") not in (None, "")
                    else (8.0 if has else 1.0)
                )
            except (TypeError, ValueError):
                seconds = 8.0 if has else 1.0
            result = await self.session.wait(
                seconds, url=want_url, text=want_text, heading=want_heading
            )
            self._emit(
                "browser_wait",
                ok=result.ok,
                hit=bool((result.data or {}).get("hit")),
            )
            if not result.ok or not has:
                return _to_tool(result)
            snap = await self.session.snapshot()
            parts = [result.output]
            if snap.ok:
                parts.append(snap.output)
            data = dict(result.data or {})
            data["snapshot"] = bool(snap.ok)
            return ToolResult(ok=True, output="\n\n".join(parts), data=data)

        if action == "back":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            result = await self.session.back()
            self._emit("browser_back", ok=result.ok)
            return _to_tool(result)

        if action == "forward":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            result = await self.session.forward()
            self._emit("browser_forward", ok=result.ok)
            return _to_tool(result)

        if action == "reload":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            result = await self.session.reload()
            self._emit("browser_reload", ok=result.ok)
            return _to_tool(result)

        if action == "find":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            text = str(kwargs.get("text") or kwargs.get("query") or "").strip()
            try:
                nth = int(kwargs.get("nth") or 0)
            except (TypeError, ValueError):
                nth = 0
            result = await self.session.find(text, nth=nth)
            self._emit("browser_find", text=text, ok=result.ok)
            return _to_tool(result)

        if action == "download":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            from arelis.browser.files import downloads_dir, safe_filename

            ref = str(kwargs.get("ref") or "").strip()
            text = str(kwargs.get("text") or "").strip()
            try:
                nth = int(kwargs.get("nth") or 0)
            except (TypeError, ValueError):
                nth = 0
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            dest = downloads_dir() / safe_filename(
                text or ref or "download",
                fallback=f"browser_{stamp}_{uuid4().hex[:8]}",
            )
            result = await self.session.download(
                str(dest), ref=ref, text=text, nth=nth
            )
            self._emit("browser_download", ok=result.ok, path=str(dest))
            return _to_tool_file(result)

        if action == "upload":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            from arelis.browser.files import resolve_upload_path

            raw_path = str(kwargs.get("path") or kwargs.get("url") or "").strip()
            allowed, err = resolve_upload_path(
                raw_path, workspace=self.workspace
            )
            if allowed is None:
                return ToolResult(
                    ok=False,
                    output=err,
                    data={"code": "UPLOAD_PATH"},
                )
            ref = str(kwargs.get("ref") or "").strip()
            into = str(kwargs.get("into") or kwargs.get("text") or "").strip()
            if ref and not _looks_like_ref(ref) and not into:
                into, ref = ref, ""
            result = await self.session.upload(
                ref, str(allowed), into=into
            )
            self._emit("browser_upload", ok=result.ok, path=str(allowed))
            return _to_tool(result)

        if action == "pdf":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            from arelis.browser.files import documents_dir, safe_filename

            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            dest = documents_dir() / safe_filename(
                str(kwargs.get("text") or "tab"),
                fallback=f"browser_{stamp}_{uuid4().hex[:8]}",
                suffix=".pdf",
            )
            result = await self.session.pdf(str(dest))
            self._emit("browser_pdf", ok=result.ok, path=str(dest))
            return _to_tool_file(result)

        if action in {"hover", "dblclick", "right_click", "drag"}:
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            from arelis.browser.pixels import parse_to_xy, parse_xy, xy_refused

            x, y = parse_xy(kwargs)
            if (x is not None or y is not None) and not self.pixel_ok:
                return ToolResult(
                    ok=False,
                    output=xy_refused(),
                    data={"code": "PIXEL_GATE"},
                )
            ref = str(kwargs.get("ref") or "").strip()
            text = str(kwargs.get("text") or "").strip()
            try:
                nth = int(kwargs.get("nth") or 0)
            except (TypeError, ValueError):
                nth = 0
            if action == "hover":
                result = await self.session.hover(
                    ref, text=text, nth=nth, x=x, y=y
                )
            elif action == "dblclick":
                result = await self.session.dblclick(
                    ref, text=text, nth=nth, x=x, y=y
                )
            elif action == "right_click":
                result = await self.session.right_click(
                    ref, text=text, nth=nth, x=x, y=y
                )
            else:
                to_x, to_y = parse_to_xy(kwargs)
                result = await self.session.drag(
                    ref,
                    to=str(kwargs.get("to") or "").strip(),
                    text=text,
                    nth=nth,
                    x=x,
                    y=y,
                    to_x=to_x,
                    to_y=to_y,
                )
            self._emit(f"browser_{action}", ref=ref or "xy", ok=result.ok)
            return _to_tool(result)

        if action == "watch":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            from arelis.browser.wait_for import has_wait_needle

            want_url = str(kwargs.get("url") or kwargs.get("target") or "").strip()
            want_text = str(kwargs.get("text") or "").strip()
            want_heading = str(kwargs.get("heading") or "").strip()
            if not has_wait_needle(
                url=want_url, text=want_text, heading=want_heading
            ):
                return ToolResult(
                    ok=False,
                    output="watch needs url, text, or heading to poll for.",
                )
            result = await self.session.watch(
                url=want_url, text=want_text, heading=want_heading
            )
            self._emit(
                "browser_watch",
                ok=result.ok,
                hit=bool((result.data or {}).get("hit")),
            )
            return _to_tool(result)

        if action == "search":
            query = str(
                kwargs.get("query")
                or kwargs.get("text")
                or kwargs.get("destination")
                or kwargs.get("url")
                or kwargs.get("target")
                or ""
            ).strip()
            if not query:
                return ToolResult(
                    ok=False,
                    output="search needs query (what to look up).",
                )
            from arelis.browser.search import normalize_search_site, search_url

            site = normalize_search_site(str(kwargs.get("site") or "google"))
            url = search_url(query, site=site)
            opened = await self._open_or_navigate(
                "open", url, browser=browser, private=private
            )
            if not opened.ok and await self._revive_once(browser, private, opened):
                opened = await self._open_or_navigate(
                    "open", url, browser=browser, private=private
                )
            self._emit("browser_search", query=query, site=site, ok=opened.ok)
            if not opened.ok:
                return opened
            await self.session.settle()
            tab = await self.session.read()
            extra_parts = [f"Search ({site}): {query}"]
            if tab.ok and (tab.output or "").strip():
                extra_parts.append(tab.output.strip())
            snap = await self.session.snapshot(focus="results")
            if snap.ok and (snap.output or "").strip():
                extra_parts.append(snap.output.strip())
            extra_parts.append(
                "Answer from this tab. Click a result by text, or "
                "click(nth=1) for the first one. Add to cart is fine. "
                "Stop before Checkout / Pay / Buy now."
            )
            extra = "\n\n" + "\n\n".join(extra_parts)
            data = dict(opened.data or {})
            data.update({"search_url": url, "query": query, "site": site})
            return ToolResult(
                ok=True,
                output=(opened.output or "").rstrip() + extra,
                data=data,
            )

        if action == "reserve":
            place = str(
                kwargs.get("place")
                or kwargs.get("query")
                or kwargs.get("destination")
                or kwargs.get("url")
                or kwargs.get("target")
                or kwargs.get("text")
                or ""
            ).strip()
            if not place:
                return ToolResult(
                    ok=False,
                    output="reserve needs place (restaurant or venue).",
                )
            from arelis.browser.reserve import (
                normalize_date,
                normalize_party,
                normalize_reserve_site,
                normalize_time,
                reserve_url,
            )

            site = normalize_reserve_site(str(kwargs.get("site") or "opentable"))
            party = normalize_party(kwargs.get("party") or kwargs.get("covers") or 2)
            date = normalize_date(str(kwargs.get("date") or ""))
            clock = normalize_time(str(kwargs.get("time") or ""))
            url = reserve_url(
                place, site=site, party=party, date=date or "", time=clock or ""
            )
            opened = await self._open_or_navigate(
                "open", url, browser=browser, private=private
            )
            self._emit(
                "browser_reserve",
                place=place,
                site=site,
                ok=opened.ok,
            )
            if not opened.ok:
                return opened
            filled: list[str] = [f"place={place}", f"party={party}", f"site={site}"]
            if date:
                filled.append(f"date={date}")
            if clock:
                filled.append(f"time={clock}")
            guest = str(kwargs.get("name") or "").strip()
            phone = str(kwargs.get("phone") or "").strip()
            notes = str(kwargs.get("notes") or "").strip()
            extra_bits: list[str] = [
                "",
                "Reservation search: " + ", ".join(filled) + ".",
                "I filled party / date / time in the URL where the site allows it.",
            ]
            if guest or phone or notes:
                extra_bits.append(
                    "After you pick a time, type remaining non-secret fields "
                    "(name/phone/notes). I do not type passwords or card numbers."
                )
            extra_bits.append(
                "You click Book / Reserve / Confirm. I stop on that screen."
            )
            extra = "\n".join(extra_bits)
            data = dict(opened.data or {})
            data.update(
                {
                    "reserve_url": url,
                    "place": place,
                    "site": site,
                    "party": party,
                    "date": date or "",
                    "time": clock or "",
                    "name": guest,
                    "phone": phone,
                    "notes": notes,
                }
            )
            return ToolResult(
                ok=True,
                output=(opened.output or "").rstrip() + extra,
                data=data,
            )

        if action == "maps":
            dest = str(
                kwargs.get("destination")
                or kwargs.get("query")
                or kwargs.get("url")
                or kwargs.get("target")
                or kwargs.get("text")
                or ""
            ).strip()
            if not dest:
                return ToolResult(
                    ok=False,
                    output="maps needs destination (a place or address).",
                )
            from arelis.browser.maps import maps_directions_url, maps_phone_link

            origin = str(kwargs.get("origin") or "").strip()
            mode = str(kwargs.get("mode") or kwargs.get("travelmode") or "driving")
            url = maps_directions_url(dest, origin=origin, mode=mode)
            phone = maps_phone_link(dest, mode=mode)
            opened = await self._open_or_navigate(
                "open", url, browser=browser, private=private
            )
            self._emit(
                "browser_maps",
                destination=dest,
                ok=opened.ok,
            )
            if not opened.ok:
                return opened
            extra = (
                f"\n\nPhone link (starts from the phone's GPS):\n{phone}\n"
                "If they asked to text it, call send_sms with this link. "
                "Allow still applies."
            )
            data = dict(opened.data or {})
            data.update(
                {
                    "maps_url": url,
                    "phone_link": phone,
                    "destination": dest,
                    "origin": origin,
                    "mode": mode,
                }
            )
            return ToolResult(
                ok=True,
                output=(opened.output or "").rstrip() + extra,
                data=data,
            )

        if action == "open":
            target = str(kwargs.get("url") or kwargs.get("target") or "").strip()
            return await self._open_or_navigate(
                "open", target, browser=browser, private=private
            )

        if action == "navigate":
            target = str(kwargs.get("url") or kwargs.get("target") or "").strip()
            return await self._open_or_navigate(
                action, target, browser=browser, private=private
            )

        return ToolResult(ok=False, output=f"Unhandled action {action!r}.")

    async def _open_or_navigate(
        self,
        action: str,
        target: str,
        *,
        browser: str,
        private: bool,
        already_ensured: bool = False,
        prefix: str = "",
    ) -> ToolResult:
        """CDP open/navigate (used after relaunch, or for action=navigate)."""
        url, err = resolve_target(target, aliases=self.aliases)
        if err or not url:
            return ToolResult(ok=False, output=err or "Missing url.")

        if already_ensured:
            ensured = ToolResult(ok=True, output=prefix or "Connected.")
        else:
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                code = str((ensured.data or {}).get("code") or "")
                if action == "open" and code in {
                    "NO_PLAYWRIGHT",
                    "CDP_TIMEOUT",
                    "CDP_DEAD",
                }:
                    opened = await self.session.open_url_os(url, browser)
                    if opened.ok:
                        data = dict(opened.data or {})
                        data["mode"] = str(data.get("mode") or "os_open")
                        data["code"] = code
                        extra = (
                            " Opened in her window without page control "
                            f"({code}). Read/click/screenshot need Playwright."
                        )
                        return ToolResult(
                            ok=True,
                            output=(opened.output or "").rstrip() + extra,
                            data=data,
                        )
                if code != "PROFILE_LOCKED":
                    return ensured
                # navigate needs CDP — relaunch once, then continue.
                self._emit(
                    "browser_relaunch_auto",
                    browser=browser,
                    url=url,
                    reason="PROFILE_LOCKED",
                )
                relaunched = await self.session.ensure(
                    browser, private=private, relaunch=True
                )
                self._emit(
                    "browser_relaunch",
                    browser=self.session.last_browser or browser,
                    ok=relaunched.ok,
                    auto=True,
                )
                if not relaunched.ok:
                    fail = _to_tool(relaunched)
                    fail.output = (
                        ensured.output
                        + "\n\nAuto-relaunch failed:\n"
                        + fail.output
                    )
                    data = dict(fail.data or {})
                    data["code"] = str(data.get("code") or "RELAUNCH_FAILED")
                    data["prior_code"] = "PROFILE_LOCKED"
                    fail.data = data
                    return fail
                ensured = _to_tool(relaunched)

        if action == "open":
            result = await self.session.open_url(url)
        else:
            result = await self.session.navigate(url)
        self._emit(f"browser_{action}", url=url, ok=result.ok)
        if not result.ok:
            return _to_tool(result)

        parts: list[str] = []
        from arelis.browser.launch import first_run_note, mark_intro_shown

        sign_in = first_run_note()
        if sign_in:
            parts.append(sign_in)
            mark_intro_shown()
        if prefix or (ensured.output and already_ensured):
            note = (prefix or ensured.output or "").strip()
            if note:
                parts.append(note)
        parts.append(result.output)
        # open = show the page. A full snapshot is a phone book of footer
        # links; the 7B then recites it. Snapshot on navigate (click prep).
        if action != "open":
            snap = await self.session.snapshot()
            if snap.ok:
                parts.append(snap.output)
            data = dict(result.data)
            data["snapshot"] = bool(snap.ok)
        else:
            data = dict(result.data)
            data["snapshot"] = False
        if sign_in:
            data["intro"] = sign_in
        landed = str(data.get("url") or "")
        from arelis.browser.walls import login_redirected_signed_in, nav_landed_note

        if login_redirected_signed_in(url, landed):
            data["signed_in"] = True
            note = nav_landed_note(url, landed)
            if note and note not in "\n\n".join(parts):
                parts.append(note)
        return ToolResult(ok=True, output="\n\n".join(parts), data=data)

    async def _revive_once(
        self, browser: str, private: bool, prior: ToolResult
    ) -> bool:
        """One auto-relaunch of her Chrome after mid-turn CDP death. Not OS-open."""
        code = str((prior.data or {}).get("code") or "")
        if prior.ok or code not in {"CDP_DEAD", "CDP_TIMEOUT"}:
            return False
        if self._revived:
            return False
        self._revived = True
        self._emit(
            "browser_relaunch_auto",
            browser=browser,
            reason=code,
        )
        relaunched = await self.session.ensure(
            browser, private=private, relaunch=True
        )
        self._emit(
            "browser_relaunch",
            browser=self.session.last_browser or browser,
            ok=relaunched.ok,
            auto=True,
        )
        return bool(relaunched.ok)

    async def _ensure(self, browser: str, private: bool) -> ToolResult:
        if self._playwright_missing:
            return ToolResult(
                ok=False,
                output=(
                    "Playwright is not installed, so this session cannot "
                    "drive or read the page. Open still works via the OS. "
                    "Install: pip install -e \".[browser]\" && playwright "
                    "install chromium firefox"
                ),
                data={"code": "NO_PLAYWRIGHT"},
            )
        ensured = await self.session.ensure(browser, private=private, relaunch=False)
        mode = str((ensured.data or {}).get("mode") or "")
        if ensured.ok:
            kind = (
                "browser_attach"
                if mode == "attach"
                else "browser_launch"
                if mode in {"launch", "firefox", "firefox_private", "fake"}
                else "browser_connect"
            )
            self._emit(kind, browser=self.session.last_browser or browser, mode=mode)
        tool = _to_tool(ensured)
        if not tool.ok and str((tool.data or {}).get("code") or "") == "NO_PLAYWRIGHT":
            self._playwright_missing = True
        return tool


def _looks_like_ref(raw: str) -> bool:
    text = (raw or "").strip().lower()
    return len(text) >= 2 and text[0] == "e" and text[1:].isdigit()


def _to_tool(result: Any) -> ToolResult:
    return ToolResult(
        ok=bool(result.ok),
        output=str(result.output),
        data=dict(result.data or {}),
    )


def _to_tool_file(result: Any) -> ToolResult:
    tool = _to_tool(result)
    if not tool.ok:
        return tool
    raw = str((tool.data or {}).get("abs_path") or (tool.data or {}).get("path") or "")
    if raw:
        short = _project_rel(raw)
        tool.data["path"] = short
        tool.data["abs_path"] = raw
        if short not in tool.output:
            tool.output = f"{tool.output}\nSaved: {short}"
    return tool
