# Tessera - Implementation-Readiness Review #2 (IRR-2)

**Reviewer role:** independent spec/architecture audit, pre-implementation.
**Date:** 2026-08-05
**Documents under review:** `design-doc.md` (Rev 8), `architecture-plan.md` (Rev 2), `implementation-plan.md` (companion to those two).
**Repo state at review:** Stage 0 merged to `main` (commit `28c2104`). No business logic exists yet.

## 0. How to use this document

This is the same kind of artifact that produced design-doc Revision 6 - an implementation-readiness pass whose output is a findings list, not edits. Nothing here has been applied to the design doc, because design-doc Section 0 forbids unilateral changes to a locked spec. Findings are grouped by severity and each carries an explicit **Disposition** telling you whether it needs a product decision or is a safe correction.

Severity meanings:

| Severity | Meaning |
|---|---|
| **BLOCKER** | An implementer following the spec literally would build something wrong, or would stop because the spec doesn't say. Must be resolved before the stage that consumes it. |
| **HIGH** | Real defect or gap. Will produce a bug, a bad user outcome, or a stalled implementation, but a competent implementer would probably notice and ask. |
| **MEDIUM** | Underspecified. Will be resolved by implementer guesswork if left alone, producing behavior nobody signed off on. |
| **LOW** | Editorial, stale cross-reference, or doc-vs-reality drift. No behavior impact. |

Verdict summary: **the docs are unusually strong on scope discipline, traceability, and process** - genuinely better than most pre-implementation specs. The defects cluster in three places: (1) the recurrence engine, which is the least-specified load-bearing feature; (2) the obstacle/conflict model in §6.2, which has a concrete correctness bug; (3) the security and persistence surface, which is thinner than the rest of the document and contains one deployment-breaking contradiction.

### Decision log

Findings resolved by the stakeholder since this review was filed. The decision text lives with the finding; each is **decided but not yet drafted** into the design or architecture documents, so the finding still gates its stage until the corresponding revision lands.

**Every finding gating Stages 1, 2 and 3 is now decided** - all twelve blockers (B1–B12), plus H1, M7, M9 and M10. What remains open is the High-severity set from H2 onward (Stage 5 and Stage 6), the rest of Section 3's Medium findings, and the editorial items in Section 4. None of those contradict the decisions below, so Revision 9 can be drafted without waiting on them.

| Finding | Decided | Summary of the decision | Drafting vehicle |
|---|---|---|---|
| B2 | 2026-08-05 | Recurrence anchoring becomes a per-template `anchor` field: `calendar` (rigid) or `completion` (`completed_at` + cadence). `completion` is valid only on flexible templates and is rejected at save on fixed ones. Completion-anchored flexible tasks use `deadline_offset` as the completion window. Timeline projects assuming on-time completion, or `today + cadence` when already behind. | design-doc Rev 9 (§3.2, §9.1, §9.2) |
| B1 | 2026-08-05 | Follows from B2: `calendar` templates generate on the occurrence boundary and allow multiple live instances, with a user-facing **dismiss** action for stale ones; `completion` templates keep completion-triggered generation, and stalling when incomplete is intended behaviour. | design-doc Rev 9 (§3.3, §4, §9.1) |
| B1 (deletion) | 2026-08-06 | Deleting a recurring instance prompts for scope, mirroring §3.10's edit-scope prompt: `this_occurrence` (series continues) or `this_and_future` (template archived). Applies to both task types and both anchor modes. `DELETE /task-instances/{id}` gains a `scope` parameter. | design-doc Rev 9 (§3.8), arch Rev 3 (§3 API contract) |
| B3 | 2026-08-06 | Placement is an **incremental fit**, not a full reflow: existing placements are never moved by a later pass. Obstacle set corrected to all instances in `scheduled` or `in_progress` (both types) plus intra-pass placements plus filtered external events. Greedy corner-painting is accepted behaviour. | design-doc Rev 9 (§6.2) |
| B4 | 2026-08-06 | Per-day `null` always means "day excluded", in globals and overrides alike. Absent `active_hours_override` inherits the global map. A partial override **merges** per-day rather than replacing the map. "Unrestricted" is an explicit `00:00`–`23:59` window. §6.2's whole-object selection is replaced by per-day resolution. | design-doc Rev 9 (§3.2, §3.7, §6.2, §6.8) |
| B8 | 2026-08-06 | `Duration` is an integer count of **minutes**, elapsed semantics, in storage and on the wire; fields renamed to carry the unit. The DST-inexact `deadline_offset` is an accepted simplification. **UI must offer value-plus-unit entry and human-readable display** - the user never enters or reads raw minutes. | design-doc Rev 9 (§3.2, §3.3, §3.7, §8.1, §14.1) |
| B9 | 2026-08-06 | Placement uses a **15-minute grid aligned to the hour**, in local wall-clock time. Durations stay unquantised and obstacles use exact end times. Fixed instances and external events are not quantised. §6.8 feasibility must measure from the first grid point in the window. | design-doc Rev 9 (§6.2, §6.8, §10) |
| H1 | 2026-08-06 | Revision 8's `blocked` gate is kept and the topological sort is **deleted**; dependents auto-schedule when the last dependency completes. Their invisibility is solved by a **Backlog view** (a filtered query over `blocked`/`unschedulable`/`missed`, not a new entity), with bidirectional dependency navigation - which forces `dependencies` to become a **join table**. Deadlines stay fixed points in time, so a backlog task can reach `missed` while blocked. `dependency_at_risk` uses a speculative, non-persisting pass. *(Reverses an earlier same-day decision to place dependents on known times; the cascade machinery that required is dropped entirely.)* | design-doc Rev 9 (§3.3, §3.4, §6.1, §6.2, §8.1, §10), arch Rev 3 (§4.1) |
| M7 | 2026-08-06 | Worked Examples A/B/C/E are rewritten as fixture tables, **and G–K are re-derived** against this session's decisions, as part of the Rev 9 drafting pass. A new example covers a dependency chain. | design-doc Rev 9 (§10), arch Rev 3 (§8) |
| B5 | 2026-08-06 | `TaskInstance` gains `created_at`, `updated_at` and a monotonic integer **`version`**. `version` is the concurrency token (incremented at the ORM layer so no write path can skip it); `updated_at` is display/audit only. Architecture §5/§5.1 switch from the timestamp to `version`. `TaskTemplate` gets the same. | design-doc Rev 9 (§3.2, §3.3), arch Rev 3 (§5, §5.1) |
| B6 | 2026-08-06 | **Expected-values PATCH**: the client sends the value it read for each field it changes; the server compares only those fields and merges onto the current row, so concurrent job writes to untouched fields survive. No retry loop on either side. Amends B5 - `version` guards the write but is no longer the client-facing token. Requires genuinely partial PATCHes from the frontend. | arch Rev 3 (§3, §5, §5.1) |
| B7 | 2026-08-06 | Add an **`ExternalEvent`** entity, unique on `(connection_id, provider_event_id)`, cached locally so the engine never makes a network call. Rolling **90-day** fetch horizon, **30-day** past retention, **soft deletes** so `sync_conflict` can auto-resolve. Retention covers the event cache only - **`TaskInstance` rows are never purged**, which Rev 9 must state outright. | design-doc Rev 9 (§3, §3.3, §6.4, §7), arch Rev 3 (§2) |
| B10 | 2026-08-06 | **First-run setup wizard** (`POST /api/v1/auth/setup`, `410 Gone` once an account exists), not an env-var bootstrap - the wizard UI is the durable artifact and a token can harden it later. Username fixed as `admin`, 12-char minimum password. `RESET_ADMIN_PASSWORD` becomes recovery-only, which makes arch §7.1's "Optional" label correct. **Setup token recommended in the same Stage 3 work** to close the claim window. | design-doc Rev 9 (§3.6, §8.1, §14.2), arch Rev 3 (§3, §6, §7.1) |
| M9 | 2026-08-07 | **30-day absolute session TTL**, no idle timeout. Rotation on login; **all sessions revoked on any password change or reset** (without which `RESET_ADMIN_PASSWORD` locks nobody out); lazy cleanup of expired rows at login; distinct `401` code for expiry. | arch Rev 3 (§6) |
| M10 | 2026-08-07 | Auth guard is **middleware with an explicit public allowlist** (default-deny), plus a test enumerating every route. Public: `/health` (minimal payload), static assets and SPA routes, login, setup. **Not** carve-outs: the OAuth callback (requires a session - what `SameSite=Lax` was chosen for) and logout. `/docs`, `/redoc`, `/openapi.json` disabled in production. | arch Rev 3 (§3, §6) |
| B12 | 2026-08-07 | **`SameSite=Lax` alone**, no CSRF token - `Lax` covers every mutation, and a token can be added later without an API break. `Lax` **not** `Strict`, deliberately: `Strict` would withhold the cookie on the OAuth callback's cross-site top-level navigation and break calendar sync. Plus two safe corrections: no state-changing `GET`, and a mandatory OAuth `state` check. | arch Rev 3 (§3, §6) |
| B11 | 2026-08-05 | Plain-HTTP LAN is a fully supported deployment. `SESSION_COOKIE_SECURE=auto\|true\|false`, default `auto`, derived from the `APP_BASE_URL` scheme, with a mandatory `WARNING` at startup when it resolves to insecure. `HttpOnly` and `SameSite=Lax` unconditional. | architecture-plan Rev 3 (§1, §3, §6, §7.1), impl-plan Stage 3, `.env.example`, README |

