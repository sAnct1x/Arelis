# Phone Notify URL (inbound SMS)

Arelis can receive texts that land as Android notifications (including RCS via
Google Messages) through the **Arelis Notify** companion app. Sending SMS is
separate — that still uses your phone as a modem after you Allow `send_sms`.

## Two inbound paths

```text
Google Messages notif  →  Arelis Notify app  →  POST :8765/inbound/sms  →  EventBus
SMSGate Local Server   →  InboundSmsWatcher poll  →  EventBus   (SMS/MMS only)
```

| Path | Covers | Needs |
|------|--------|-------|
| **Notify companion** (primary) | SMS + **RCS** via Google Messages notifications | Companion app + token + LAN |
| **SMSGate inbox poll** (fallback) | Classic SMS/MMS only | Local Server Online + `inbox_base_url` when outbound is Cloud |

**RCS = Notify only.** SMSGate never sees RCS. If you rely on Google Messages /
RCS, the companion is required.

`data/` and `logs/` below are under the user data root — `%LOCALAPPDATA%\Arelis`
installed, or the repository when running from source.

Both paths share one dedup store (`data/sms_inbound_seen.json`). First SMSGate
poll **seeds** the current inbox as already-seen (no backlog flood) — only
*new* rows after that announce.

## Setup

1. Keep Arelis running on the PC (window or tray). Tray Quit stops the listener.
2. Put a shared token in `data/secrets.yaml` under `sms.ingest_token` (see
   `data/secrets.example.yaml`), or set `ARELIS_INGEST_TOKEN`.
3. On the phone (same Wi‑Fi), open Arelis Notify and set the server URL to the
   LAN address Arelis shows — typically `http://<PC-LAN-IP>:8765`.
4. Copy the URL from the desktop: View → **notify url…**, or Settings →
   Notify, then **Copy primary URL**.

The STATUS line `Inbound notify ready — Phone Notify URL: …` is the same URL.

### Core + UI

If you run `arelis --core` (or attach to an external core), the glass UI does
**not** bind `:8765` itself. Inbound reaches chat only when the UI shows a live
IPC bridge attached. Without that bridge, core still logs the SMS and emits a
STATUS that nothing is attached — open the glass to see it in chat.

## Firewall

Allow inbound TCP on the ingest port (default **8765**) from your LAN if Windows
Firewall prompts. Do not expose the port to the public internet.

## If something else already has :8765

`8765` is an ordinary port and other software can be sitting on it — including
another Arelis, if two Windows accounts are signed into the same PC. Whichever
starts first keeps it; a later one falls forward to `:8766`, `:8767` and so on, and
says so:

```
Port 8765 was already in use, so inbound notify is on 8766 instead —
update the phone companion to http://<PC-LAN-IP>:8766
```

Act on that rather than closing it. A companion still pointed at `:8765` delivers
to whatever is there, which will not have your token, so the text is dropped with
nothing to show you why. View → **notify url…** (Settings → Notify) always shows
the port actually serving *this* Arelis, and the SMS readiness chip distinguishes
"your ingest is up" from "something else holds that port". Allow the new port
through the firewall too.

## Operator checklist (misses that look “random”)

Do these before digging in PC code:

1. **Battery optimization off** for Arelis Notify and SMSGate (Android Settings →
   Apps → battery → Unrestricted). Doze silently kills notification listeners.
2. **Notification access** on for Arelis Notify.
3. Companion **Test ping** OK; token matches `sms.ingest_token`; URL matches
   View → notify url… / Settings → Notify (DHCP IP drift is common).
4. Same LAN / not Guest Wi‑Fi; firewall TCP **8765** Private.
5. Google Messages notifications **not muted** for that chat — muted chats never
   notify, so they never bridge.
6. If using `--core`: UI shows live bridge attached.
7. Check `logs/arelis.log` for `Inbound ingest ignored`, `published=false`
   (duplicate), or `published id=…` lines.

Misses that cluster when the phone screen has been off for a while are usually
doze / battery, not Arelis rate-limiting (there is no inbound rate limiter).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No inbound texts | Arelis still running? Token matches? Same Wi‑Fi? |
| STATUS missing | `tools.sms.inbound` / `ingest` enabled in config; token set |
| Companion 401 | Wrong or missing `sms.ingest_token` |
| Companion timeout | Firewall / wrong IP — use View → notify url… / Settings → Notify |
| Some texts, not others | Muted chat? Battery optimization? See checklist above |
| Updates in a thread missing | Rebuild/reinstall companion after content-hash fix; check log for `published=false` |
| Core running, empty glass | UI not IPC-attached — open glass / check STATUS |
| SMSGate never sees RCS | Expected — use Notify companion |

## Related

- Architecture: [architecture.md](architecture.md)
- Health script: `scripts/check_inbound.ps1`
