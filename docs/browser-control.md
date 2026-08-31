# Browser

Arelis drives **her own Chrome window** (profile under
`data/browser-profile/`), not your daily Chrome. You watch it. You sign
into Google and Maps in that window once — launch prunes Cache / GPU
trees but keeps the sign-in. A full wipe is
`python -m arelis.housekeep --reset-browser`; the next open is a new
profile. She does not enter passwords,
OTP codes, or payment fields. Relaunch never runs `taskkill /IM
chrome.exe`.

Ask her to open a page and she does. If she offers a window you did not
ask for, you still get allow / deny.

The Windows installer already includes the browser extra. She attaches
to Chrome or Edge that is already on the PC. Firefox's private path still
needs Playwright's browsers, which from source means the extra step
below.

## From source

```powershell
cd C:\Users\you\Documents\Arelis
.\.venv\Scripts\pip.exe install -e ".[browser]"
.\.venv\Scripts\playwright.exe install chromium firefox
```

Chromium / CDP attaches to **her** Chrome. Firefox is still an ephemeral
private path when you ask.

## How open works

`browser(action=open, url=…)` launches or attaches Arelis Chrome as a
normal window on one monitor (~60% of that desk), not maximized across
the 1/2/3 span. If a single-desk Arelis window leaves room, she parks
beside chat. The tab opens there. Your other Chrome windows are left
alone.

First time: she tells you to sign into Google and Maps in that window.

## How click / snapshot / screenshot connect

1. If her Chrome already has CDP up at `tools.browser.cdp_url` (default
   `http://127.0.0.1:9222`), attach. If that port is already someone
   else's Chrome, she does not attach — she opens her window on 9333+.
   An empty process scan is unknown, not foreign: she keeps the port
   she already attached. A live attach is not hopped mid-errand.
2. If not: launch Chrome or Edge with `--remote-debugging-port` and
   `data/browser-profile/` (never `%LOCALAPPDATA%\Google\Chrome\User Data`).
3. If her window is wedged (process up, CDP down), she can `relaunch`.
   That stops **her** profile processes only. Mid-turn CDP death
   relaunches her Chrome once, then retries the same step.

Daily Chrome can stay open.

`open` / `navigate` / `click` all use this window. Search waits for
result links before the snapshot. Mid-turn CDP death no longer dumps
the turn — she restarts her window once.

Override per call: `browser=edge`, `browser=firefox`, `private=true`
(Firefox only).

## Tool

`browser` actions: `open`, `navigate`, `snapshot`, `read`, `maps`,
`search`, `reserve`, `click`, `type`, `scroll`, `press`, `select`,
`wait`, `back`, `forward`, `reload`, `find`, `tabs`, `screenshot`,
`relaunch`.

- Aliases: `youtube`, `gmail`, `github`, … (see `tools.browser.aliases`).
- You tell her the errand. She plans the clicks. Refs are optional.
- `click(text="Sign in")` or `click(nth=1)` for the first result.
  `type(text="…", into="search")` — empty `into` uses the search box.
  `find` lists matches without clicking. Password and OTP fields are refused.
- Snapshot ranks visible controls (light DOM, one shadow root, same-origin
  iframes). `focus=results` (what search returns)
  is a short result list, not the footer.
- `click` glows the target in-page (not your mouse), waits a beat, then
  clicks. The Drive strip says the label, not `e3`.
- `back` / `forward` / `reload`. `tabs` with `tab=new` (optional url) or
  `tab=close`. The window stays.
- `open` reuses the current tab and returns a short receipt.
- `read` returns compact visible text of the tab she is on. That is not
  scrape. The body is framed as untrusted data.
- `maps` opens Google Maps directions in her window and returns a phone
  link (destination-only, so the phone can start from GPS). If you asked
  her to text it, she calls `send_sms` with that link (allow / deny).
- `search` opens Google / YouTube / Amazon results in her window. She
  can type non-secret fields and click **Add to cart**. Checkout / Pay /
  Buy now is still your turn.
- `reserve` opens OpenTable (or Resy / Google) with party, date, and
  time in the URL. She can type remaining non-secret fields. Book /
  Reserve / Confirm is still your turn.
- A **Drive strip** in Arelis (not in Chrome) shows Stop / Pause /
  "about to click…". Pause freezes the glow beat and the next step. The
  page stays. Go continues. Stop aborts the turn. The same words work
  out loud on both faces.
- `screenshot` writes a PNG under `outputs/images/browser_….png`.
  Describe pixels with `vision` in a separate call. Optional
  `full_page=true`.

A drive you typed or said is the grant. If she offers the window, that
still pauses. `agent.confirm_browser` (default true) is that offer gate.
**rest of this ask** covers further browser steps in the same reply.
Vision uses `confirm_vision` separately. Never batches with mail or SMS.

## vs search / scrape

| Goal | Tool |
|------|------|
| Show me a page / click around in her window | `browser` |
| What is on this tab | `browser(action=read)` |
| Directions plus a link for the phone | `browser(action=maps)` |
| Search YouTube / Google / Amazon in her window | `browser(action=search)` |
| Book a table (you click Book) | `browser(action=reserve)` |
| Read the web for her answer (no window) | `web_search` / `scrape` |
| Page is a JS app scrape cannot read | `browser(action=open)` on that URL |

## Config

See `tools.browser` and `agent.confirm_browser` in
`arelis/config/default.yaml`. Unattended jobs do not get this tool.

## Your turn

She does not solve captchas, type passwords, or click Book / Pay / Order.
When she sees one of those walls she freezes, the Drive strip says
**your turn**, and the page stays. Captcha / sign-in: she continues when
the wall is gone (or you hit Go). Pay: you click the last button.
