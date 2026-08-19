# Arelis Notify

Android companion that forwards **Google Messages** notifications (SMS, MMS,
and RCS) to Arelis on your PC over the LAN.

## Why

SMSGate cannot read RCS chats. This app uses Notification Listener access — the
same surface Android already shows you — and POSTs each alert to Arelis while
ingest is up (desktop open, hidden in the tray, or `arelis --core`).

## Build / install

1. Open this folder in Android Studio (Giraffe+ / SDK 34).
2. Sync Gradle, connect the phone, **Run** the `app` configuration.
3. Or: `./gradlew :app:assembleDebug` then install
   `app/build/outputs/apk/debug/app-debug.apk`.

## Configure

1. On the phone: Settings → Notifications → Notification access → enable
   **Arelis Notify**.
2. Open the app. Set:
   - **Arelis URL:** `http://YOUR_PC_LAN_IP:8765` (no trailing path)
   - **Token:** paste `sms.ingest_token` from `data/secrets.yaml` on the PC
     (eye icon shows/hides the field; if unsure what the phone has, overwrite
     from the PC file — that is the source of truth)
3. Tap **Test ping** — should say OK when Arelis ingest is listening (UI, tray,
   or `--core`). A full Quit from the tray stops the port.
4. Keep Google Messages notifications on for contacts you care about.

## Notes

- Phone and PC must be on the same Wi‑Fi; allow TCP 8765 on the PC firewall.
- If ping fails, run `.\scripts\check_inbound.ps1` on the PC (see main README).
- Muted / silenced chats do not produce notifications and will not bridge.
- Outbound texts still go through SMSGate + allow / deny on the PC; this app is
  inbound only.
