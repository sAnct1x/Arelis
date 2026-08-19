# Arelis (Android companion)

One sideloaded app: Google Messages inbound (SMS, MMS, RCS) plus a LAN
SMS radio so the PC can send from this SIM after allow / deny. Google
Messages stays the default messenger. This is not a Play Store build.

## Build / install

1. Open this folder in Android Studio (Giraffe+ / SDK 34).
2. Sync Gradle, connect the phone, **Run** the `app` configuration.
3. Or: `./gradlew :app:assembleDebug` then install
   `app/build/outputs/apk/debug/app-debug.apk`.
4. **Uninstall** the old `app.arelis.notify` package first. This id is
   `app.arelis`.

Android 13+ / 15: Play Protect may block a GitHub APK. Install anyway
from this repo, turn Protect back on, then Settings → Apps → Arelis → ⋮
→ **Allow restricted settings** before SMS and notification access will
take.

## Configure

1. On the phone, in order:
   - Allow restricted settings (see above).
   - Grant **SMS**.
   - Settings → Notifications → Notification access → **Arelis**.
   - Battery → **Unrestricted**.
2. On the PC, open Settings → **Notify**. Scan the QR (or paste the
   pairing text). Same Wi-Fi. Arelis must be running (window, tray, or
   `--core`).
3. Uninstall SMSGate after a successful pair unless you still want its
   inbox poll as a leftover.

## Notes

- Phone and PC must be on the same Wi-Fi. Allow TCP 8765 on the PC
  firewall. Do not expose ingest to the public internet.
- Muted / silenced Google Messages chats do not produce notifications
  and will not bridge.
- Outbound SMS from the desk still uses the allow / deny card on the PC.
  You still type your own texts in Google Messages.
- Inbound POSTs that fail while the PC is asleep are queued on the phone
  and retried.

PC how-to: [docs/notify-inbound.md](../../docs/notify-inbound.md).
