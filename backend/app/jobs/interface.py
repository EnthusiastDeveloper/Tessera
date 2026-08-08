"""Background-job scheduling interface. See architecture-plan §4, §4.1.

Every `TaskInstance`/`TaskTemplate` mutation path calls this interface at the correct call
site rather than importing APScheduler directly - `app.jobs.scheduler.APSchedulerJobScheduler`
(Stage 6) is the real, production-facing implementation; `NoOpJobScheduler` remains available
for contexts that need the interface satisfied without a job store.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class JobScheduler(ABC):
    """One job per `job_key()` - callers use the key-builder functions below so every
    call site derives the same key the same way.
    """

    @abstractmethod
    def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
        """Schedule (or reschedule, replacing any existing job under the same key) a one-off job."""

    @abstractmethod
    def cancel(self, *, job_key: str) -> None:
        """Cancel a single job by key. A no-op if no job exists under that key."""

    @abstractmethod
    def cancel_all_for_instance(self, *, instance_id: str) -> None:
        """Cancel every job (reminders, overdue check, deadline-elapsed check) for an instance -
        used on completion, dismissal, and deletion, where the instance leaves the live pool
        entirely and every one of its jobs becomes an orphan by definition.
        """

    @abstractmethod
    def schedule_interval(self, *, job_key: str, minutes: int) -> None:
        """Schedule (or reschedule, replacing any existing job under the same key) a job
        that fires every `minutes` minutes - the deadline-elapsed safety-net sweep (§6.7)
        and Stage 7's external-calendar poll. Dependency-at-risk (§6.3) is a one-off per
        instance instead (architecture-plan §4's job breakdown: "schedule a one-off check
        at deadline - 3 days ... rather than scanning the whole table on an interval").
        """


class NoOpJobScheduler(JobScheduler):
    """Retained as a lightweight scheduler for contexts that need the interface satisfied
    without a real job store (e.g. one-off scripts). Production now uses
    `app.jobs.scheduler.APSchedulerJobScheduler` (Stage 6). `tests.fixtures.jobs.RecordingJobScheduler`
    is the test double that makes the wiring itself assertable.
    """

    def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
        return None

    def cancel(self, *, job_key: str) -> None:
        return None

    def cancel_all_for_instance(self, *, instance_id: str) -> None:
        return None

    def schedule_interval(self, *, job_key: str, minutes: int) -> None:
        return None


def reminder_job_key(instance_id: str, offset_minutes: int) -> str:
    """One key per (instance, reminder offset) - an instance may have several reminders."""
    return f"reminder:{instance_id}:{offset_minutes}"


def overdue_job_key(instance_id: str) -> str:
    return f"overdue:{instance_id}"


def deadline_elapsed_job_key(instance_id: str) -> str:
    return f"deadline_elapsed:{instance_id}"


def dependency_at_risk_job_key(instance_id: str) -> str:
    return f"dependency_at_risk:{instance_id}"


def occurrence_boundary_job_key(template_id: str) -> str:
    """The calendar-anchor recurring-generation job (§9.1, architecture-plan §4's job
    breakdown table) - template-scoped, not instance-scoped, so it is deliberately outside
    `cancel_all_for_instance`'s reach.
    """
    return f"occurrence_boundary:{template_id}"


#: Singleton key for the §6.7 periodic deadline-elapsed safety-net sweep - one recurring
#: job for the whole table, not per-instance (the inline gate + the one-off per-instance
#: job are the primary mechanism; this just catches anything they missed).
DEADLINE_ELAPSED_SWEEP_JOB_KEY = "sweep:deadline_elapsed"

#: Not specified in either source doc - frequent enough that a missed deadline is caught
#: promptly, infrequent enough not to be wasteful given the inline gate and the one-off
#: per-instance job are already the primary mechanism (this is only the safety net).
DEADLINE_ELAPSED_SWEEP_INTERVAL_MINUTES = 15

_job_scheduler: JobScheduler = NoOpJobScheduler()


def get_job_scheduler() -> JobScheduler:
    """FastAPI dependency / general accessor for the process-wide job scheduler."""
    return _job_scheduler


def set_job_scheduler(scheduler: JobScheduler) -> None:
    """Swap the process-wide job scheduler - called once at startup (main.py's lifespan)
    to install the real adapter, and by tests that need a scoped override.
    """
    global _job_scheduler
    _job_scheduler = scheduler
