"""Background-job scheduling interface. See architecture-plan §4, §4.1.

Every `TaskInstance` mutation path calls this interface at the correct call site, backed
in this stage by a no-op stub - Stage 6 swaps in a real APScheduler-backed adapter behind
the exact same interface, touching no call site. This is what closes architecture-plan
§4.1's warning that job wiring is "the one path most likely to be half-implemented by
accident": the wiring is correct now, even though nothing is actually scheduled yet.
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


class NoOpJobScheduler(JobScheduler):
    """Stage 5's production implementation: schedules and cancels nothing.

    Correct today because nothing else in the app has ever fired a job either - there is
    no regression to cause. `tests.fixtures.jobs.RecordingJobScheduler` is the test
    double that makes the wiring itself assertable.
    """

    def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
        return None

    def cancel(self, *, job_key: str) -> None:
        return None

    def cancel_all_for_instance(self, *, instance_id: str) -> None:
        return None


def reminder_job_key(instance_id: str, offset_minutes: int) -> str:
    """One key per (instance, reminder offset) - an instance may have several reminders."""
    return f"reminder:{instance_id}:{offset_minutes}"


def overdue_job_key(instance_id: str) -> str:
    return f"overdue:{instance_id}"


def deadline_elapsed_job_key(instance_id: str) -> str:
    return f"deadline_elapsed:{instance_id}"


_job_scheduler: JobScheduler = NoOpJobScheduler()


def get_job_scheduler() -> JobScheduler:
    """FastAPI dependency / general accessor for the process-wide job scheduler."""
    return _job_scheduler
