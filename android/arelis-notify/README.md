# Arelis (Android)

One sideloaded app. Scan the QR on the PC, then talk. The phone keeps
its own seat — it does not steal the PC's open thread. After pair,
install the offline brain (Gemma 4 E2B, ~2.6 GB) so she still talks
and can look at a photo if the PC is down. Wi-Fi is nicer; mobile
data is allowed if you say so, same as any big update.

Google Messages stays your messenger. SMS/RCS grants are **optional**
(Settings → Texts). This is not a Play Store build.

## Build / install

1. Open this folder in Android Studio (Giraffe+ / SDK 34).
2. Sync Gradle, connect the phone, **Run** the `app` configuration.
3. Or: `./gradlew :app:assembleDebug` then install
   `app/build/outputs/apk/debug/app-debug.apk`.
4. **Uninstall** the old `app.arelis.notify` package first. This id is
   `app.arelis`.

JVM tests (no emulator): `./gradlew :app:testDebugUnitTest` from this
folder. Pairing, URL strip, inbound queue, Gemma install, ready-file,
voice latches, pings. Not screenshots, not Gemma inference.

Android 13+ / 15: Play Protect may block a GitHub APK. Install anyway
from this repo, turn Protect back on.

## Configure

1. Same Wi-Fi as the PC. Arelis running (window, tray, or `--core` with
   the window open so she can think).
2. On the PC: Settings → **Notify**. Scan the QR (or paste the pairing
   text). Pairing is once.
3. Talk. Chat is home. **chats** and **files** are only at the house —
   same history as the PC, plus a new conversation. While the PC is off,
   you stay in the conversation you can already see. Gemma talk copies
   back silently when Arelis is up, including while it is still loading.
   System back goes up one screen. From chat, back leaves the app.
4. Optional **Settings → Texts**: restricted settings, SMS, notification
   access, Battery Unrestricted. Then inbound RCS and SMS-out after
   Allow. Re-pair only from Settings if this is a different PC.

## Notes

- Status is **at the house** or **on the phone**. Honest: Gemma can
  talk and look at a photo. She cannot mail, text, or open PC files.
- Arelis pings only for Allow waiting and finished jobs — never for a
  text or an email. Google already did that.
- Do not expose ingest to the public internet. Allow TCP 8765 on the PC
  firewall from your LAN. UDP 18765 (outbound broadcast) lets the phone
  find this PC after DHCP without a new QR.
- Gemma is an install option after pair (~2.6 GB). Wait for Wi-Fi, or
  use mobile data on purpose. Not stuffed in the APK, and not a surprise
  the first time the PC is down.

PC how-to: [docs/notify-inbound.md](../../docs/notify-inbound.md).