---

## 1. Blockers

### B1 - Recurring-instance generation dead-ends on any non-completion path
**Where:** design-doc §9.1, §6.6, §6.7, §3.8
**Finding:** §9.1 generates the next instance *only* when the current one reaches `completed`. `completed` is not the only terminal-ish outcome an instance can reach:
- A flexible instance that goes `missed` (§6.7) never completes → the template never generates again.
- A fixed instance whose `scheduled_time` passes un-checked-off stays `scheduled` forever (§6.6 leaves status unchanged) → the template never generates again. A user who forgets to tick off one Monday stand-up silently loses every future Monday stand-up.
- Deleting the live instance (§3.8, `DELETE /task-instances/{id}`) removes the only thing that could ever trigger generation. §3.8 defines what happens to *dependents* of a deleted instance but never what happens to its *template*.
- An instance sitting `blocked` on a dependency that is itself never completed has the same effect.

**Why it matters:** recurring tasks are a headline feature (README, §2 scope table). The failure is silent - no notification, no error, the task just stops existing. This is the single highest-impact defect in the spec.
**Recommendation:** define generation as triggered by the live instance reaching **any terminal disposition** - `completed`, `deleted`, or an explicit user "skip this occurrence" - and add an explicit rule for the two stuck states (`missed` flexible, past-due `scheduled` fixed).

**Stakeholder decision (2026-08-05) - largely resolved by the anchor-mode decision in B2:**
- **`calendar`-anchored templates** take option (a): generation fires on the occurrence boundary regardless of the prior instance's state. Multiple live instances are allowed, and the user can **dismiss** a stale one. None of the four dead-ends in this finding apply, because generation no longer depends on the predecessor at all.
- **`completion`-anchored templates** keep completion-triggered generation, and the stall is *intended* (B2 consequence 2). A `missed` or perpetually-`blocked` filter-change still needs doing; the correct behaviour is that it stays outstanding rather than that a second one appears.

**Deletion scope - stakeholder decision (2026-08-06):** deleting an instance of a recurring template prompts the user for a **scope**, mirroring the edit-scope prompt in §3.10 rather than inventing a second mental model:

| Scope | Effect |
|---|---|
| `this_occurrence` | Delete the live instance only. The series continues and the successor is generated. |
| `this_and_future` | Delete the live instance and end the series - the template is `archived` (§3.2 already defines archival as the soft-delete path for templates with history). |

This applies to **both** task types and **both** anchor modes. The rationale is the same as §3.10's: the user knows which one they mean, and guessing on their behalf is the worse failure.

Consequences Rev 9 must state:
- `DELETE /api/v1/task-instances/{id}` takes a `scope` parameter (`this_occurrence` | `this_and_future`), matching the `PATCH` scope contract. For a non-recurring (`one_time`) template the prompt is skipped and the two scopes are equivalent.
- §3.8's dependency-unlink rule is unchanged and applies to whichever instances are removed.
- **Re-anchoring on `this_occurrence` for a `completion`-anchored template:** deleting is not completing, so there is no `completed_at` to anchor from. Recommend anchoring the successor at `now + cadence` - the user has explicitly declined to do this one, so restarting the interval from the decision point matches the intent better than pretending it happened on the old nominal date.

**Residual, still needs a rule:** `dismiss` must be added to the status model as a terminal disposition distinct from `completed` and from delete - §4's state diagram and §3.3's `status` enum both need it. Note also that `dismiss` and `delete (this_occurrence)` now have nearly identical effects; Rev 9 should decide whether they remain two actions (dismiss preserving the row for history, delete removing it) or collapse into one.
**Disposition:** decided; one residual rule above. Blocks Stage 5.

### B2 - Recurrence anchoring is undefined, and `recurrence` has no effect at all on flexible tasks
**Where:** design-doc §3.2 (`recurrence`), §9.1, §9.2
**Finding:** two distinct gaps.

*(a) Anchor:* when instance N completes, §9.1 says to generate instance N+1, but never says what date/time N+1 lands on. If a weekly Monday task is completed on a Wednesday, is N+1 the following Monday (calendar-anchored) or Wednesday + 7 days (completion-anchored)? If it's completed three weeks late, do you generate the occurrence that was already due, or skip forward to the next future one? §9.2's virtual projection says it projects "forward from the most recently generated/completed real instance" - which inherits the same ambiguity, and if the projection and the real generator disagree, the Timeline actively lies to the user.

*(b) Flexible + recurrence is a contradiction as written:* a flexible instance has no `scheduled_time` at generation - only a `deadline`, computed as `deadline_offset` after generation (§3.2). Generation fires on completion of the prior instance. So a "weekly" flexible chore completed on Monday generates its successor immediately on Monday with a deadline of Monday + `deadline_offset`, and the scheduler places it as soon as possible. **The `weekly`/`interval` fields have no effect whatsoever on a flexible task.** A weekly chore becomes an as-fast-as-you-finish-them chore. This will be visibly wrong to a user on day one.

**Recommendation:** define a recurrence anchor explicitly. For flexible tasks, define the occurrence's nominal date as the earliest-start gate - i.e. instance N+1 is not eligible for placement before its occurrence date, and its `deadline` is `occurrence_date + deadline_offset`. Add a worked example for a recurring flexible task; there currently isn't one.

**Stakeholder decision (2026-08-05) - resolved, pending drafting into Rev 9:**

Anchoring is a **per-template choice**, not a single global rule. `recurrence` gains an `anchor` field with two modes:

| Mode | Next occurrence lands at | Motivating case |
|---|---|---|
| `calendar` | the next date the recurrence rule produces, independent of when (or whether) the prior instance completed | weekly team sync, birthdays, a concert |
| `completion` | `completed_at` + cadence | replace the HVAC filter monthly - completed on the 7th, next one is due the 7th of the following month, not the 1st |

Consequences that follow, and which Rev 9 must state:
1. **Stale predecessor:** under `calendar`, generation is driven by the occurrence boundary, so an un-completed predecessor does not block it. **Both instances stay live**, and the user gets an explicit action to dismiss the older one. "Dismiss" therefore becomes a first-class user action with its own terminal disposition (see B1) - it is not a delete, and it is not `completed`.
2. **Completion-anchored tasks are self-throttling by design.** One live instance at a time; if it is never completed, no successor is generated and the live instance simply stays outstanding. That is the intended behaviour, not a dead-end - an un-replaced filter still needs replacing.
3. **Deadline for completion-anchored flexible tasks:** `deadline_offset` is the window the user gives themselves to get it done. The occurrence's nominal date (`completed_at` of the predecessor + cadence) is the earliest-start gate; `deadline = nominal_date + deadline_offset`; the task may be freely rescheduled anywhere inside that window.
4. **`anchor: completion` is valid only on `type: flexible` templates; fixed templates are always `calendar`-anchored.** This is a type constraint, not a policy preference. Completion-anchoring only means anything if the resulting occurrence can be *pushed* within a window, and that window is `deadline_offset` - a field flexible instances have and fixed instances do not (§3.3 sets `deadline` at generation for flexible tasks only; a fixed instance carries `scheduled_time` and nothing to slide against). A fixed task must happen at its defined date and time (meetings, concerts, birthdays), so its recurrence date is not negotiable and there is nothing for a completion date to re-anchor.

   Rev 9 must state this as a **validation rule rejected at template save**, not as prose: `anchor == "completion"` requires `type == "flexible"`. It needs a machine-readable error code alongside the others in architecture §3 (suggest `invalid_recurrence_anchor`). The "car service every 6 months" shape belongs in the flexible model, with `deadline_offset` expressing how long you are willing to let it slip.
5. **Timeline projection (§9.2) for completion-anchored templates:** project assuming on-time completion. If the live instance is already past its nominal date, project from `today + cadence` instead, so the ghost occurrences do not accumulate in the past.

**Disposition:** decided; needs drafting into design-doc §3.2, §9.1 and §9.2 as part of Rev 9. Blocks Stage 5 and Stage 9d until drafted.

### B3 - The §6.2 obstacle set omits already-scheduled flexible instances from prior passes
**Where:** design-doc §6.2 (`obstacles = ...`) and the note "Obstacles accumulate within a single pass"
**Finding:** the obstacle set is specified as *fixed* instances (scheduled) + *flexible* instances scheduled **in this pass** + external busy-blocks. Flexible instances placed in any **previous** pass are not listed. Since the algorithm is event-driven and most passes contain exactly one candidate, essentially every real placement will ignore every previously-placed flexible task, and the scheduler will double-book them on top of each other.

Related: `in_progress` instances are also outside the obstacle set, because the set is keyed on status `scheduled`. A task the user is actively doing can be scheduled over.
**Recommendation:** obstacle set = all instances in status `scheduled` **or** `in_progress` (both types), plus flexible instances placed earlier in the current pass, plus filtered external busy-blocks. The "accumulate within a pass" note then covers only the intra-pass increment.

**Stakeholder decision (2026-08-06) - resolved:**

Placement is an **incremental fit**, not a full reflow. A pass places only the new or changed candidate into the gaps left by everything already committed; existing placements are never moved by a later pass. The obstacle set is corrected to:

```
obstacles = all TaskInstances with status in (scheduled, in_progress)   # both types
          + flexible instances placed earlier in the current pass
          + external busy-blocks surviving the §7 filter
```

