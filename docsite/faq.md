# FAQ & Troubleshooting

## Setup & login

**I can't find the setup token.**
It's logged at `WARNING` level on startup, only while zero accounts exist: `podman logs tessera` or `docker logs tessera`. If you've lost it or the container's been running a while, just restart the container - a fresh token is generated every time it boots with no accounts, and the old one was never persisted anywhere to go stale.

**The setup screen says the endpoint is gone (410).**
That means an account already exists. Setup is one-time by design - go to the login screen instead. If you genuinely need to start over, that means wiping the database, which also wipes all task history.

**I'm locked out and don't remember the password.**
Set `RESET_ADMIN_PASSWORD` in `.env` and restart the container - see [Getting Started](installation.md#password-recovery). It only fires once per value; changing the value again forces another reset.

**Login works but I keep getting logged out unexpectedly.**
Sessions are absolute-TTL (30 days from issue, no idle extension) and are revoked entirely on any password change or reset. If you just reset the password, that's expected - log in again.

## Deployment

**The container won't start / crashes immediately.**
Check that `SECRET_KEY` is actually set to something in `.env` - it's the one genuinely required variable. Also confirm `DATABASE_PATH` points somewhere writable inside the container (the default, `./data/tessera.db`, assumes the compose file's volume mount is in place).

**Login works on `http://localhost` but not behind my reverse proxy / HTTPS domain.**
Set `APP_BASE_URL` to the externally-visible URL and leave `SESSION_COOKIE_SECURE=auto` - it derives the cookie's `Secure` flag from that URL's scheme. Hardcoding `SESSION_COOKIE_SECURE=true` will silently break login on plain HTTP.

**I restarted/updated the container and lost all my data.**
The SQLite database must live on a mounted volume (the provided `docker-compose.yml` already does this via the `tessera_data` volume). If you changed `DATABASE_PATH` or removed the volume mount, the database was living in the container's writable layer and didn't survive the recreate. Restore from a backup of the volume if you have one, and fix the mount going forward.

## Scheduling

**I created a flexible task and it just... never got scheduled.**
Check the Notifications panel and the Backlog view. If it has an active `unschedulable` notification, every eligible day before its deadline is booked solid - relax the deadline, shorten the duration, or free up a day. If it's sitting `blocked` instead, it has an incomplete dependency.

**A task I created was rejected outright.**
- `creation_conflict` - a fixed task collided with something at save time; fixed tasks are hard-blocked on conflict, never silently double-booked.
- `infeasible_duration` - a flexible task's duration can't fit any day's active-hours window under any circumstance; shorten it or widen your active hours.
- `invalid_recurrence_anchor` - you set `anchor: completion` on a fixed template; completion-anchoring is flexible-only, since it needs a deadline window to slide within.

**I edited a recurring task but the change didn't show up on later occurrences (or vice versa).**
Check whether the instance you edited is marked `detached`. A "this occurrence" edit (or a manual fixed-task reschedule) detaches that single instance from the template permanently - future template-wide edits skip it entirely. See [Tasks & Events](tasks-and-events.md#detach-and-edit-scope).

**I completed a recurring task and the next one was scheduled weeks away.**
If the task is `completion`-anchored, that's expected: the next occurrence is due one cadence after you finished, and it isn't scheduled before then. See [Tasks & Events](tasks-and-events.md#anchoring-calendar-vs-completion).

**Why didn't Tessera just move an earlier task to make room for a new one?**
It never does - placements are never moved by a later scheduling pass, on purpose. See [Scheduling Algorithm](scheduling-algorithm.md#incremental-fit-not-a-reflow).

## Calendar sync

**Synced events aren't blocking my flexible tasks.**
Check whether they're marked "Free"/transparent on the provider side, or are all-day events - both are intentionally excluded from blocking flexible placement. See [Capabilities](capabilities.md#external-calendar-sync).

**How fresh is the synced calendar data?**
As fresh as your configured `refresh_interval_minutes` in Settings - Tessera polls, it doesn't get pushed live updates. The UI should show a "last synced" timestamp; if sync looks stuck, check that the connection's OAuth credentials haven't expired.

## Something not covered here

Check the [design document](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/design-doc.md) for the full specification, or open an issue on [GitHub](https://github.com/EnthusiastDeveloper/Tessera/issues).
