# Tasks & Events

## The core model: templates and instances

Every schedulable item in Tessera is a **`TaskInstance`**, generated from a **`TaskTemplate`**. Even a plain one-time task has a template behind it - it just has `recurrence: one_time` and generates exactly one instance immediately.

The template holds recurrence rules and defaults (name, priority, duration, deadline offset, etc.); the instance is the actual schedulable/completable unit with its own status, scheduled time, and history. This split is what lets a recurring task have a fresh, independent instance each cycle while the template keeps defining what "the next one" looks like.

## Fixed vs. flexible

| | Fixed | Flexible |
|---|---|---|
| You specify | An exact time (`fixed_time_of_day`) | A deadline offset |
| Tessera specifies | Nothing - it's exactly where you put it | The scheduled time, via the placement algorithm |
| Conflict with something else | **Hard-blocked at creation** - save is rejected (`creation_conflict`), nothing is created | N/A - the algorithm finds a free slot or reports `unschedulable` |
| Bound by active hours / budget | No - never constrained by your scheduling window | Yes - the whole point of the setting |
| Still counts against the daily budget | Yes - a fixed task's duration counts toward the day's cap even though it isn't *placed* by the algorithm | Yes |

## Recurrence

Templates support five patterns: `one_time`, `daily`, `weekly`, `monthly`, and `custom` (interval-based, e.g. every 2 weeks; weekly/monthly patterns also take a day-of-week or day-of-month).

### Anchoring: `calendar` vs. `completion`

Every non-one-time template picks an **anchor**, which decides where the *next* occurrence lands:

- **`calendar`** - the next occurrence is generated at the next date the recurrence rule produces, full stop, independent of whether the previous occurrence was ever completed. Use this for rigid commitments like a weekly meeting - if you missed last Monday's, next Monday's still shows up on schedule, and you clear the stale one with **skip this occurrence** (below).
- **`completion`** - the next occurrence is generated at `completed_at + cadence`, i.e. relative to when you actually finished the previous one. Use this for upkeep work that should shift with reality ("replace the filter a month after I actually did it last," not a month after some date I never got to).

`anchor: completion` is **only valid on flexible templates** - saving it on a fixed template is rejected with `invalid_recurrence_anchor`. The reason is structural: completion-anchoring means "this occurrence can slide within a window," and that window is the deadline offset a flexible task has and a fixed task doesn't.

## Status lifecycle

```
pending → scheduled → in_progress → completed   (terminal)
   ↑           ↓
   └── blocked (has incomplete dependencies)
```

Plus two more:

- **`missed`** - a *flexible* task whose deadline elapsed before it was ever scheduled or completed. It's pulled out of the scheduling pool until you act on it (extend the deadline, mark complete, or delete it).
- **`dismissed`** - terminal, reachable from any non-terminal status via **"skip this occurrence."** It means "this one isn't happening" - distinct from completing it.

Key rules:

- Only `pending` instances are candidates for auto-placement. A task with unfulfilled dependencies starts life `blocked`, not `pending`, and never enters the algorithm until it unblocks.
- A fixed task with no unfulfilled dependencies goes straight to `scheduled` at creation - it never enters the algorithm at all, since its time is yours to set.
- `completed` is reachable directly from `pending`, `blocked`, or `scheduled`, not only via `in_progress` - covering "I already did this, don't bother scheduling it." `in_progress` is always optional.
- **Neither `missed` nor `dismissed` satisfies a dependency.** A task depending on one that was missed or dismissed stays `blocked` until the upstream instance is actually completed, or the dependency link is removed.

## Dependencies

A task can list other `TaskInstance`s it depends on. It cannot enter the scheduling pool (or be manually started) until **every** dependency has reached `completed`. There's no priority-based "start anyway" override in the POC - the gate is absolute.

Because a candidate only becomes eligible for scheduling once all its dependencies are actually completed, the algorithm never needs to reason about partially-finished dependency chains or run a topological sort - by the time a task is a candidate, everything it depends on is already done.

Deleting a task that others depend on doesn't cascade: the dependency link is simply removed from the dependent(s), which may unblock them.

## Skip vs. delete: two different intents

These look similar but mean different things, and Tessera keeps them distinct:

| Action | Meaning | What happens to the row |
|---|---|---|
| **Skip this occurrence** (dismiss) | "This one isn't happening." The routine way to clear a stale recurring occurrence. | Preserved, status becomes `dismissed` (terminal) |
| **Delete → this occurrence** | "Remove this from my records." Exceptional. | Row destroyed; series continues, next occurrence generated normally |
| **Delete → this and future occurrences** | "End this series." | Row destroyed, template archived |

Dismissing (and deleting "this occurrence" on a `completion`-anchored template) still generates the successor - otherwise a completion-anchored series would silently die the first time an occurrence was skipped instead of completed.

Dismissal, like completion, is irreversible. Recovering from a mistaken skip means creating a new task.

## Detach and edit scope

Editing a recurring task asks **which scope** you mean:

- **"This occurrence"** - changes only the live instance (name, duration, priority, deadline/scheduled time, etc.). Sets `detached = true` on that instance. The template, and every future occurrence, is unaffected.
- **"This and future occurrences"** - edits the template, and - unless the current live instance is already `detached` - also applies the same change to it immediately, in the same operation.

  Two template fields reach the live instance indirectly:

  - Changing a fixed task's **time of day** moves the live occurrence to the new time on the same date. If the new time collides with another fixed task or a busy external event, the whole edit is rejected - the same hard block as creating the task there.
  - Changing a flexible task's **deadline offset** moves the live occurrence's deadline by the same amount. If its current slot still finishes in time it stays put; otherwise it's re-placed, and a deadline that has already passed sends it straight to `missed`. An occurrence that is already `missed` is left for you to resolve.

Once an instance is `detached`, it's skipped **entirely** by future template-wide edits (not just the field you originally overrode) until it reaches `completed`. A manual reschedule of a fixed task works the same way: it's a "this occurrence" edit and sets `detached = true`.

The UI should always show you when an instance is detached - it's the reason a template-wide edit didn't land on a specific occurrence you're looking at.

## Deadline extension for missed tasks

A `missed` flexible task doesn't just sit there - you extend its deadline (which is itself a "this occurrence" edit, so it detaches), and it returns to `pending` and gets placed on the next scheduling pass.

## External calendar events

Events synced from Google/Outlook aren't "tasks" - they're opaque busy-blocks Tessera treats as obstacles, with two filtering rules (see [Capabilities](capabilities.md#external-calendar-sync)):

- Events marked **"Free"/transparent** by the provider don't block anything.
- **All-day events** are shown but don't block flexible placement (display-only for now).

If a synced event collides with an already-scheduled fixed task, Tessera raises a `sync_conflict` notification rather than silently moving or deleting anything - you resolve it manually.
