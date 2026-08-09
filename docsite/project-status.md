# Project Status & Scope

Tessera is being built as a proof-of-concept (POC) with a deliberately fixed scope boundary. This page exists so that boundary - and the current build progress - can change without needing edits to every other page of this guide.

## What's in scope for the POC

- Single user, password login, first-run setup wizard
- Read-only external calendar sync (polling - Google, Outlook)
- One fixed greedy scheduling algorithm (see [Scheduling Algorithm](scheduling-algorithm.md))
- Global active-hours + per-task override + manual blackout dates + soft daily time-budget
- Fixed-task hard-block on conflicts (no soft override)
- Task dependencies (on instances, not templates) with a dedicated Backlog view
- Two recurrence anchor modes (`calendar` / `completion`)
- Two-scope editing/deletion for recurring tasks ("this occurrence" vs. "this and future")
- In-app notifications only
- WebUI only, single self-hosted container

## What's explicitly out of scope (not "while you're in there")

These are deliberate exclusions, not oversights - documented in the design doc's backlog sections so they don't get quietly built as "prep work" for something else:

- Multi-user or shared timelines
- Location-aware scheduling or commute time
- Automatic task splitting (a task that can't fit is hard-blocked at creation instead - see [Tasks & Events](tasks-and-events.md))
- Multiple selectable scheduling algorithms
- Holiday calendars
- Email/IM notification channels
- Write access to external calendars (read-only polling only)

## Current build progress

This project is built in sequential stages, each merged as its own PR. As of this guide's last update:

| Stage | Area | Status |
|---|---|---|
| 0 | Bootstrap & tooling | Done |
| 1 | Scheduling engine | Done |
| 2 | Data access layer | Done |
| 3 | Auth & sessions | Done |
| 4 | User settings | Done |
| 5 | Task domain (templates, instances, notifications) | Done |
| 6 | Background jobs & reconciliation | Done |
| 7 | Calendar sync | Done |
| 8 | API hardening & backend E2E | Done |
| 9 | Frontend | In progress |
| 10 | Deployment & packaging | Not started |
| 11 | Hardening & release readiness | Not started |

In short: the backend - scheduling engine, data layer, auth, settings, task/notification domain, background jobs, calendar sync, and the full API contract - is functionally complete. The web frontend is under active development, so parts of this guide (particularly UI-flow descriptions) describe designed, not-yet-visually-verified behavior.

For the authoritative, continuously-updated stage-by-stage tracker (including per-stage implementation notes and what was deferred within each), see [`docs/implementation-plan.md`](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/implementation-plan.md) in the repository - that file, not this page, is the source of truth for build progress.
