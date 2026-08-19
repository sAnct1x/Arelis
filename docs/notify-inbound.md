# Phone companion

Arelis talks to one **Arelis** app on the phone. That companion is both
the radio (SMS out from your SIM after you allow it on the PC) and the
Google Messages notification bridge (SMS, MMS, RCS in). Google Messages
stays your daily messenger. Uninstall the old Notify APK after this
pairs. SMSGate can come off too unless you still want its inbox poll.

Sending still pauses for allow / deny on the PC. No silent SMS.

```text
OUT:  PC  --HTTP-->  Arelis radio on the handset  --SIM-->  SMS
IN:   Google Messages notif  →  Arelis app  →  POST :8765/inbound/sms
IN:   SMSGate Local Server   →  inbox poll  (optional leftover)
```

| Path | Covers | Needs |
|------|--------|-------|
| Arelis companion (primary) | SMS + RCS via Google Messages notifications. SMS out. | One APK, QR pair, same Wi-Fi |
| SMSGate inbox poll (fallback) | Classic SMS / MMS only | Local Server still running plus `inbox_base_url` |

RCS is companion notifications only. A SEND_SMS radio never sees RCS.
Keep Google Messages as the default SMS app. Do not make Arelis the
default SMS app.

`data/` and `logs/` below are under the user data root:
`%LOCALAPPDATA%\Arelis` installed, or the repository from source.

Both inbound paths share one dedup store (`data/sms_inbound_seen.json`).
The first SMSGate poll seeds the current inbox as already-seen, so you
are not flooded with backlog.

## Setup

1. Keep Arelis running on the PC (window or tray). Tray Quit stops the
   listener.
2. Put a shared token in `data/secrets.yaml` under `sms.ingest_token`
   (see `data/secrets.example.yaml`), or set `ARELIS_INGEST_TOKEN`.
3. Sideload the companion from `android/arelis-notify/` (application id
   `app.arelis`). Uninstall the old Notify app first.
4. On the phone, in order:
   1. If Play Protect blocks the APK, install anyway from this repo, then
      turn Protect back on.
   2. Settings → Apps → Arelis → ⋮ → **Allow restricted settings**
      (Android 13+).
   3. Grant **SMS**.
   4. Notification access → **Arelis**.
   5. Battery → **Unrestricted**.
   6. On the PC, Settings → **Notify**, scan the QR (or paste the pairing
      text).
5. Same Wi-Fi. The copyable LAN URL is still on that Settings tab if the
   camera fails.
6. If she could not text before this pair (no SMSGate leftover), restart
   **Arelis (dev)** once so `send_sms` is registered. Later DHCP IP
   changes do not need a restart.

The STATUS line about the Phone Notify URL is written to the thinking
dock, not chat.

### Core + UI

If you run `arelis --core` (or attach to an external core), the glass UI
does not bind `:8765` itself. Inbound reaches chat only when the UI
shows a live IPC bridge attached. Without that bridge, core still logs
the SMS. Open the glass to see it.

## Firewall

Allow inbound TCP on the ingest port (default **8765**) from your LAN if
Windows Firewall prompts. Do not expose the port to the public internet.

## If something else already has :8765

`8765` is an ordinary port. Other software can be sitting on it,
including another Arelis if two Windows accounts are signed into the
same PC. Whichever starts first keeps it. A later one falls forward to
`:8766`, `:8767` and so on, and says so.

Scan a **new QR** from Settings → Notify rather than guessing. A
companion still pointed at `:8765` delivers to whatever is there, which
will not have your token, so the text is dropped with nothing to show
you why. View → **notify url…** (Settings → Notify) always shows the
port actually serving this Arelis.

## If texts feel random

Do these before digging in PC code:

1. Battery Unrestricted for Arelis. Doze silently kills notification
   listeners.
2. Notification access on for Arelis.
3. Companion paired. Token in the QR matches `sms.ingest_token`. DHCP
   IP drift: the app re-registers on Wi-Fi change. If it still fails,
   scan a new QR.
4. Same LAN, not Guest Wi-Fi. Firewall TCP 8765, Private.
5. Google Messages notifications not muted for that chat. Muted chats
   never notify, so they never bridge.
6. If using `--core`: UI shows live bridge attached.
7. Check `logs/arelis.log` for `Inbound ingest ignored`,
   `published=false` (duplicate), or `published id=…` lines.

Misses that cluster when the phone screen has been off for a while are
usually doze, not Arelis rate-limiting. There is no inbound rate
limiter. Failed POSTs stay in a queue on the phone and retry when the
PC is back.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No inbound texts | Arelis still running? Paired? Same Wi-Fi? |
| STATUS missing | `tools.sms.inbound` / `ingest` enabled. Token set. Thinking dock (`Ctrl+1`), not the orbit |
| Companion 401 | Wrong or missing `sms.ingest_token`. New QR |
| Companion timeout | Firewall / wrong IP. Scan Settings → Notify again |
| Pairing 409 | QR was for a different Windows account's Arelis |
| Some texts, not others | Muted chat? Battery optimization? |
| Updates in a thread missing | Rebuild / reinstall companion. Check log for `published=false` |
| Core running, empty glass | UI not IPC-attached |
| SMS radio never sees RCS | Expected. Keep Google Messages plus notification access |

## Related

- Architecture: [architecture.md](architecture.md)
- Health script: `scripts/check_inbound.ps1`