Consequences Rev 9 must state:
1. **Placement stability is a product property**, not an implementation detail. Adding a task never silently moves an existing one. This should be written down, because it is the reason the algorithm is allowed to be greedy.
2. **The greedy corner-painting failure mode is accepted behaviour, not a defect.** Because earlier placements are immovable, a later task can be reported `unschedulable` even though some global re-arrangement would have fitted it. Rev 9 should say so explicitly next to the `unschedulable` notification, so it is not later filed as a bug. A user-triggered "re-optimise" reflow is the natural escape hatch and belongs in the backlog (§12), not the POC.
3. `in_progress` joins `scheduled` in the obstacle set under every reading; this part was a straight bug.
4. The "obstacles accumulate within a single pass" note now describes only the intra-pass increment, which is all it was ever doing.

**Disposition:** decided; drafting into design-doc §6.2 (and a sentence in §6.3/§12). Blocks Stage 1 until drafted.

### B4 - `active_hours_override` null semantics contradict `active_hours` null semantics
**Where:** design-doc §3.2 vs §3.7 vs §6.2 vs §6.8
**Finding:** §3.7 defines a per-day `null` in `active_hours` as **"day fully excluded"**. §3.2 annotates `active_hours_override`'s `null` as **"no restriction"** - the exact opposite - for a field with the same shape, consumed by the same code path. §6.2 (`override if override is not None else user_settings.active_hours`) treats an outer `null` as "fall back to global", which matches neither annotation. §6.8's feasibility math ("no day-of-week has a non-null window at all → reject") only makes sense under the *excluded* reading.

Three readings of one field, all present in the locked spec.
**Recommendation:** pick one and state it once: recommend **`null` always means "excluded"** at the per-day level (consistent with §3.7 and §6.8), and **absent/`null` at the outer level means "inherit global"** (consistent with §6.2). If "unrestricted for this day" is genuinely needed (the HVAC-at-22:30 case in Example B), express it as an explicit wide window (`00:00`–`23:59`), not as `null`. Delete the §3.2 annotation.
**Stakeholder decision (2026-08-06) - resolved:**

One meaning for `null`, and overrides **merge** per-day over the global map.

1. **Inner (per-day) `null` always means "this day is excluded"** - identically in `UserSettings.active_hours` and in `TaskTemplate.active_hours_override`. §3.2's "no restriction" annotation is deleted.
2. **Outer absent/`null` `active_hours_override` means "inherit the global map entirely".**
3. **A partial override is a per-day patch, not a replacement.** Days the override names use the override's value; days it does not name inherit the global value.
4. **"Unrestricted on this day" is expressed as an explicit `00:00`–`23:59` window**, never as `null`.

Consequences Rev 9 must state:
- **§6.2's resolution expression is wrong under merge semantics and must be replaced.** `override if override is not None else user_settings.active_hours` selects whole objects; the rule is now resolved per day:
  ```
  effective_hours(template, day):
      if template.active_hours_override is not None and day in template.active_hours_override:
          return template.active_hours_override[day]    # may be null -> day excluded
      return user_settings.active_hours[day]            # may be null -> day excluded
  ```
- **§6.8's feasibility check must run against the merged effective map**, not against the override alone, or a partial override will produce spurious `infeasible_duration` rejections.
- **The API contract must distinguish an absent key from a present-but-null key**, because merge semantics depend on that difference: `{"monday": null}` means Monday is excluded, `{}` means Monday inherits. This is a live trap in Pydantic, where both commonly deserialise to the same thing - the model needs an explicit sentinel or `model_fields_set` check, and Stage 2/Stage 8 need a test for it.
- Example B (HVAC filter at 22:30) is now expressed as a single-day override with an explicit wide window, not as a `null`.

**Disposition:** decided; drafting into design-doc §3.2, §3.7, §6.2, §6.8. Blocks Stage 1 and Stage 4 until drafted.

### B5 - `TaskInstance` has no `updated_at`, but optimistic locking is specified on `updated_at`
**Where:** design-doc §3.3 vs architecture-plan §5
**Finding:** architecture §5 makes optimistic locking via `updated_at` a binding concurrency mechanism for `TaskInstance`. §3.3's schema has `generated_at`, `completed_at`, `scheduled_time` - and no `created_at` or `updated_at`. `TaskTemplate` (§3.2) has both. The mechanism the whole of §5/§5.1 rests on has no field to rest on.
**Recommendation:** add `created_at` and `updated_at` to `TaskInstance`. Additionally, recommend a monotonic integer `version` column as the actual concurrency token rather than a timestamp - timestamp granularity makes two writes inside the same clock tick indistinguishable, which is exactly the background-job-plus-user-edit case §5.1 is about.

**Stakeholder decision (2026-08-06) - resolved:**

`TaskInstance` gains **`created_at`, `updated_at`, and a monotonic integer `version`**. `version` is the concurrency token; `updated_at` is for display and auditing only and must not be used for locking.

1. **`version` starts at 1 and increments on every persisted mutation**, including writes made by background jobs and by template propagation. Any write path that skips the increment silently defeats the mechanism, so the increment belongs in the ORM layer (a SQLAlchemy `version_id_col` or an equivalent mapper-level hook), not in individual service methods.
2. **Every conditional update carries `WHERE id = ? AND version = ?`**, and a zero-row result is the 409 signal.
3. **`version` is exposed on the API** as the concurrency token clients echo back. It replaces `updated_at` in that role throughout architecture §5 and §5.1, which currently name the timestamp.
4. **Rationale for the record:** SQLite's default timestamp resolution makes two writes inside the same tick indistinguishable, and the background-job-plus-user-edit race in §5.1 is precisely the sub-millisecond case. An integer removes the failure mode rather than narrowing it.
5. **`TaskTemplate` should get the same treatment** for consistency, since template propagation writes to both and §3.10's "this and future" edit touches template and instance in one transaction.

**Disposition:** decided; drafting into design-doc §3.2, §3.3 and architecture-plan §5, §5.1. Blocks Stage 2 until drafted.

### B6 - Architecture §5.1's diff-based conflict resolution is not implementable as written
**Where:** architecture-plan §5.1
**Finding:** the corrected fix says the service layer "diffs which fields actually changed between the `updated_at` the client last read and the current row." You cannot diff against a past state you do not have. An `updated_at` value is a token, not a snapshot - the server has no record of what the row looked like at that timestamp unless it keeps row history, which nothing in the plan provides. As specified, the overlap check cannot be computed.
**Recommendation:** move the comparison to the client's side of the contract. Two workable shapes:
- **Expected-values PATCH** (recommended): the client sends, for each field it is changing, the value it originally read. The server 409s only if `current[field] != client_expected[field]` for a field being written. No history storage, no field lists, and it degrades to exactly the §5.1 intent.
- **Per-field change log:** a small append-only `task_instance_changes` table. More power than this POC needs.

Also worth stating explicitly: the auto-retry described ("re-fetch, reapply, resubmit") is a *client* behavior, but §5.1 places it in the service layer. Pin which side owns it.

**Stakeholder decision (2026-08-06) - resolved:**

**Expected-values PATCH.** The client supplies, for each field it is changing, the value it read; the server compares only those fields and merges the change onto the current row.

```
PATCH /api/v1/task-instances/42
{ "priority": "medium", "expected": { "priority": "high" } }
```

1. **Algorithm**, in one transaction: read the current row; for each field present in the patch, `409` if `current[field] != expected[field]`; otherwise apply the patch onto the *current* row, increment `version`, write. Fields nobody is writing are preserved, so a concurrent job's `status` change survives a user's `priority` edit untouched.
2. **There is no retry loop, on either side.** The server applies or rejects. This resolves the ownership ambiguity in §5.1's "re-fetch, reapply, resubmit" wording, which should be deleted rather than reassigned.
3. **Amends B5:** `version` remains the guard on the write and a debugging aid, but it is **no longer the client-facing concurrency token** - the expected values are. Architecture §5.1 should not ask clients to echo a version.
4. **Atomicity:** SQLite serialises writers and the app is a single process (arch §7), so a single transaction around read-check-write is sufficient. No advisory locking needed.
5. **Error envelope:** `409` must name the conflicting fields and their current server-side values, so the frontend can show a specific conflict rather than a generic reload prompt.

**Hard requirements this places on the implementation - all four need tests:**
- **PATCH must be genuinely partial.** A frontend that sends its whole task object defeats the mechanism entirely, because every field then participates in the comparison. Dirty-fields-only is a binding requirement on Stage 9, not a nicety.
- **Omitted must be distinguishable from `null`** on the wire ("not touching `description`" versus "clearing `description`"). Same Pydantic trap as B4.
- **Structured fields need a defined comparison:** compare `dependencies` and `reminder_offsets` as sets so reordering is not a false conflict; deep-compare `active_hours_override`.
- **Field-level agreement is not semantic agreement.** Disjoint writes can still produce an invalid combination (a job setting `status: missed` while the user sets `scheduled_time`). Normal service-layer validation runs after the merge and rejects those on business rules; §5.1 must say so, so the field check is not mistaken for a correctness guarantee.

**Disposition:** decided; drafting into architecture-plan §5, §5.1 and §3 (error envelope). Blocks Stage 2 and Stage 8 until drafted.

