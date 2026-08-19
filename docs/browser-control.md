# 🧭 Browser control

Arelis drives **her own Chrome window** (profile under
`data/browser-profile/`), not your daily Chrome. You watch it. You sign
into Google and Maps in that window once. She does not enter passwords,
OTP codes, or payment fields. Relaunch never runs `taskkill /IM
chrome.exe`.

Ask her to open a page and she does. If she offers a window you did not
ask for, you still get allow / deny. Living notes:
[whats-new.md](whats-new.md).

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

`browser(action=open, url=…)` launches or attaches Arelis Chrome, same
size as the Arelis app, offset down-right so it does not cover chat. The
tab opens there. Your other Chrome windows are left alone.

First time: she tells you to sign into Google and Maps in that window.

## How click / snapshot / screenshot connect

1. If her Chrome already has CDP up at `tools.browser.cdp_url` (default
   `http://127.0.0.1:9222`), attach.
2. If not: launch Chrome or Edge with `--remote-debugging-port` and
   `data/browser-profile/` (never `%LOCALAPPDATA%\Google\Chrome\User Data`).
3. If her window is wedged (process up, CDP down), she can `relaunch`.
   That stops **her** profile processes only.

Daily Chrome can stay open.

`open` / `navigate` / `click` all use this window. Mid-turn CDP death
returns `CDP_DEAD` instead of crashing the turn.

Override per call: `browser=edge`, `browser=firefox`, `private=true`
(Firefox only).

## Tool

`browser` actions: `open`, `navigate`, `snapshot`, `read`, `maps`,
`search`, `reserve`, `click`, `type`, `scroll`, `press`, `select`,
`wait`, `tabs`, `screenshot`, `relaunch`.

- Aliases: `youtube`, `gmail`, `github`, … (see `tools.browser.aliases`).
- Click and type use snapshot refs. Password and OTP fields are refused.
- `click` glows the target in-page (not your mouse), waits a beat, then
  clicks.
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
- A glass **Drive strip** in Arelis (not in Chrome) shows Stop / Pause /
  "about to click…". Pause freezes the glow beat and the next step. The
  page stays. Go continues. Stop aborts the turn.
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
