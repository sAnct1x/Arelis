# Phone companion

The phone is her face in your pocket. Same Wi-Fi, scan the QR once, talk.
That is the whole first-run. SMS/RCS grants are **optional** (Settings →
Texts in the app). Google Messages stays your messenger. This is not a
Play Store build, and it is not a second copy of Arelis.

- **At the house** — same Wi-Fi, PC reachable. Chat is the same live
  session as the desktop. Allow/Deny for sends she already does on the
  PC. **files** opens the current room or workspace. **chats** is the PC
  history plus a new conversation; switching on the phone switches the
  desktop too. Plots she just made still show as cards. Allow on the
  phone is the same card as the PC — one press on either side settles it.
- **On the phone** — the PC is gone. Chats and files wait. If you
  installed the offline brain at pair (Gemma 4 E2B, ~2.6 GB), she can
  talk and look at a photo you just took. No mail, no SMS, no PC files.
  You stay in the conversation already on screen. When Arelis is back —
  even during “At the house · loading” — those words copy in, no prompt
  and no extra line. If there was no house thread yet, they become a
  new conversation instead of landing in last week’s. Wi-Fi is the nicer
  download; mobile data is allowed if you choose it.

The companion is still the radio (SMS out after Allow) and the Google
Messages notification bridge (SMS, MMS, RCS in) if you turn that on.
Uninstall the old Notify APK after this pairs.

Sending still pauses for allow / deny. No silent SMS. Until the phone is
paired with a radio URL, `send_sms` is not registered and chat will say
she cannot text.

| Path | Covers | Needs |
|------|--------|-------|
| Talk (default) | Same session as the PC. Gemma if the PC is away. | One APK, QR pair, same Wi-Fi. No SMS grant. |
| Texts (optional) | SMS + RCS via Google Messages. SMS out. | Restricted settings, SMS, notification access, battery Unrestricted |
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
4. On the phone: scan the QR on Settings → Notify (or paste the pairing
   text). Same Wi-Fi. You can talk immediately. SMS grants are not
   required for talk.
5. After pair, install the offline brain (~2.6 GB) so she still talks
   if the PC is down. Wait for Wi-Fi, or use mobile data on purpose.
6. Optional, only if you want the text hose: **Settings → Texts**, then
   Allow restricted settings, SMS, notification access, Battery
   Unrestricted. Pairing and texts are once; chat is the home screen.
   System back on the phone returns one screen (not out of the app)
   until you are on chat.
7. If Play Protect blocks the APK, install anyway from this repo, then
   turn Protect back on. If she could not text before a radio pair,
   restart **Arelis (dev)** once so `send_sms` is registered.

The STATUS line about the Phone Notify URL is written to the thinking
dock, not chat.

### Core + UI

If you run `arelis --core` (or attach to an external core), the window
does not bind `:8765` itself. Inbound reaches chat only when the UI
shows a live IPC bridge attached. Without that bridge, core still logs
the SMS. Open the window to see it.

## Firewall

Allow inbound TCP on the ingest port (default **8765**) from your LAN if
Windows Firewall prompts. UDP **18765** is optional: the PC broadcasts
so the phone can find a new DHCP lease without a new QR. Do not expose
either port to the public internet.

## If something else already has :8765

`8765` is an ordinary port. Other software can be sitting on it,
including another Arelis if two Windows accounts are signed into the
same PC. Whichever starts first keeps it. A later one falls forward to
`:8766`, `:8767` and so on, and says so.

The phone finds the port this Arelis actually bound. A companion still
pointed at `:8765` after a fall-forward would have hit whoever is there;
the LAN beacon plus instance check now skip a stranger on that port.
View → **notify url…** (Settings → Notify) still shows the port serving
this Arelis.

## If texts feel random

Do these before digging in PC code:

1. Battery Unrestricted for Arelis. Doze silently kills notification
   listeners.
2. Notification access on for Arelis.
3. Companion paired. Token in the QR matches `sms.ingest_token`. DHCP
   IP drift: the phone re-registers its radio and listens for a LAN
   beacon from this PC. Do not scan a new QR for a lease change — only
   for a different PC or a different phone.
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
| Companion timeout | Firewall / wrong IP. Wait for the phone to find the LAN beacon, or open Settings → Notify if this is a new PC |
| Pairing 409 | QR was for a different Windows account's Arelis |
| Some texts, not others | Muted chat? Battery optimization? |
| Updates in a thread missing | Rebuild / reinstall companion. Check log for `published=false` |
| Core running, empty window | UI not IPC-attached |
| SMS radio never sees RCS | Expected. Keep Google Messages plus notification access |
| Picture shows as a Photo chip | Rebuild/sideload the companion. Google Messages often posts no bytes. |
| Picture never arrives after APK update | Pairing token still matches. Restart Arelis on the PC |

## Inbound pictures

The desktop tile shows a picture when the phone actually sent bytes. If it
only sent the word Photo, you get a chip, not a blank bubble.

Companion POST `/inbound/sms` may include:

| Field | What it is |
|---|---|
| `body` / `text` | Caption. `"Photo"` with no bytes → chip |
| `image_jpeg` | Base64 JPEG from the notification extras (max ~400 KB on the phone, 1 MB on the PC) |
| `media_url` | `http(s)` image URL. `file://` is refused |

Sideload a new companion APK or those extras never leave the phone. SMSGate
inbox rows that carry `mediaUrl` / `parts[].url` are fetched on the PC; if the
Local Server has no media, you still get the chip.

Cached files live under the user data root (`sms_media/`), not the git repo.

## Related

- Architecture: [architecture.md](architecture.md)
- Health script: `scripts/check_inbound.ps1`