### B7 - No entity exists for external calendar events
**Where:** design-doc §3 (entity list), §6.2, §6.4, §7
**Finding:** §6.4 says "fetch upcoming events, **diff against previously known set**" - which requires the previously known set to be persisted. §6.2 needs external busy-blocks as obstacles on every scheduling pass, which would otherwise mean a live API call inside the scheduler (breaking §2's pure-engine rule and making placement non-deterministic and offline-fragile). §3 defines six entities and none of them is an event. Implementation-plan Stage 2 inherits the gap verbatim ("ORM models for all six §3 entities").
**Recommendation:** add a seventh entity, cached locally and refreshed by the poll. Note that §3.9's `sync_conflict` auto-resolution ("the external event was later removed") *also* requires this - you cannot detect a removal without a prior set.

**Stakeholder decision (2026-08-06) - resolved:**

Add a seventh entity:

```
ExternalEvent
  id, connection_id, provider_event_id      # (connection_id, provider_event_id) unique
  start, end
  title
  is_all_day, is_transparent                # the §7 filter inputs
  fetched_at
  deleted_at                                # soft delete
```

Cached locally, refreshed by the poll, and handed to the scheduling engine as plain data like every other obstacle - so §6.2 never makes a network call and placement stays deterministic, offline-tolerant and unit-testable.

1. **Fetch horizon: a rolling 90 days.** Covers realistic deadlines without pulling years of recurring meetings.
2. **Past retention: purge events whose `end` is more than 30 days past**, on the same poll.
3. **Removals are soft-deleted** (`deleted_at` set), so §3.9's `sync_conflict` auto-resolution can detect "the external event was later removed" by inspecting a row rather than reasoning about absence. Purged on the retention sweep.
4. **The uniqueness constraint on `(connection_id, provider_event_id)`** is what makes §6.4's diff a plain upsert rather than bespoke matching logic.

**Retention scope - stakeholder clarification (2026-08-06): this policy covers `ExternalEvent` only.**

`ExternalEvent` is a **cache** of third-party data - the provider is the source of truth and any purged row is refetchable. `TaskInstance` is the **system of record**: §3.3 makes `completed` terminal and immutable, and §3.8 archives templates rather than hard-deleting them precisely so `template_id` references on historical instances stay valid. Rev 9 must therefore state explicitly that **`TaskInstance` rows are never aged out or purged** - completed and missed instances persist indefinitely. This is currently implied but nowhere written, and it is exactly the rule someone would violate in good faith by adding a "keep the database small" cleanup job.

**Disposition:** decided; drafting into design-doc §3 (new entity), §3.3 (retention statement), §6.4, §7 and architecture-plan §2. Blocks Stage 2 and Stage 7 until drafted.

### B8 - `Duration` is used throughout and never defined
**Where:** design-doc §3.2, §3.3, §3.7 - and the API contract by extension
**Finding:** `Duration` appears in `estimated_duration`, `deadline_offset`, `reminder_offsets`, and `daily_time_budget`, expressed in the prose as `"3 days"`, `"1h"`, `"15m"`, `"0m"`, and "e.g. minutes". No canonical wire format, no storage type, no precision rule.
**Stakeholder decision (2026-08-06) - resolved:**

`Duration` is **an integer count of minutes**, with elapsed-time semantics, in storage and on the wire alike. No parser, no ISO-8601, no value object.

1. **Fields carry the unit in their name** so it cannot be misread at a call site: `estimated_duration_minutes`, `deadline_offset_minutes`, `reminder_offsets_minutes`, `daily_time_budget_minutes`.
2. **Elapsed, not calendar.** `deadline_offset_minutes = 4320` is 3 days of elapsed time. Across a DST boundary the resulting deadline lands an hour off the original wall-clock time; this is an accepted simplification and should be stated in §14.1 so it is not later filed as a DST bug. Recurrence cadence is unaffected - §3.2 expresses it as `pattern` + `interval`, so calendar-month arithmetic stays outside this type.
3. **The scheduling engine therefore needs no timezone dependency for duration arithmetic**, which keeps §6.2's math pure integer comparison.

**UI requirement (stakeholder, 2026-08-06): the minute-count is a storage and wire format, never a data-entry format.** The user must never be asked to compute minutes. Rev 9 must specify in §8.1, and the frontend plan must implement:

- A **duration input control**: numeric value plus a unit selector, converting to minutes on submit. Sensible unit sets differ per field - `estimated_duration` in minutes/hours; `deadline_offset` in hours/days/weeks; `reminder_offsets` in minutes/hours/days plus an explicit "at start time" for `0`; `daily_time_budget` in hours/minutes.
- **Human-readable formatting on display**, in both directions: `4320` renders as "3 days", `90` as "1h 30m", never as a raw minute count.
- **Round-trip stability**: formatting a stored value and re-parsing it must yield the same integer. Worth an explicit test, since the natural greedy formatter ("90m") and the natural user expression ("1h 30m") differ.
- **Validation**: reject negative and non-integer values at the API boundary with a machine-readable code; `estimated_duration_minutes` is additionally subject to the §6.8 feasibility check.

**Disposition:** decided; drafting into design-doc §3.2, §3.3, §3.7, §8.1, §14.1. Blocks Stage 1 (engine input types) and Stage 2 until drafted; the input control is a Stage 9 item.

### B9 - Slot granularity is undefined, so §6.2 has no deterministic output
**Where:** design-doc §6.2 (`find_first_free_slot`)
**Finding:** "first free slot" is not a well-defined function without a time quantum. Does a 30-minute task in a gap from 18:07 to 19:00 start at 18:07, or at 18:15, or at 18:30? Every worked example is reproducible only by accident until this is pinned, and architecture §8 wants these examples to be the acceptance suite.
**Stakeholder decision (2026-08-06) - resolved:**

Placement uses a **15-minute grid aligned to the hour** (`:00`, `:15`, `:30`, `:45`). **Durations are not quantised.**

1. **The grid constrains computed start times only.** Fixed instances sit at their `fixed_time_of_day` and external calendar events keep their real times, so gaps still have arbitrary boundaries; only the *chosen start* must land on a grid point.
2. **Durations are stored and used exactly.** A 20-minute task placed at 18:00 occupies 18:00–18:20 as an obstacle; the next flexible placement starts at 18:30. Budget arithmetic stays exact and `estimated_duration` remains an honest estimate rather than something the user has to round.
3. **Placement rule:** the chosen start is the earliest grid point `t` with `t >= gap_start` such that `t + duration <= gap_end`, `t + duration <= deadline`, and `t + duration <=` the end of the effective active-hours window.
4. **The grid is aligned in the user's local wall-clock time, not UTC.** This matters: aligning in UTC produces `:15`-offset slots for anyone in a half-hour or quarter-hour offset zone (`Asia/Kolkata` at +05:30, `Asia/Kathmandu` at +05:45). §14.1 already requires local-timezone computation; this is a concrete instance of it.

Consequences Rev 9 must state:
- **§6.8's feasibility check must account for grid loss.** The usable window is measured from the first grid point at or after the window start, not from the window start itself, or a task can pass feasibility validation and then never be placeable.
- **Every Worked Example in §10 needs re-checking against the grid**, since the effective usable window shrinks by up to 14 minutes per window.

**Disposition:** decided; drafting into design-doc §6.2, §6.8, §10. Blocks Stage 1 until drafted.

### B10 - There is no way to create the first user, and `RESET_ADMIN_PASSWORD` is documented as optional
**Where:** design-doc §3.6, §14.2 vs architecture-plan §7.1
**Finding:** §14.2 makes auth mandatory with no anonymous mode. §3.6 defines a password *reset* mechanism but no account *creation* path, and there is no signup screen in §8.1. So on a fresh deployment there is no user, no way to make one, and the app is unusable. Meanwhile architecture §7.1 lists `RESET_ADMIN_PASSWORD` as **Optional**, which is only true after first run. Implementation-plan Stage 3 spotted this and correctly flagged it as a decision the plan should not be making alone - agreed, and it belongs in the design doc, not in Stage 3.
**Recommendation:** define a first-run bootstrap path in §3.6, and correct §7.1's "Optional" label to match whichever path is chosen.

**Stakeholder decision (2026-08-06) - resolved:**

**A first-run setup wizard**, not an env-var bootstrap. On a deployment with zero `User` rows, the app serves a one-time setup screen that creates the admin account. Chosen over the env-var path because the wizard UI is the durable artifact: gating it with a token later is an incremental hardening of an existing flow, whereas an env-var bootstrap would have to be replaced outright.

**Consequence, and a welcome one:** `RESET_ADMIN_PASSWORD` becomes purely a *recovery* mechanism and is never used for creation. Architecture §7.1's existing **Optional** label therefore becomes correct as written, and B10's complaint about it falls away.

**Rules Rev 9 must state:**
1. **`POST /api/v1/auth/setup`** plus a frontend route, available **only** while zero `User` rows exist. Once an account exists the endpoint is permanently gone (`410 Gone`), not merely unauthorised.
2. **The zero-users check and the insert are one transaction**, backed by a uniqueness guarantee on the users table. Two concurrent setup requests must not both pass the check.
3. **While unconfigured, every other route refuses to serve** and directs to setup. An app serving task data before an account exists would be an unauthenticated app, which §14.2 forbids.
4. **Username** is fixed as `admin`. Single-user; a configurable username is a knob with no benefit.
5. **Password rules:** minimum 12 characters, no composition requirements, validated at the setup endpoint.
6. **The one-time marker (finding M8)** still governs `RESET_ADMIN_PASSWORD` on the recovery path. Recommend storing it as a row in a small `system_state` table rather than a file, so it shares the mounted volume with the data and cannot desynchronise from it.

**Setup token - recommended in scope for the same Stage 3 work, not deferred:**

An unguarded wizard leaves a **claim window** between container start and the operator's first visit; whoever arrives first owns the account, the task history and the OAuth calendar connections. That window is more exposed now that plain-HTTP LAN is a supported deployment (B11), and §14.2 has already established that this app should not be open by default even on a trusted network.

Recommended shape: on startup with zero users, generate a random single-use token, log it at `WARNING` level so it appears in default output, and require it in the setup request. Invalidate it once setup completes; regenerate per process start while still unconfigured. Roughly twenty lines, and it closes the window entirely.

**If the token is deferred instead**, the app must at minimum log loudly and repeatedly that it is awaiting setup and is currently claimable, so the operator knows the window is open.

**Disposition:** decided; token in scope pending confirmation. Drafting into design-doc §3.6, §8.1, §14.2 and architecture-plan §3, §6, §7.1. Blocks Stage 3 until drafted.

### B11 - `secure` cookie + LAN-only HTTP deployment is a deployment-breaking contradiction
**Where:** architecture-plan §1, §3 (Auth), §6 vs design-doc §2, §12.5, §13
**Finding:** the auth design mandates a `Secure` session cookie. The deployment target is explicitly LAN-local self-hosting - §12.5 defers webhooks specifically *because* the app is not publicly reachable, and §13 lists "self-hosted and LAN-reachable" as the operating assumption. Browsers do not send `Secure` cookies over plain `http://`, and a typical operator will run this at `http://192.168.1.x:8000`. **As specified, login cannot work on the primary target deployment.**
**Recommendation:** make the flag configuration-derived rather than a constant, and document the TLS upgrade path rather than requiring it.

**Stakeholder decision (2026-08-05) - resolved, pending drafting into Rev 3 of the architecture plan:**

Plain-HTTP LAN is a **fully supported deployment**, not a degraded mode. The flag is derived, with a loud startup warning when it resolves to insecure.

1. **New env var `SESSION_COOKIE_SECURE`, values `auto` | `true` | `false`, default `auto`.**
   - `auto` reads the scheme of `APP_BASE_URL`: `https://...` resolves to `Secure`, `http://...` resolves to not-`Secure`.
   - `true` / `false` force the value, for deployments behind a TLS-terminating proxy where `APP_BASE_URL` may not reflect the browser-facing scheme.
2. **Startup logging is mandatory, not optional.** The app logs the resolved value at startup. When it resolves to not-`Secure` it must emit a `WARNING`-level line stating that the session cookie and the login password cross the network in cleartext, and naming the remedy (TLS-terminating reverse proxy, or a WireGuard/Tailscale transport). The warning is the entire mechanism preventing an operator from stumbling into this silently, so it must be visible in default log output.
3. **`HttpOnly` and `SameSite=Lax` are set unconditionally**, independent of `SESSION_COOKIE_SECURE`. Both function correctly over plain HTTP. See B12 - on an HTTP LAN deployment `SameSite` carries *more* weight, not less, because any site the user visits can reach `http://<lan-ip>:8000` directly.
4. **README documents the upgrade path** (reverse proxy with automatic TLS, or Tailscale for encrypted transport plus remote access) as a recommendation rather than a prerequisite, noting that `auto` picks the change up from `APP_BASE_URL` with no further configuration.

**Rationale for the record:** on a plaintext deployment `Secure` protects nothing - there is no encrypted channel for it to confine the cookie to, and the password is already in the clear on every login. Its value is entirely in preventing downgrade leakage on deployments that *do* have TLS. Hardcoding it `true`, as the current text does, therefore buys zero security on the primary target while silently breaking login on every access path except `http://localhost` (browsers treat `localhost`/`127.0.0.1`/`[::1]` as trustworthy origins; private IPs and `.local` names are not). The failure is invisible: login returns `200`, the browser discards the cookie, the next request 401s, and the user loops back to the login screen with nothing logged.

**Documents to update in Rev 3:** architecture-plan §1 (component table, "Auth" row), §3 (Auth), §6, §7.1 (env var table - add `SESSION_COOKIE_SECURE`), the §7 deployment section; implementation-plan Stage 3 scope line; `.env.example`; README configuration section.
**Disposition:** decided; needs drafting. Blocks Stage 3 and Stage 10 until drafted.

### B12 - No CSRF defense anywhere in the design
**Where:** architecture-plan §3 (Auth), §6
**Finding:** the app uses same-origin cookie auth for all state-changing endpoints and never mentions CSRF. Cookies are attached automatically by the browser, so any page the user visits can issue cross-site state-changing requests to `http://tessera.local:8000/api/v1/task-instances/...`. The doc's rationale for cookies over `localStorage` tokens is XSS resistance, which is correct - but it trades XSS exposure for CSRF exposure, and only half that trade is acknowledged.
**Recommendation:** set `SameSite=Lax` at minimum (blocks cross-site POST/PATCH/DELETE while preserving normal navigation); add `SameSite=Strict` or a double-submit token if the OAuth redirect flow doesn't need Lax. State it in architecture §6 next to the other cookie attributes. The OAuth callback additionally needs the standard `state` parameter check, which is also unmentioned.

**Stakeholder decision (2026-08-07) - resolved:**

**`SameSite=Lax` alone. No CSRF token.** `Lax` withholds the session cookie from every cross-site `POST`, `PATCH` and `DELETE`, which covers every mutation in the API. For a single-user, single-origin app that is sufficient; a double-submit token is defence in depth bought with real frontend plumbing, and it can be added later without an API break if this is ever exposed beyond a LAN.

**`Lax`, deliberately not `Strict` - Rev 3 must record the rationale**, because `Strict` looks safer and someone will otherwise "harden" it later and break calendar sync. The OAuth callback arrives as a **cross-site top-level navigation** from the provider. `Strict` withholds the cookie on exactly that request, so the callback would land unauthenticated and a connection could never complete. `Lax` sends it. The weaker-looking setting is the correct one, for a specific reason.

**Two safe corrections adopted with it:**
1. **No state-changing endpoint may be exposed over `GET`.** `Lax` still attaches the cookie to top-level `GET` navigations, so a mutating `GET` reopens the hole `Lax` closes. The API contract currently complies by accident; this makes it a stated rule.
2. **The OAuth callback must verify a `state` parameter**, generated per authorisation request and checked on return. It is unmentioned in both documents, and without it the callback will accept an attacker-initiated authorisation code. Mandatory, not recommended.

**Note after the B11 decision (2026-08-05):** `SameSite=Lax` is now load-bearing rather than defence-in-depth. With plain-HTTP LAN a supported deployment, the app is served from an origin that any website the user visits can address directly (`http://192.168.1.50:8000`), and the session cookie is not `Secure`. `SameSite=Lax` is what prevents a hostile page from issuing authenticated `POST`/`PATCH`/`DELETE` requests. It is set unconditionally per B11 item 3. This also means **no state-changing endpoint may be exposed over `GET`**, since `Lax` still attaches the cookie to top-level `GET` navigations.
**Disposition:** safe correction (industry-standard, no product tradeoff). Blocks Stage 3.

---

## 2. High-severity findings

### H1 - The topological sort in §6.1/§6.2 is provably dead code
**Where:** design-doc §6.1 (third bullet), §6.2 (`topological_sort`)
**Finding:** §4 says an instance with unfulfilled dependencies is `blocked`, and only `pending` instances are eligible for the algorithm. Therefore **every candidate in a scheduling pass already has all dependencies `completed`** - the doc says as much itself in §3.3's Revision 6 note. No candidate can depend on another candidate. The topological sort can never reorder anything, and the `earliest_start` dependency term is only ever reading completed timestamps (which §6.2 also already notes). Meanwhile §6.1 justifies the sort with "so no instance is placed before its dependencies' scheduled/completed times" - a hazard that the `blocked` rule already eliminates.
**Why it matters:** an implementer will spend real time building and testing a topological sort that cannot affect any outcome, and may conclude the `blocked` gating rule is wrong and "fix" it.
**Recommendation:** either delete the sort and state plainly that dependency ordering is enforced by the `blocked` status gate, not by pass-level sorting; or make the sort genuinely load-bearing by relaxing the gate. Do not leave it looking load-bearing when it is not.

**Stakeholder decision (2026-08-06) - resolved:**

**Dependents are not placed until every dependency is `completed`**, and are then scheduled automatically. This keeps Revision 8's `blocked` gate as-is; the sort is deleted. The cost of that gate - dependents being invisible until their prerequisites finish - is fixed with a **Backlog view** rather than with algorithm.

*(An earlier decision this same day took the opposite option, placing dependents once their dependencies merely had a known time. It was reversed after the Backlog proposal, which achieves the visibility goal without any of the cascade machinery. Recorded here rather than deleted, per the changelog convention in §11.)*

**Core rules:**
1. **The `blocked` gate is unchanged.** An instance with any dependency not `completed` is `blocked` and is not a scheduling candidate. `blocked` therefore remains mutually exclusive with `scheduled_time`, and §4's state model needs no rewrite.
2. **The topological sort is deleted**, along with any test purporting to exercise it. §6.1's justification for it is replaced with a sentence stating that dependency ordering is enforced by the `blocked` status gate, not by pass-level sorting. Cycle detection stays at edit time (`cycle_detected`); the engine needs none at runtime.
3. **Auto-scheduling on unblock** is an event hook fired when the last dependency reaches `completed`, in the same service method as that completion (arch §4.1). This fits the event-driven job model directly - no cascade jobs, no re-placement of anything already committed. B3's immovability rule keeps no exceptions.
4. **If auto-scheduling fails** (no room before the deadline), the instance becomes `unschedulable` and notifies, exactly as any other unplaceable flexible task.

**The Backlog (new UI surface, stakeholder-confirmed 2026-08-06):**
- **It is a view, not an entity.** A backlog item is a `TaskInstance`; the backlog is a filtered query. Introducing a separate entity would put the same task in two places with a migration between them, which is the silent-orphan failure mode arch §4.1 exists to prevent.
- **Scope of the view: all instances in `blocked`, `unschedulable`, or `missed`** - everything that needs the user's attention and has no place on the timeline. Not dependency-blocked tasks alone.
- **The dependency relation is navigable in both directions.** From a backlog item, see and edit what is blocking it; from any task, see what is waiting on it.
- **Schema consequence:** `dependencies` must become a **join table** (`task_instance_dependencies(dependent_id, dependency_id)`), not the `TaskInstance id[]` array §3.3 currently specifies. Reverse lookup is free against a join table and a full scan against a JSON column. This is required by the bidirectional view and is worth doing regardless.

**Deadline semantics - stakeholder decision:** a **deadline is a fixed point in time**. The clock keeps running while an instance sits in the backlog, so a dependent can reach `missed` without ever having been schedulable, if its dependency ran late. The user recovers through the existing §6.7 extend-deadline path. The clock does **not** pause while blocked, and deadlines are never rebased on unblock.

**`dependency_at_risk` (see H10) uses a speculative pass.** Since downstream tasks are never placed, chain-completion risk cannot be read off the timeline. The scheduling engine is pure, so the risk scan runs a **hypothetical placement of the chain, persisting nothing**, and compares the projected end against the deadline. This preserves the notification's purpose without reintroducing chain scheduling, and the same dry run can later back a "preview this chain" UI if wanted.

**Also required:** add a Worked Example to §10 covering a dependency chain - unblock, auto-schedule, and the late-dependency `missed` path.

**Disposition:** decided. Deletes work rather than adding it, apart from the Backlog view (a Stage 9 UI item) and the join-table schema change (Stage 2). Blocks Stage 1 and Stage 5 until drafted.

### H2 - §6.6's overdue handling yanks `in_progress` tasks back to `pending`
**Where:** design-doc §6.6
**Finding:** the trigger is "`scheduled_time` has passed and `status` is not `completed`." `in_progress` is not `completed`. So a flexible task the user started on time and is *currently doing* has its `scheduled_time` cleared and is thrown back into the scheduling pool the moment its start time passes.
**Recommendation:** restrict the overdue check to `scheduled` only. Separately, decide what (if anything) should happen to an `in_progress` task that never gets completed - recommend nothing automatic for POC.
**Disposition:** safe correction.

### H3 - Budget accounting counts commitments that fall outside active hours
**Where:** design-doc §3.7 (final paragraph), §6.2 (`committed_duration`)
**Finding:** `daily_time_budget` counts fixed instances and external events toward a day's capacity. Nothing restricts that sum to the active-hours window. An operator with a work calendar synced in will have 8 hours of 09:00–17:00 meetings counted against a 3-hour 18:00–21:00 evening budget, saturating every weekday and forcing every flexible task into Pass 2 or `unschedulable`. The stated rationale for counting them ("a day already packed with fixed commitments shouldn't also absorb a stack of chores") is sound, but only for commitments inside the window the user actually schedules into.
**Recommendation:** count only the portion of each obstacle that overlaps the applicable active-hours window for that day.
**Disposition:** needs stakeholder confirmation (it changes Example G/H arithmetic in principle, though not in those examples as written).

### H4 - `creation_conflict` cannot exist as a `Notification`
**Where:** design-doc §3.4, §5, §6.5
**Finding:** `Notification.related_instance_id` is required. §6.5 **hard-blocks** creation - nothing is saved, so there is no instance to relate the notification to. `infeasible_duration` (§6.8), which the doc explicitly says "mirrors the existing hard-block pattern already used for fixed-task creation conflicts (6.5)", is correctly modeled as an API error code and *not* as a notification type. The two should be treated identically.
**Recommendation:** remove `creation_conflict` from the `Notification` type enum and §5's table; keep it as an error code in the API envelope (architecture §3 already lists it there). If a persisted record of blocked attempts is genuinely wanted, that's a different feature and belongs in the backlog.
**Disposition:** safe correction.

### H5 - Archiving a template with live incomplete instances has no defined outcome
**Where:** design-doc §3.8 (second bullet), §8.2
**Finding:** §3.8 says the UI must explain "what happens to them" and §8.2 says the dialog lists them - but neither document ever says what actually happens. Are the live instances deleted, left scheduled (and still firing reminders for a task the user just deleted), or cancelled?
**Recommendation:** define it. Recommend: incomplete instances of an archived template are deleted (with their jobs cancelled and dependents unlinked per §3.8's instance rule); completed instances are retained as history, which is the stated reason for archiving rather than hard-deleting in the first place.
**Disposition:** needs stakeholder decision.

### H6 - No de-duplication rule for `unschedulable` or `budget_exceeded`
**Where:** design-doc §6.2, §6.3, §5
**Finding:** §6.3 explicitly de-duplicates `dependency_at_risk` ("fires once per (instance, threshold-crossing) event, not every scan"). §6.2 has no equivalent rule and creates a notification on **every failed pass** for the same instance, and a `budget_exceeded` on every over-budget placement. Since a task can be evicted and re-placed repeatedly (§6.4, §6.6), and `budget_exceeded` is explicitly never auto-resolved (§3.9), the panel will accumulate duplicates for a single underlying situation.
**Recommendation:** apply §6.3's de-dup rule generally: at most one active (undismissed, unresolved) notification per (instance, type). State it once in §3.4 rather than per type.
**Disposition:** safe correction.

### H7 - §3.9 auto-resolution is a rule with no per-type triggers
**Where:** design-doc §3.9, §5
**Finding:** §3.9 states the principle and gives examples for two types. §5's table's "Resolution path" column describes *user* actions, not auto-resolution conditions. So for `unschedulable`, `overdue`, `reminder`, and `deadline_missed` there is no stated trigger for when `resolved_at` gets set. Implementation-plan Stage 5 catches this and demands a row-by-row audit - correct, but the answer is product behavior and belongs in the design doc, not in an implementer's judgement.
**Recommendation:** add a third column to §5's table: "Auto-resolves when". Suggested: `reminder` - never (informational, dismissed only); `sync_conflict` - conflicting external event removed/moved, or instance rescheduled clear of it; `unschedulable` - instance reaches `scheduled` or a terminal state; `dependency_at_risk` - all dependencies complete, or deadline extended past the threshold; `overdue` - instance completed or rescheduled forward; `deadline_missed` - as already stated in §6.7; `budget_exceeded` - never, by design.
**Disposition:** needs stakeholder confirmation of the table.

### H8 - The design doc mandates periodic scans; the architecture doc replaces them with event-driven jobs
**Where:** design-doc §6.3, §6.6, §6.7, §9 vs architecture-plan §4
**Finding:** §6.3 ("Periodic check"), §6.6 ("Periodic check"), §6.7 ("Periodically"), and §9's job list ("reminder scan", "overdue scan", "deadline-elapsed scan") all specify a mechanism. Architecture §4 deliberately replaces all of them with precisely-scheduled one-off jobs. Per implementation-plan §0's authority chain, **the design doc wins on conflict** - so a literal reading requires periodic scans and forbids the architecture's core job design.
**Why it matters:** this is a process defect, not just a wording one. The authority chain is the mechanism that keeps an LLM agent or a returning developer honest; an unresolved conflict inside it teaches them to resolve conflicts by taste.
**Recommendation:** the design doc should specify *guarantees* ("the system must transition the instance to `missed` no later than N minutes after its deadline elapses") and leave mechanism to the architecture doc, which is exactly the §0 division of labour both documents claim. Reword §6.3/§6.6/§6.7/§9 accordingly, or add an explicit note in architecture §4 that it supersedes the design doc's mechanism wording. The former is cleaner.
**Disposition:** safe correction, but touches the locked doc.

### H9 - No misfire policy for one-off jobs
**Where:** architecture-plan §4, §4.2
**Finding:** every timing-critical behavior is a one-off APScheduler job. Two unhandled cases:
- **Container down across a fire time.** Self-hosted machines get rebooted. On restart, does a reminder whose time passed two days ago fire immediately, fire silently, or get dropped? APScheduler's `misfire_grace_time` default will make this decision for you if you don't. §4.2's reconciliation recreates *missing* jobs but says nothing about *stale* fire times.
- **Fire time already in the past at creation.** A task scheduled 30 minutes from now with a `1h` reminder offset, or a dependency-at-risk job at `deadline - 3 days` on a task due tomorrow. Both compute a past timestamp at wiring time.

**Recommendation:** state one rule covering both: a one-off job whose fire time is in the past is evaluated immediately at wiring/reconciliation time, and its handler must be idempotent and must re-check current state before acting (an overdue check that fires late should still no-op if the task was completed meanwhile). Set `misfire_grace_time` explicitly rather than inheriting the default.
**Disposition:** safe correction to architecture §4; add to Stage 6's test list.

### H10 - `dependency_at_risk` cannot fire for fixed instances
**Where:** design-doc §6.3, §3.3
**Finding:** §6.3 applies to "any non-completed instance with ≥1 incomplete dependency" and keys off `deadline`. `deadline` is optional and only set "at generation for flexible tasks" (§3.3). A blocked *fixed* instance - e.g. "Annual inspection, Tuesday 09:00, depends on Prepare car" - has no `deadline`, so it never warns, which is the case where a warning matters most (the time is immovable).
**Recommendation:** for fixed instances, evaluate the threshold against `scheduled_time`. One line in §6.3.
**Disposition:** safe correction.

### H11 - A blocked fixed instance whose time passes has no defined outcome
**Where:** design-doc §4, §6.6, §6.7
**Finding:** `missed` is explicitly flexible-only. A fixed instance that is `blocked` when its `scheduled_time` arrives never becomes `scheduled`, so §6.6's overdue check (keyed on `scheduled_time` passing) may or may not apply depending on whether a blocked fixed instance carries a `scheduled_time` at all - itself unstated. Either way it sits `blocked` forever with a time in the past, and per B1 its template never generates again.
**Recommendation:** decide whether a `blocked` fixed instance holds a `scheduled_time` (recommend yes - it is user-specified and known at creation), and give it a terminal path when that time passes while still blocked.
**Disposition:** needs stakeholder decision.

### H12 - Timezone re-projection (§14.1) is optional-sounding, unassigned, and can create conflicts
**Where:** design-doc §14.1 vs implementation-plan Stages 4/5/6
**Finding:** three problems in one rule.
- **Optional wording:** "re-projected ... the next time their `scheduled_time` is computed (e.g. at next recurrence generation, or via an explicit recompute triggered by the timezone-change save action)". The "e.g." leaves it genuinely unclear whether changing your timezone moves your existing fixed tasks today or at some unspecified later point. For a binding cross-cutting rule, that's too loose.
- **Conflicts:** re-projecting fixed instances can land two of them on top of each other, or on top of an external event - violating the §6.5 invariant that the system otherwise hard-blocks. Nothing says what happens.
- **Flexible instances:** a flexible task placed at 19:00 local is stored as a UTC instant. Change the timezone and it is now at 13:00 local - outside the user's active hours, which is the constraint that justified placing it there. §14.1 addresses only fixed instances.
- **Unassigned:** implementation-plan Stage 4 (Settings) explicitly defers all settings-consuming behavior to Stage 5, but Stage 5's scope covers only the generation-time projection. No stage owns "recompute on timezone change."

**Recommendation:** make the recompute mandatory and synchronous with the timezone save (same transaction, with job re-wiring, per architecture §4.1's co-location rule); define collision behavior (recommend: re-project anyway, then raise `sync_conflict`-style notifications for any resulting collisions rather than blocking the settings change); decide explicitly whether scheduled flexible instances are re-evaluated (recommend: return them to `pending` for re-placement, since their placement constraint is wall-clock); and assign the work to a named stage.
**Disposition:** needs stakeholder decision on the flexible-instance half; the rest is safe correction.

### H13 - §6.8 feasibility is validated once and never re-validated
**Where:** design-doc §6.8, §3.7
**Finding:** duration feasibility is checked at save time against the then-current active hours. Nothing re-checks when the user later *shrinks* their global `active_hours` or a template's override. Every task that no longer fits silently returns to the exact failure mode §6.8 was written to prevent: permanent `pending` with a repeating `unschedulable` notification.
**Recommendation:** re-run the §6.8 check across affected templates/instances when `active_hours` or an override is narrowed, and surface the now-infeasible tasks to the user at settings-save time (warn, don't block - the settings change is legitimate). Assign to Stage 4 or 5.
**Disposition:** needs stakeholder decision (warn vs. block).

### H14 - In-process APScheduler assumes a single worker; nothing enforces it
**Where:** architecture-plan §4, §7
**Finding:** APScheduler runs in-process with a shared SQLite job store. §7 says "single container, single process", but nothing in the deployment config, docs, or startup code pins uvicorn to one worker. Anyone who sets `--workers 4` for throughput gets every job executed up to four times - duplicate reminders, duplicate scheduling passes, duplicate instance generation.
**Recommendation:** state the constraint explicitly in §7, pin it in the container entrypoint, and add a startup guard that refuses to run the scheduler in more than one process (env flag or advisory lock). Also worth adding to implementation-plan §8's risk list alongside the existing SQLite-sharing entry.
**Disposition:** safe correction.

### H15 - `priority` is close to inert in the POC, which will read as a bug to users
**Where:** design-doc §3.2, §6.2, §12.7
**Finding:** priority only influences the sort *within a single scheduling pass*, and already-`scheduled` instances are never re-placed (§6.2's candidate set is `pending` only; priority-based bumping is deferred to 12.7). Because passes are event-driven and usually contain exactly one candidate, priority will almost never affect any outcome. A user who marks something `critical` and watches it get scheduled after a `low` chore that happened to be created first will report it as broken.
**Why it matters:** this is not a defect in the algorithm - it follows correctly from deliberate scope decisions - but it is a defect in the *product expectation* the field sets. It is cheap to address in the UI/docs and expensive to discover after release.
**Recommendation:** no algorithm change (12.7 stays deferred). Add an explicit note to §3.2 and to the UI copy in §8.1 stating what priority does and does not do in the POC.
**Disposition:** needs stakeholder acknowledgement.

---

## 3. Medium-severity findings

| # | Where | Finding | Recommendation |
|---|---|---|---|
| M1 | §3.2 | `recurrence.pattern: "custom"` is in the enum with no definition and no configuring fields. | Define it or drop it from POC. Recommend dropping - `interval` already covers "every N days/weeks/months". |
| M2 | §3.2 | Monthly recurrence with `day_of_month` 29–31 is undefined for short months. | State a rule (recommend: clamp to the last day of the month). |
| M3 | §3.2 | A one-time flexible task can only express a deadline as an *offset from creation*. "Submit taxes by April 15" requires the user to do date arithmetic, and the workaround (create, then edit the instance's absolute `deadline`) detaches the instance as a side effect (§3.10). | Allow an absolute `deadline` at creation for `one_time` templates, or have the UI compute the offset from a date picker. The latter is smaller. |
| M4 | §3.7, §6.2 | Three window edge cases undefined: is `blackout_dates.end` inclusive? Is an overnight window (`start` 22:00 > `end` 02:00) legal? Split windows (morning + evening) are unsupported by the single `{start,end}` shape. | Define inclusivity; either support or explicitly reject overnight windows at validation; record split windows as backlog if they're wanted. |
| M5 | §3.3, §9.1 | Whether a generated instance inherits the prior instance's `dependencies` is unstated. Template-level dependencies are backlogged (12.12), which implies "no", but it isn't said. | State "generated instances have no dependencies" in §9.1. |
| M6 | §3.5, §7 | External sync omits: which calendars within a connected account are synced (a Google account has many); how far ahead events are fetched; rate-limit/backoff behavior; what happens when a token refresh fails. | Add a `calendar_ids` selection to `ExternalCalendarConnection`, a fetch horizon constant (suggest 90 days, consistent with §9.2's hardcoded-horizon precedent), and a failed-sync notification or status field. |
| M7 | §10, arch §8 | Architecture §8 claims Worked Examples A–K "are already concrete input/expected-output scenarios". A, B, C, and E are qualitative prose ("finds the first free 30-minute slot") with no settings, obstacles, or expected timestamps. They cannot be transcribed into acceptance tests without inventing the fixture data - which is exactly the invention implementation-plan §0 forbids. | Rewrite A, B, C, E as tables (given settings / given obstacles / expected `scheduled_time`), the way G, H, I and J nearly already are. This is the single highest-value edit for Stage 1. **Decided 2026-08-06:** rewrite A/B/C/E as fixture tables **and re-derive every expected value in G–K**, as part of the Rev 9 drafting pass rather than deferred into Stage 1 - five decisions from this session (B3, B4, B8, B9, H1) change their expected output, most visibly the 15-minute grid. Add a new example covering a dependency chain, which H1 leaves uncovered. |
| M8 | §3.6 | The one-time-reset marker's storage location is unspecified ("writes a local marker"). If it lands in the container's writable layer rather than the mounted volume, it is erased on every container recreate and `RESET_ADMIN_PASSWORD` becomes the standing backdoor §3.6 exists to prevent. | State that the marker is stored in the database (i.e. on the volume). |
| M9 | arch §6 | No session lifetime, idle timeout, rotation-on-login, or revocation-on-password-change policy. An implementer who writes no expiry code gets sessions that never expire, which under B11 (cookie may travel in cleartext on a LAN) turns a once-captured cookie into a permanent credential. | **Decided 2026-08-07: 30-day absolute TTL, no idle timeout.** No per-request `last_seen` write, which matters with SQLite as the store (see M12). Plus: **rotation on login** (fresh session ID per successful login - the standard session-fixation defence); **revoke every session for the user on any password change or reset**, which is not optional because `RESET_ADMIN_PASSWORD` exists to lock somebody out and fails at that if old sessions survive; **lazy cleanup** of expired rows at login rather than another background job; and an expired session returns `401` with a **distinct machine-readable code** so the frontend redirects to login instead of surfacing a generic error. Session row: high-entropy id, `user_id`, `created_at`, `expires_at`. |
| M10 | arch §3, design §14.2 | "A session/auth guard must wrap the entire app" cannot be literally true - several routes must serve before a session exists - and the exempt set is never listed. An unlisted carve-out is how auth bypasses happen: not through a deliberate hole, but through a route added later by someone who never considered which side of the boundary it sits on. | **Decided 2026-08-07.** **Wiring: middleware with an explicit public-route allowlist (default-deny)**, not per-endpoint auth dependencies - a route added next year is then protected automatically unless someone deliberately exempts it, whereas a forgotten dependency silently publishes an endpoint with nothing failing to signal it. **Public:** `GET /health` (payload limited to `{"status": "ok"}` - no version, no database state, nothing fingerprintable); static assets, `index.html` and all SPA client routes; `POST /api/v1/auth/login`; `POST /api/v1/auth/setup` and its frontend route (public only while zero users exist, `410 Gone` after - B10). **Explicitly NOT carve-outs, correcting this finding's original framing:** the **OAuth callback requires a valid session** - B12 chose `SameSite=Lax` precisely so the cookie is sent on that cross-site top-level navigation, and requiring auth is correct on the merits since the callback binds a calendar connection to an account; combined with the mandatory `state` check that closes it properly, and an expired mid-flow session simply fails and is retried. `POST /api/v1/auth/logout` also requires a session and returns `204` either way. **Public by default and easily missed:** FastAPI auto-serves `/docs`, `/redoc` and `/openapi.json`, exposing the whole API surface uncredentialed - disable them in production via a setting, leave them on in development. **Add a test that enumerates every registered route** and asserts each is either allowlisted or guarded, in the same spirit as the existing `import-linter` and AST-walk architecture tests. |
| M11 | §3.2, §3.3 | No field validation rules anywhere: min/max `estimated_duration`, non-empty `name`, `reminder_offsets` count cap, `interval` bounds, negative/zero durations. | Add a short validation table to §3. Cheap now, tedious to retrofit across API + UI + ORM. |
| M12 | arch §5, impl §8 | SQLite WAL mode and `busy_timeout` appear only as a "risk to watch", but sharing one SQLite file between the app and the APScheduler job store in one process makes them a requirement, not an observation. | Promote to an architecture decision in §5 with the pragmas stated. |
| M13 | arch §7 | Nothing addresses backup/restore of the SQLite file, which holds all task history and encrypted OAuth tokens. `docker-compose.yml` uses a named volume, which is harder for an operator to back up than a bind mount. | Add a short operator note; consider defaulting the compose file to a bind mount (`./data:/app/data`). |
| M14 | design §9 | Design-doc §9 duplicates architecture-plan content (stack, DB, packaging, job list) and has **already drifted** from it (the job list, per H8). Two sources of truth for the same decisions. | Trim §9 to a pointer at the architecture plan, keeping only what is genuinely product-level (self-hosted, single deployable unit, auth required). |
| M15 | §3.2/§3.3, arch §3 | `priority` is a string enum on the template and a number on the instance, and the API contract never says which crosses the wire for instances. | Pin the wire representation (recommend the string enum everywhere externally, numeric only internally). |
| M16 *(raised 2026-08-06)* | §13 vs §3.3, backlog 12.14 | §13 states that duration prediction (12.14) builds on "data the POC will start collecting". The POC only partly collects it. Actual duration is derivable solely from a `status_history` pair of `in_progress` → `completed`, and §3.3 makes `in_progress` **explicitly optional**, permitting `completed` directly from `pending`, `blocked` or `scheduled`. Every task completed without passing through `in_progress` contributes an estimate with no matching actual. | **No action, and no schema change - deliberately.** Everything 12.14 needs is already preserved: `estimated_duration` is copied onto the instance at generation so later template edits don't rewrite history, `completed` instances are immutable, and `status_history` is an immutable trail. The corpus is simply **partial by construction**, and the missing signal is behavioural, not structural - no extra field can recover it. Soften §13's wording to say the POC collects this for instances that pass through `in_progress`, so whoever builds 12.14 learns this before training on the data rather than after. Any prompt-for-actual-duration mechanism is a 12.14 feature and out of POC scope (§0). |

---

## 4. Low-severity / editorial

| # | Where | Finding |
|---|---|---|
| L1 | arch header | "Companion to: Design Document (POC), **Revision 7**" - the design doc is at Rev 8. Rev 8 was markup-only so nothing substantive drifted, but the authority chain should cite the current revision. |
| L2 | §4 state diagram | The diagram contradicts its own rules below it: it shows `blocked → scheduled` (true only for fixed instances), omits `blocked → pending` (the flexible path), and omits `pending → missed` even though the rules text says `missed` is reachable from `pending`. |
| L3 | §3.10 | The UI trigger condition "(a) recurring and (b) not a one-time (`recurrence: one_time`) template" states the same condition twice. |
| L4 | impl §5 | Progress Tracker shows Stage 0 as "Not started"; Stage 0 is merged to `main` (`28c2104`). The tracker is explicitly named as the recovery point for a returning developer or LLM agent, so drift here is worse than it looks. |
| L5 | impl §4, §2 | "CI enforces the coverage gates from architecture doc §8" - there is no `--cov-fail-under` in `backend/pyproject.toml` or `.github/workflows/ci.yml`. The gate is documented but not enforced; codecov is configured with `fail_ci_if_error: false`. |
| L6 | impl §4 | The Stage 9 hard prerequisite `/mnt/skills/public/frontend-design/SKILL.md` does not exist in this environment. A hard gate pointing at a missing file will either be skipped or will block Stage 9. |
| L7 | §10 Example J | "Wednesday: budget effectively exceeded already, committed 1h" - with a 1h budget and 1h committed, Wednesday is exactly *at* budget, not exceeded. The arithmetic that follows is right; the wording isn't. |
| L8 | infra | `docker-compose.yml` declares the obsolete `version: "3.8"` key (Compose v2 warns on it). The CI container smoke test runs with `DATABASE_PATH=:memory:`, so the volume-persistence requirement architecture §7 calls critical is never actually exercised in CI. |
| L9 | §12 | `12.15` is both a backlog table row and a subsection heading ("### 12.15 - Open questions..."), which reads as a numbering collision. |
| L10 | impl Stage 9d | The "compute virtual projections client-side or server-side" decision is deferred to Stage 9d, but the server-side option adds a backend endpoint *after* Stage 8 has already frozen the API contract. |

---

## 5. What the documents get right

Worth recording, so a revision pass doesn't damage it:

- **The authority chain and traceability mechanism** (design = what, architecture = how, implementation = order/gates; docstrings citing section numbers; module structure mirroring section boundaries) is the strongest part of this documentation set. It is what makes the codebase resumable by someone with no memory of the decisions.
- **Scope discipline is enforced structurally, not aspirationally** - Section 12 with per-item rationale, the "don't build it while you're in there" rule, and Stage 11's explicit backlog audit. Most POCs have a backlog; few have a mechanism that checks nothing leaked out of it.
- **Layering enforcement is mechanical** (import-linter blocking CI + a redundant AST test) rather than a paragraph nobody re-reads. The redundancy is well-justified.
- **§4.1's co-location rule** (DB write and job side-effect in one service method) is exactly the right response to the failure mode it names, and it correctly identifies template propagation as the path most likely to be half-built.
- **§4.2 startup reconciliation** is a robustness measure most POCs discover only after losing data.
- **The changelog discipline** across design-doc revisions - including recording *reversed* decisions with their reasoning trail (§3.10 / §11 item 7) and preserving rejected alternatives as backlog items (12.20, 12.21) rather than losing them - is genuinely unusual and worth keeping up.
- **Stage 4's `first_day_of_week` regression guard** (feed two settings objects differing only in that field through the engine, assert identical output) is a good instinct: proving a "display-only" claim in code rather than asserting it in prose.

---

## 6. Suggested disposition

**Before Stage 1 can start:** B3, B4, B8, B9, H1, M7. These are all scheduling-engine inputs - the engine cannot be built correctly, or its acceptance tests written, without them. **All six were decided on 2026-08-06** (see the decision log in §0) and now await drafting into design-doc Revision 9. Stage 1 unblocks when Rev 9 lands, not when the decisions were taken - H1 in particular carries unconfirmed cascade sub-rules and is a scope addition rather than a correction.

**Before Stage 2:** B5, B6, B7 - **all decided 2026-08-06**, awaiting drafting.

**Before Stage 3:** B10, B11, B12, M9, M10 - **all decided 2026-08-06/07**, awaiting drafting. M8 (reset-marker storage) is folded into B10's decision.

**Before Stage 5:** B1 *(decided in outline, two residual rules)*, B2 *(decided, needs drafting)*, H2, H5, H6, H7, H10, H11, H12, H13.

**Before Stage 6:** H9, H14.

**Anytime (editorial, no dependency):** all of Section 4, plus M14.

Recommended vehicle: **design-doc Revision 9** for the product-level items, **architecture-plan Revision 3** for B6, B11, B12, H9, H14, M9, M10, M12, M13, and a **companion revision to the implementation plan** for the stage-assignment gaps (H12's unassigned recompute, H13's re-validation, L4, L5, L6, L10).
