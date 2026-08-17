# Calendar OAuth — Google + Outlook

Explicit exception to local-first: Arelis may hold **calendar** refresh tokens
so she can read/write Google Calendar and Outlook. Models stay local. Writes
always require an Allow confirm card.

`data/secrets.yaml` below is under your records folder:
`%LOCALAPPDATA%\Arelis\data` for an installed copy, or `data\` in the
repository when running from source. See the README for that split.

## Checklist (only you can do this)

### A — Google

1. [Google Cloud Console](https://console.cloud.google.com/) → project (e.g. `arelis-home`).
2. Enable **Google Calendar API**.
3. OAuth consent screen → External → app name `Arelis` → add yourself as test user.
4. Credentials → OAuth client ID → **Desktop app** → copy client id + secret.
5. Paste into `data/secrets.yaml` under `calendar.google.client_id` / `client_secret`.
6. Sign in from a terminal:

From an installed copy:

```powershell
& "$env:LOCALAPPDATA\Programs\Arelis\Scripts\arelis.cmd" --auth-calendar google
```

From a source checkout:

```powershell
cd C:\Users\you\Documents\Arelis
.\.venv\Scripts\arelis.exe --auth-calendar google
```

7. Allow access. `refresh_token` is written into `secrets.yaml`.

### B — Outlook / Microsoft (personal account)

School and work tenants often block app registration. Use a **personal**
Microsoft account (Outlook.com / Hotmail / live.com) instead.

1. Sign out of any work or school session in Azure.
2. Open [Azure portal](https://portal.azure.com/) and sign in with your
   **personal** Microsoft account.
3. If you see tenant / “interaction required” errors: search **Microsoft Entra ID**
   → **Manage tenants** → **Create** a free personal tenant → **Switch** to it.
4. [App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
   → **New registration**.
5. Name: `Arelis`. Accounts: **Personal Microsoft accounts only**.
6. Redirect URI → **Mobile and desktop applications** →  
   `https://login.microsoftonline.com/common/oauth2/nativeclient`  
   (also add `http://localhost` if the UI allows a second URI).
7. After create: **Authentication** → **Allow public client flows** = **Yes**.
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

10. Run `--auth-calendar outlook` the same way as the Google step above
    (installed `arelis.cmd`, or `.\.venv\Scripts\arelis.exe` from a checkout).

Sign in with the **same personal Microsoft account** that owns the Outlook calendar.

## What Arelis does after that

- `agenda` sync/list reads a local cache filled from the APIs (ICS file is fallback).
- `agenda` create/update/delete open a confirm card; never silent; never batched.
- Unattended jobs do not get calendar write tools.

## Testing note (Google)

While the OAuth app is in **Testing**, Google may expire refresh tokens after ~7 days.
Add yourself as a test user, or publish the app when you trust the scopes.
