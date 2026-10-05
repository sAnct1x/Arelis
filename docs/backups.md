# Backups

Arelis does not take a daily copy of `memory.db`. That used to fill
`data\backups\` on its own, so the dated memory snapshot stays off.

What she does take is a small copy right before an in-app upgrade
starts the installer. It is written under a temporary name first, and
only renamed to `pre-<version>\` (the version you are leaving) when
the copy is finished. A copy that stops halfway never has that final
name, and its temporary folder is removed right away. Leftover
temporary folders from older versions are removed the next time a
backup runs, and they do not count toward the two `pre-*` folders she
keeps.

The finished folders live next to her data folder, not inside it, so
an uninstall that wipes Arelis data does not take them with it. On a
normal Windows install that is a sibling of `%LOCALAPPDATA%\Arelis`
named `Arelis-backups`.

This starts with 0.3.0. The 0.2.9 to 0.3.0 upgrade is made by 0.2.9,
which has no backup code, so copy the data folder by hand first.

Only these files, and only if they are already there:

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
out until someone puts its name on that list. A symbolic link, or a
regular file with more than one hard link, is skipped even when its
name is on that list, so `rooms.yaml` cannot pull in `secrets.yaml`
by pointing at it.

She keeps the newest two `pre-*` folders and deletes older ones
inside that backups folder only.

If the copy fails, she shows a short notice and does not update.
Nothing has changed. She'll offer the update again tomorrow. If this
keeps happening, check that your disk has free space, or download the
new version from the Arelis releases page.

Running the setup `.exe` by hand over an existing install does not
write this copy. There is no restore command in this version.

## Restore

1. Close Arelis.
2. Copy the files you want from the `pre-<version>\` folder in that
   backups sibling back into `data\`.
3. Start Arelis.

Because `secrets.yaml` was never in the backup, memory, rooms, jobs,
contacts and settings come back, but mail, text, calendar, and API
keys do not. Set those up again in Settings and Notify (and the
Earth/science keys). A disk that loses `secrets.yaml` itself is the
case this does not cover.
