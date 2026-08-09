# Notifications

Notifications are a separate concept from task **status** - a task can be `scheduled` and simultaneously have an active `dependency_at_risk` notification. They live in an in-app panel; there's no email or IM push in the current build (see [Project Status & Scope](project-status.md)).

## Types

| Type | Fires when | How it resolves |
|---|---|---|
| `reminder` | A task's scheduled time minus one of its configured reminder offsets is reached | Informational; you dismiss it |
| `creation_conflict` | A fixed task's creation collides with an existing fixed task or external event | The save was already hard-blocked - you must change the time or task type before it can be created at all |
| `sync_conflict` | An external calendar sync introduces an event that collides with an already-`scheduled` fixed task | Manual - reschedule the fixed task or dismiss the notice |
| `unschedulable` | A flexible task's placement search finds no valid slot before its deadline (budget ignored, in soft mode) | Relax the deadline or duration, or intervene manually |
| `dependency_at_risk` | The deadline is within 3 days and at least one dependency is still incomplete | Informational - chase the dependency or adjust the deadline |
| `overdue` | A task's scheduled time has passed without it being marked complete | Flexible tasks auto-reschedule (informational notice); fixed tasks get an action menu - reschedule, mark complete, or skip this occurrence |
| `budget_exceeded` | A flexible task was placed by overriding its day's time budget as a last resort | Informational only - the one type that never auto-resolves, since it records something that already happened rather than an ongoing condition |
| `deadline_missed` | A flexible task's deadline elapses while it's still `pending` or `blocked` | Extend the deadline, mark complete, or delete the instance/template |

## Auto-resolution

Every type except `budget_exceeded` **auto-resolves** the moment its underlying condition clears on its own - a `dependency_at_risk` notice clears itself if the dependency completes in time; a `sync_conflict` clears itself if the colliding external event is later removed; a `deadline_missed` notice clears itself if you extend the deadline. If you open a notification that's already auto-resolved, you'll see an "already resolved" state rather than stale action buttons for a condition that no longer exists.

`budget_exceeded` is the one exception: it's a record of something that already happened, not a condition to watch, so it's dismissed like an ordinary notice instead.
