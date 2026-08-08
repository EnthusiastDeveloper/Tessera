"""Test double for app.jobs.interface.JobScheduler - records calls instead of no-op'ing,
so job-wiring tests can assert exactly what a mutation path scheduled/cancelled.
"""

from __future__ import annotations

from datetime import datetime

from app.jobs.interface import JobScheduler


class RecordingJobScheduler(JobScheduler):
    def __init__(self) -> None:
        self.scheduled: list[tuple[str, datetime]] = []
        self.cancelled: list[str] = []
        self.cancelled_instances: list[str] = []

    def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
        self.scheduled.append((job_key, run_at))

    def cancel(self, *, job_key: str) -> None:
        self.cancelled.append(job_key)

    def cancel_all_for_instance(self, *, instance_id: str) -> None:
        self.cancelled_instances.append(instance_id)

    def scheduled_keys(self) -> set[str]:
        return {key for key, _ in self.scheduled}
