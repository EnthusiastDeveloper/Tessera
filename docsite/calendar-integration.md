# Connecting an External Calendar

Tessera can read your existing Google or Outlook calendar so those events count as scheduling obstacles - see [Capabilities](capabilities.md#external-calendar-sync) for what that means in practice. Getting there requires registering a small OAuth application with the provider first; this page walks through that, end to end, for both providers.

**This is a one-time, per-deployment setup step**, done by whoever operates the Tessera instance (not something each user does). Once the environment variables below are in place, connecting is a two-click flow inside the app.

## How it fits together

1. You register an OAuth application with Google or Microsoft. This gets you a **client ID** and **client secret** - credentials that identify *your Tessera instance* to the provider, not your personal account.
2. You put those in Tessera's `.env` file and restart the container.
3. In Tessera's **Settings → External calendars**, you click "Connect" and sign in with your actual Google/Microsoft account, granting Tessera **read-only** access to your calendar.
4. Tessera polls that calendar in the background and caches events locally.

Nothing here needs your Tessera instance to be reachable from the public internet - the redirect happens through *your own browser*, not a server-to-server callback. A LAN-only deployment works fine as long as the browser doing the connecting can reach `APP_BASE_URL`.

## Prerequisites

- `APP_BASE_URL` set in `.env` to the URL you actually use to reach Tessera (e.g. `http://tessera.local:8000` or `https://tessera.example.com`). This is used to build the redirect URI below - get it right *before* registering the OAuth app, since the redirect URI has to match exactly.
- The container restarted after any `.env` change - these variables are only read at startup.

Each provider needs its own redirect URI, built from `APP_BASE_URL`:

```
{APP_BASE_URL}/api/v1/calendar-connections/google/callback
{APP_BASE_URL}/api/v1/calendar-connections/outlook/callback
```

For `APP_BASE_URL=https://tessera.example.com`, that's `https://tessera.example.com/api/v1/calendar-connections/google/callback`.

## Google Calendar

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or pick an existing one) - the free tier is enough, this doesn't need billing enabled.
2. **APIs & Services → Library**: search for and enable the **Google Calendar API**.
3. **APIs & Services → OAuth consent screen**:
    - User type: **External** (unless you're on Google Workspace and want to restrict this to your organization, in which case **Internal**).
    - Fill in the required app name/support email fields - these are just labels shown on the consent screen, not verified by Google for this use case.
    - Add the scope `https://www.googleapis.com/auth/calendar.readonly`.
    - Under **Test users**, add the Google account(s) you'll actually connect. Google apps start in "Testing" status, which restricts sign-in to accounts you've explicitly listed here - without this step, Google will refuse to let you complete the connection.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
    - Application type: **Web application**.
    - Under **Authorized redirect URIs**, add the exact Google redirect URI from [Prerequisites](#prerequisites) above.
    - Save, then copy the **Client ID** and **Client secret** it generates.
5. In Tessera's `.env`:
   ```
   GOOGLE_CLIENT_ID=<client id>
   GOOGLE_CLIENT_SECRET=<client secret>
   ```
6. Restart the container.
7. In Tessera, go to **Settings → External calendars** and click **Connect Google Calendar**. You'll be sent to Google's real sign-in/consent screen; approve it, and you'll land back in Tessera with a "Google Calendar connected" confirmation.

## Outlook / Microsoft 365 Calendar

1. Go to the [Azure Portal](https://portal.azure.com/) → **Microsoft Entra ID** → **App registrations** → **New registration**.
2. Name it anything recognizable (e.g. "Tessera").
3. Under **Supported account types**, choose **Accounts in any organizational directory and personal Microsoft accounts** - Tessera's OAuth requests go through Microsoft's `common` sign-in endpoint, which needs this multi-tenant-plus-personal option. Picking a narrower option here is the most common way this integration fails to authorize.
4. Under **Redirect URI**, choose platform **Web** and enter the exact Outlook redirect URI from [Prerequisites](#prerequisites) above.
5. Register the app, then note the **Application (client) ID** on the Overview page.
6. **API permissions → Add a permission → Microsoft Graph → Delegated permissions**: add **Calendars.Read**. (`openid` and `offline_access` are requested automatically at connect time and don't need to be added here.)
7. **Certificates & secrets → New client secret**: create one and **copy the secret's *value* immediately** - Azure only shows it once.
8. In Tessera's `.env`:
   ```
   OUTLOOK_CLIENT_ID=<application (client) id>
   OUTLOOK_CLIENT_SECRET=<client secret value>
   ```
9. Restart the container.
10. In Tessera, go to **Settings → External calendars** and click **Connect Outlook Calendar**. Sign in and approve, and you'll land back in Tessera with an "Outlook Calendar connected" confirmation.

## After connecting

- Tessera polls every **15 minutes** by default (`refresh_interval_minutes`) - the current UI doesn't expose changing this at connect time; disconnecting and reconnecting is the only way to change it today (see [Configuration](configuration.md#external-calendar-connections)).
- The connection's card in Settings shows a "Last synced" timestamp - use it to confirm sync is actually running.
- Access is **read-only**: Tessera never creates, edits, or deletes anything on your Google/Outlook calendar.
- To stop syncing a calendar, click **Disconnect** next to it in Settings - this revokes the stored token and cancels the poll job.
- If something isn't showing up as blocked, or sync looks stuck, see [FAQ & Troubleshooting](faq.md#calendar-sync).

## A note on verification

The exact redirect URI, scopes, and parameters above are taken directly from Tessera's provider client code (`backend/app/calendar_sync/providers/`), so they're accurate to what the app actually sends. The Google/Microsoft console steps follow each provider's standard OAuth app registration flow as of this writing - both consoles change their UI periodically, so if a menu has moved, look for the equivalent option (the underlying concept - register an app, get a client ID/secret, set a redirect URI, grant a read-only calendar scope - won't change even if the exact button does).
