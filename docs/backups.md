# Backups

Arelis does not take a daily copy of `memory.db`. That used to fill
`data\backups\` on its own, so the dated memory snapshot stays off.

What she does take is a small copy right before an in-app upgrade
starts the installer. It lands in `data\backups\pre-<version>\` (the
version you are leaving). Only these files, and only if they are
already there:

- `memory.db`
- `rooms.yaml`
- `jobs.yaml`
- `config.local.yaml`
- `contacts.yaml`
- `profile.yaml`
- `lessons.yaml`

Passwords and tokens in `secrets.yaml` are never copied. Pairing
data, the browser profile, SMS threads and media, and the action
ledger are not copied either. A later file added under `data\` stays
out until someone puts its name on that list.

She keeps the newest two `pre-*` folders and deletes older ones
inside `data\backups\` only.

Running the setup `.exe` by hand over an existing install does not
write this copy. There is no restore command in this version.

## Restore

1. Close Arelis.
2. Copy the files you want from `data\backups\pre-<version>\` back
   into `data\`.
3. Start Arelis.

Because `secrets.yaml` was never in the backup, memory, rooms, jobs,
contacts and settings come back, but mail, text, calendar, and API
keys do not. Set those up again in Settings and Notify (and the
Earth/science keys). A disk that loses `secrets.yaml` itself is the
case this does not cover.
