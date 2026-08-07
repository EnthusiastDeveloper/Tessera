---
name: debug-tessera
description: Playbook for diagnosing Tessera bugs - wrong scheduling behavior, reminders/overdue/deadline checks not firing, dependency graphs staying blocked, unexpected 409 Conflicts, or external calendar events not blocking placement. Use when something in Tessera is broken and you need to know where to look first.
---

# When Something Breaks

1. **Scheduling behavior is wrong (task placed at wrong time)?**
   - Check design-doc Section 6.2 (algorithm) and Section 14.1 (timezone handling)
   - Run the Worked Examples (design-doc Section 10, A–K) as acceptance tests to isolate whether it's the algorithm or a data-layer issue
   - Narrow to the scheduling_engine unit tests first (it's pure, deterministic, testable in isolation)

2. **A reminder/overdue/deadline check didn't fire?**
   - Check architecture-plan 4.1 and 4.2: did the mutation path wire the job? Did the reconciliation pass run at startup?
   - Verify APScheduler job store isn't out of sync with `TaskInstance` rows (4.2 reconciliation should catch this, but look at the reconciliation test coverage)

3. **Dependency graph seems broken (task stayed blocked when it should've unblocked)?**
   - Check design-doc 3.8 (deletion rules) and Section 4 (status lifecycle)
   - Remember: `missed` is not `completed` (design-doc 6.7) - a downstream task depending on a `missed` task stays blocked

4. **API returned `409 Conflict` unexpectedly?**
   - Check architecture-plan Section 5.1: background jobs and template propagation write to `TaskInstance` too
   - The app tries to auto-retry if the fields don't overlap; real overlap shows a conflict UI in the frontend
   - If the `updated_at` check is too strict, the fix is in the diff-based retry logic (5.1), not in bypassing the check

5. **External calendar events aren't blocking placement?**
   - Check design-doc Section 7 (event filtering): transparent/"Free" events and all-day events are excluded from the obstacle set by default (display-only)
   - All-day events show on Timeline but don't block scheduling in POC (design-doc 7, confirmed Rev 8)
   - Webhook-based sync is backlog (12.5); POC uses polling
