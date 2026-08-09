# Capabilities

A tour of what Tessera actually does. For the mechanics of any one piece, see the linked deep-dive page.

## Auto-placement of flexible tasks

The core value proposition: you tell Tessera a task's duration, priority, and deadline; it finds a slot. Placement respects your active-hours windows, blackout dates, daily time budget, everything already on the timeline (fixed tasks, other scheduled flexible tasks, external calendar events), and task dependencies - and it does this incrementally, as an event fires, not as a periodic batch job. See [Scheduling Algorithm](scheduling-algorithm.md) for exactly how a slot gets chosen.

## Two task types, one editing model

**Fixed** tasks happen at a time *you* choose and are never moved by the algorithm - creating one that collides with something else is rejected outright, not silently double-booked. **Flexible** tasks get a deadline instead of a time, and Tessera finds the time. Both come from **recurring templates** if you want them to repeat, with independent recurrence patterns and a choice of what "the next one" anchors against. See [Tasks & Events](tasks-and-events.md).

## Task dependencies

A task can depend on one or more other tasks. Until every dependency is actually **completed** (not just scheduled), the dependent task is `blocked` and never appears on the timeline - it shows up instead in a dedicated **Backlog view**, navigable in both directions ("what's blocking this" and "what does this block"). The moment the last dependency completes, the dependent unblocks and gets placed in the same transaction - no polling delay.

## Daily capacity, not just free/busy

Most calendar tools only know "busy" or "free." Tessera additionally tracks a **daily time budget** for flexible work, so a day doesn't quietly become wall-to-wall chores just because there happened to be gaps in it. The budget is a soft cap by default - it yields only as a last resort to avoid missing a deadline - or a hard wall if you set `budget_enforcement: strict`.

## Recurrence with a real semantics for "when's the next one"

Recurring templates support `one_time`, `daily`, `weekly`, `monthly`, and `custom` patterns, plus - the part most calendar apps don't offer - a choice of **anchor**:

- **`calendar`** - the next occurrence lands where the rule says, on schedule, regardless of whether you ever did the previous one. Right for rigid commitments ("team sync every Monday").
- **`completion`** - the next occurrence is generated relative to when you actually finished the last one. Right for upkeep work ("replace the filter a month after I actually replaced it last"), and only available on flexible templates, since it needs a deadline window to slide within.

## Per-occurrence edits without breaking the series

Editing or rescheduling one occurrence of a recurring task doesn't force a choice between "change the whole series" or "lose your recurrence." Tessera's two-scope edit model lets you override a single occurrence (it becomes `detached` and stops receiving future template edits) while the template - and every future occurrence - carries on unaffected. See [Tasks & Events](tasks-and-events.md#detach-and-edit-scope).

## Notifications that map to real conditions, not noise

Eight distinct notification types - reminders, creation conflicts, sync conflicts, unschedulable tasks, at-risk dependencies, overdue tasks, budget overrides, missed deadlines - each tied to a specific condition, and each (except the purely informational `budget_exceeded`) **auto-resolves** the moment its underlying condition clears, rather than sitting there until you manually dismiss something that's no longer true. See [Notifications](notifications.md).

## External calendar sync

Connect Google Calendar or Outlook and Tessera polls them on an interval you set, caching events locally so scheduling stays fast and works even if the provider is briefly unreachable. Synced events become obstacles the algorithm won't schedule over - with two POC filtering rules that keep this from being over-aggressive:

- Events you've marked **"Free" / transparent** on the provider side don't block anything - you told the calendar you're actually available.
- **All-day events** are imported and shown, but for now are display-only - they don't block flexible placement.

Tessera never writes back to your external calendars - sync is one-way, in.

## Timezone-correct, DST-safe, everywhere

Every date/time computation - active-hours windows, deadlines, the placement grid, day boundaries for budget accounting - runs in your configured IANA timezone (e.g. `America/New_York`), not a raw UTC offset. That's what makes DST transitions handled automatically rather than a source of silent one-hour drift, and it's why a half-hour-offset timezone like `Asia/Kolkata` still gets correctly-aligned scheduling.

## Mandatory authentication, zero cloud dependency

There's no anonymous mode, not even for a trusted LAN deployment - Tessera is a single-user app with a password-protected first-run setup wizard, gated by a one-time token you retrieve from the container logs so nobody else can claim your instance before you do. Sessions carry a 30-day absolute TTL, rotate on login, and are fully revoked on any password change. Everything runs in one self-hosted container; nothing about core functionality depends on an external service.
