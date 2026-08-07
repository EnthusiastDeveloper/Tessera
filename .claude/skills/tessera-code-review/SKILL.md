---
name: tessera-code-review
description: Code review checklist for Tessera changes - covers layering violations, job wiring, scheduling_engine purity, timezone handling, detach-flag/template propagation, error codes, and backlog-scope rejection. Use when reviewing a Tessera PR or diff, yours or a collaborator's.
---

# Code Review Checklist

- [ ] Does the change touch layering (Section 2)? Run `lint-imports` and check it passes.
- [ ] Does the change touch job wiring (architecture-plan 4.1)? Is the DB write + job side-effect co-located in one service method?
- [ ] Does the change touch `scheduling_engine/`? Verify zero imports of FastAPI, SQLAlchemy, or `app/`.
- [ ] Does the change affect timezone handling? Verify all persisted timestamps are UTC; user timezone is IANA name; re-projection uses a timezone-aware library, never raw offsets.
- [ ] Does the change add a mutation to `TaskInstance` or `TaskTemplate`? Verify detach-flag logic if it's instance-scoped (design-doc 3.10), template propagation if it's template-scoped.
- [ ] Does the change add a new error case? Verify the API returns a machine-readable error code (not just a generic 400), and the frontend handles it distinctly if needed.
- [ ] Does the change touch backlog scope (Sections 12–13 of design-doc)? **Reject it.** POC scope is locked.
