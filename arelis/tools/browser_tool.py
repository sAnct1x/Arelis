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
)


class BrowserTool:
    name = "browser"
    description = (
        "Open and drive the user's real desktop browser (usually the system "
        "default — Chrome when that is default), using their existing logged-in "
        "sessions. Prefer this when they ask to pull up / open / go to a site "
        "or click around a page. Use search/scrape when YOU need to read the "
        "web without opening a window. Never type passwords or OTP codes. "
        "If a captcha, sign-in, or Book/Pay/Order screen appears, stop and "
        "tell the user it is their turn — do not solve captchas or click Pay. "
        "Actions: open (alias or https URL in Arelis' Chrome window, not the "
        "daily browser), navigate (same window), snapshot (get click refs), "
        "read (compact text of the tab she is on — not scrape), "
        "maps (directions in her window + a phone link), "
        "search (Google / YouTube / Amazon results in her window), "
        "reserve (OpenTable / Resy / Google — fills party/date/time; you click Book), "
        "click(ref) (glows first), type(ref, text), scroll, press(key), "
        "select(ref, text), wait(seconds), tabs, screenshot (PNG under "
        "outputs/images/ — then vision to describe), relaunch (CDP restart; "
        "optional url opens after). Prefer open when they only asked to pull "
        "up a site. Prefer read when they ask what is on this tab/page. "
        "Prefer maps when they ask for directions — opens Maps in her "
        "window and returns a phone link. Do not scrape for directions. "
        "Prefer search when they ask to look something up on YouTube / "
        "Google / Amazon in her window. Add to cart is fine; stop before "
        "Checkout / Pay / Buy now. "
        "Sign in on the current page: snapshot, then click Sign in by ref. "
        "There is no goto_sign_in action. Username they provide can be typed "
        "into a non-secret field; never type passwords or OTP. "
        "Prefer reserve when they ask to book a table / make a reservation. "
        "That opens OpenTable (or Resy / Google) with party, date, and time "
        "filled in the URL. Type remaining non-secret fields. Never click "
        "Book / Reserve / Confirm reservation — that is their turn. "
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
                    "tabs / screenshot / relaunch"
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
                "description": "Text to type into a non-secret field",
            },
            "select": {
                "type": "integer",
                "description": "Tab index for action=tabs",
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
                "description": "wait: 0.2-8 seconds",
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
        },
        "required": ["action"],
    }

    def __init__(
        self,
        session: BrowserSession,
        *,
        aliases: dict[str, str] | None = None,
        event_sink: Any | None = None,
    ) -> None:
        self.session = session
        self.aliases = dict(aliases or {})
        # Optional callable(kind: str, **payload) for Thinking telemetry.
        self._event_sink = event_sink

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
                if invented_note:
                    return ToolResult(
                        ok=False,
                        output=invented_note + "\n" + (ensured.output or ""),
                        data=dict(ensured.data or {}),
                    )
                return ensured
            result = await self.session.snapshot()
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
            select = kwargs.get("select")
            sel = int(select) if select is not None and str(select) != "" else None
            result = await self.session.tabs(select=sel)
            self._emit("browser_tabs", ok=result.ok)
            return _to_tool(result)

        if action == "click":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            ref = str(kwargs.get("ref") or "").strip()
            if not ref:
                return ToolResult(ok=False, output="click needs ref from snapshot.")
            result = await self.session.click(ref)
            self._emit("browser_click", ref=ref, ok=result.ok)
            return _to_tool(result)

        if action == "type":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            ref = str(kwargs.get("ref") or "").strip()
            text = str(kwargs.get("text") or "")
            if not ref:
                return ToolResult(ok=False, output="type needs ref from snapshot.")
            if text == "" and "text" not in kwargs:
                return ToolResult(ok=False, output="type needs text.")
            result = await self.session.type_text(ref, text)
            self._emit("browser_type", ref=ref, ok=result.ok)
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
            if not ref:
                return ToolResult(ok=False, output="select needs ref from snapshot.")
            if not value:
                return ToolResult(ok=False, output="select needs text (the option).")
            result = await self.session.select_option(ref, value)
            self._emit("browser_select", ref=ref, ok=result.ok)
            return _to_tool(result)

        if action == "wait":
            ensured = await self._ensure(browser, private)
            if not ensured.ok:
                return ensured
            try:
                seconds = float(kwargs.get("seconds") or 1.0)
            except (TypeError, ValueError):
                seconds = 1.0
            result = await self.session.wait(seconds)
            self._emit("browser_wait", ok=result.ok)
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
            self._emit("browser_search", query=query, site=site, ok=opened.ok)
            if not opened.ok:
                return opened
            tab = await self.session.read()
            extra_parts = [f"Search ({site}): {query}"]
            if tab.ok and (tab.output or "").strip():
                extra_parts.append(tab.output.strip())
            extra_parts.append(
                "Answer from this tab. Snapshot or click a result if they "
                "asked to open one. Add to cart is fine. Stop before "
                "Checkout / Pay / Buy now."
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

    async def _open_plain(self, target: str, *, browser: str) -> ToolResult:
        """Back-compat name — open now lands in Arelis Chrome."""
        return await self._open_or_navigate(
            "open", target, browser=browser, private=False
        )

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
        return ToolResult(ok=True, output="\n\n".join(parts), data=data)

    async def _ensure(self, browser: str, private: bool) -> ToolResult:
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
        return _to_tool(ensured)


def _to_tool(result: Any) -> ToolResult:
    return ToolResult(
        ok=bool(result.ok),
        output=str(result.output),
        data=dict(result.data or {}),
    )
