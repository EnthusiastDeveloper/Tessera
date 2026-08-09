# Tessera

**Self-hosted task scheduling that respects the real shape of your day.**

Tessera fits your flexible tasks into the gaps left by fixed commitments, deadlines, priorities, and dependencies - inside a daily capacity you set, not just wherever a slot happens to be free.

You list what needs doing and how urgent or flexible it is. Tessera figures out *when* to actually do it, without double-booking your real life or scheduling things at hours that don't make sense.

## Who this is for

Tessera is built for one person to run for themselves: a single-user, self-hosted app you deploy on your own hardware (a home server, a NAS, a small VPS) and point a browser at. There's no multi-tenant account system, no cloud service to sign up for, and no telemetry leaving your box.

If you've ever maintained a to-do list that quietly became a lie - full of things you wrote down but never scheduled - Tessera's whole reason to exist is closing that gap between *listed* and *placed on a timeline*.

## What makes it different from a plain to-do list or calendar

| A calendar | A to-do list | Tessera |
|---|---|---|
| You decide every time slot yourself | Nothing has a time slot | Fixed tasks keep their exact time; flexible tasks get auto-placed for you |
| No concept of "this can't fit" | No concept of "this can't fit" | Rejects a task at creation if it could never physically fit your schedule |
| No task dependencies | No scheduling around dependencies | A task literally cannot be placed until what it depends on is done |
| Blind to your other calendars unless you paste events in manually | N/A | Reads your external calendars read-only and never double-books against them |

## How to use this guide

- **[Getting Started](installation.md)** - install Tessera, bring it up in a container, and get through first-run setup.
- **[Capabilities](capabilities.md)** - a tour of what Tessera actually does, end to end.
- **[Configuration](configuration.md)** - environment variables and the settings that shape scheduling (active hours, budgets, blackout dates, timezone).
- **[Tasks & Events](tasks-and-events.md)** - fixed vs. flexible tasks, recurrence, statuses, dependencies, and how editing/deleting a recurring task works.
- **[Scheduling Algorithm](scheduling-algorithm.md)** - how Tessera actually decides where to put a task, with worked examples.
- **[Notifications](notifications.md)** - what Tessera tells you and why.
- **[FAQ & Troubleshooting](faq.md)** - common setup and operational questions.
- **[Project Status & Scope](project-status.md)** - what's in scope for the current build, what's deliberately deferred, and where to check build progress.
- **[Contributing](contributing.md)** - if you're picking up development work on Tessera itself.

## Project links

- [Source code on GitHub](https://github.com/EnthusiastDeveloper/Tessera)
- [Design document](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/design-doc.md) - the authoritative product specification, for anyone who wants the full detail behind this guide
- [Architecture plan](https://github.com/EnthusiastDeveloper/Tessera/blob/main/docs/architecture-plan.md) - how the system is structured and built
