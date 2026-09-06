# Calendar OAuth

Explicit exception to local-first: Arelis may hold **calendar** refresh
tokens so she can read and write Google Calendar and Outlook. Models
stay local. Writes always wait for allow / deny. She can create events
on the local tile before anything is connected. Connecting or
re-authorizing Google / Outlook pushes those pending events in the
background — no second ask. Ctrl+7 opens the local tile either way.

`data/secrets.yaml` is under your records folder:
`%LOCALAPPDATA%\Arelis\data` installed, or `data\` in the repository
from source.

## Google

1. [Google Cloud Console](https://console.cloud.google.com/) → a project
   (for example `arelis-home`).
2. Enable **Google Calendar API**.
3. OAuth consent screen → External → app name `Arelis` → add yourself as
   a test user.
4. Credentials → OAuth client ID → **Desktop app** → copy client id and
   secret.
5. Paste into `data/secrets.yaml` under `calendar.google.client_id` /
   `client_secret`.
6. Open the calendar tile (Ctrl+7) and press **sign in**. Arelis
   opens Google in the browser. Allow access. The refresh token is
   written into `secrets.yaml`.

While the OAuth app is in **Testing**, Google expires refresh tokens
after about seven days of light use. That is expected. The next sync
or create opens the sign-in again from the tile — do not run a
terminal command. Publish the Cloud app when you trust the scopes if
you want tokens that last.

## Outlook / Microsoft (personal account)

School and work tenants often block app registration. Use a **personal**
Microsoft account (Outlook.com / Hotmail / live.com) instead.

1. Sign out of any work or school session in Azure.
2. Open [Azure portal](https://portal.azure.com/) and sign in with your
   personal Microsoft account.
3. If you see tenant / "interaction required" errors: search **Microsoft
   Entra ID** → **Manage tenants** → **Create** a free personal tenant
   → **Switch** to it.
4. [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
   → **New registration**.
5. Name: `Arelis`. Accounts: **Personal Microsoft accounts only**.
6. Redirect URI → **Mobile and desktop applications** →
   `https://login.microsoftonline.com/common/oauth2/nativeclient`
   (also add `http://localhost` if the UI allows a second URI).
7. After create: **Authentication** → **Allow public client flows** =
   **Yes**.
8. **API permissions** → Microsoft Graph → Delegated →
   `Calendars.ReadWrite`, `offline_access`, `User.Read`.
9. Paste **Application (client) ID** into `data/secrets.yaml`:

```yaml
calendar:
  outlook:
    client_id: "<Application (client) ID>"
    client_secret: ""
    tenant: "consumers"
    refresh_token: ""
```

10. Open the calendar tile and press **sign in** (Outlook if Google
    is not configured).

Sign in with the same personal Microsoft account that owns the Outlook
calendar.

## What Arelis does after that

- `agenda` sync / list reads a local cache filled from the APIs (ICS
  file is fallback).
- `agenda` create / update / delete open a confirm card. Never silent.
  Never batched.
- Unattended jobs do not get calendar write tools.

Timed email digests need mail first, not a calendar token.
[jobs.md](jobs.md).
