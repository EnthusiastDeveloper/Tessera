# Scheduling Algorithm

This page explains how Tessera decides *when* to place a flexible task. It's a deliberately simple, deterministic, greedy algorithm - not an optimizer - and understanding its shape will save you some surprise.

## It's event-driven, not a periodic sweep

Placement runs whenever something changes that could affect it: a new flexible task is created, an external sync or an overdue check invalidates an existing placement, a dependency completes and unblocks a downstream task, or a "this and future" template edit changes a non-detached instance's duration or deadline in a way that invalidates its current slot. There's no "runs every 5 minutes" batch job to wait on.

## Incremental fit, not a reflow

**This is the most important thing to understand about the algorithm:** a scheduling pass places only the new or changed task into gaps left by everything already committed. **Existing placements are never moved by a later pass.** Adding a task never silently reshuffles what's already on your timeline.

The consequence - accepted as correct behavior, not a bug - is what the design doc calls **greedy corner-painting**: a later task can come back `unschedulable` even though some global rearrangement of the week *would* have fitted it. The alternative (a scheduler that quietly moves things you've already planned around) is worse. A user-triggered "re-optimize everything" reflow is a possible future feature, not something the core algorithm does.

## What counts as an obstacle

When looking for a free slot, the algorithm treats all of the following as occupied time:

- Every `TaskInstance` currently `scheduled` or `in_progress` - **both** fixed and flexible
- Every flexible task already placed earlier in the *same* pass (so a single event that unblocks several tasks at once doesn't double-book them against each other)
- External calendar events (after the transparent/all-day filtering rules - see [Capabilities](capabilities.md#external-calendar-sync))

## The two-pass placement

For each pending flexible task, in order of deadline (soonest first), then priority:

**Pass 1 - respect the daily budget.** Search for the first slot, on or after the task's earliest possible start (now, or the moment its last dependency completed), before its deadline, inside that day's effective active-hours window, that doesn't push the day's committed flexible-task minutes over `daily_time_budget_minutes` for that day of week.

**Pass 2 - only if Pass 1 finds nothing, and only in `soft` budget-enforcement mode.** Ignore the budget and look at every day between now and the deadline that has a *physically* free slot of sufficient length (active hours and blackout dates still apply - only the budget is relaxed). Among those days, pick the one that:

1. Minimizes overage (how far over budget placing the task there would push that day)
2. On a tie, maximizes remaining free capacity afterward (prefer leaving a day less "wall-to-wall")
3. On a further tie, picks the earliest date

If a slot is found this way, the task is placed and gets a `budget_exceeded` notification - informational, not an error.

If **neither pass** finds a slot, the task stays `pending` and gets an `unschedulable` notification. In `strict` budget mode, Pass 2 never runs at all - a Pass 1 failure goes straight to `unschedulable`.

## The placement grid

Computed start times land on a **15-minute grid, aligned to the hour, in your local wall-clock time** (`:00`, `:15`, `:30`, `:45`) - never in UTC, which would misalign for half-hour-offset zones like `Asia/Kolkata`. This only constrains *computed* starts: fixed tasks sit exactly where you put them, and external events keep their real times, so the gaps between obstacles can still have arbitrary boundaries.

**Durations themselves are never quantized** - a 20-minute task placed at 18:00 occupies exactly 18:00–18:20, and budget arithmetic stays exact down to the minute.

## Feasibility is checked once, at creation

Before a flexible task is ever a candidate for placement, its `estimated_duration_minutes` is validated against the largest active-hours window across all applicable days (measured from the first grid point, not the raw window edge). If it could never fit *any* day under *any* circumstance, the save is rejected outright with `infeasible_duration` - you find out immediately, not after it silently fails to schedule for two weeks straight.

This is a different failure mode from `unschedulable`: a task can be feasible in principle (it *could* fit some day) but still come back `unschedulable` in practice because every eligible day happens to be booked solid before the deadline.

## Worked examples

These are drawn directly from the design document's acceptance-test fixtures (all times `America/New_York`, 15-minute grid):

**Merged per-day override.** Global active hours are 18:00–21:00 every day; a monthly "Replace HVAC filters" task overrides only Tuesday to 18:00–22:30. Monday's window is still the *global* 18:00–21:00 (inherited, since the override didn't name it) - a whole-map replacement would have wrongly opened every day to the override, or closed every day but Tuesday.

**Budget yields to a deadline.** Saturday's budget is 180 minutes and already has 150 minutes scheduled. A 90-minute task with a deadline that same day fails Pass 1 (`150 + 90 = 240 > 180`), so Pass 2 retries ignoring the budget, finds Saturday physically free from 11:30 onward, and places it there with a `budget_exceeded` notification recording the 60-minute overage.

**Pass 2 picks the least-damaging day, not the earliest.** Sunday has a free slot with 10 minutes of budget headroom; Monday has one with 17 minutes of headroom. For a 20-minute task, Sunday's overage (10 minutes) is *worse* than Monday's (3 minutes) - Monday wins the tie-break despite coming second chronologically.

**Feasibility hard block.** Active hours are 180 minutes every day, no overrides. Creating a flexible task with a 300-minute estimated duration is rejected at save time with `infeasible_duration` - no day-of-week could ever hold it as a single block, so there's no point letting it become `unschedulable` forever instead.

**Dependency unblock.** "Prepare car for inspection" (flexible, 120 min) has "Perform annual inspection" (flexible, 90 min) depending on it. The inspection task is `blocked` and sits in the Backlog view - not the Timeline - until the prep task is marked `completed`. The moment that happens, in the same transaction, the inspection task flips to `pending` and is placed by the algorithm using the actual completion timestamp as its earliest start.

For the complete, exhaustive set of worked examples (including sync-eviction, dismissed-and-regenerated recurrence, and completion-anchored recurrence), see [Section 10 of the design document](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/design-doc.md).
