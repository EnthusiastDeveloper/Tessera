"""Commit-bound job scheduling. Fixes the ordering gap in architecture-plan §4.1's
co-location rule (GitHub issue #23).

§4.1 puts a mutation's DB write and its job side effects in one service method, but the
two stores don't share a transaction: the job store is a separate SQLite file with its
own engine (see `app.db.session.jobs_database_path`). A job call made mid-method commits
immediately, so if a later step in the same request raises and the DB transaction rolls
back, the job change survives it. Example: `complete()` cancels an instance's jobs, a
later step fails, the instance reverts to `scheduled` with no reminder or overdue job
left, and nothing reports it.

`TransactionalJobScheduler` wraps the real scheduler for the lifetime of one DB session.
Calls are buffered in order and replayed only after that session commits; a rollback
discards them. Call sites stay unchanged - they still co-locate their job calls with
their writes, which is what keeps the wiring reviewable - and the ordering guarantee
moves to the one place that owns the transaction boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.jobs.interface import JobScheduler

logger = logging.getLogger(__name__)


class TransactionalJobScheduler(JobScheduler):
    def __init__(self, inner: JobScheduler, session: Session) -> None:
        self._inner = inner
        self._pending: list[tuple[str, Callable[[], None]]] = []
        event.listen(session, "after_commit", self._flush)
        event.listen(session, "after_soft_rollback", self._discard)

    def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
        self._pending.append((job_key, lambda: self._inner.schedule_at(job_key=job_key, run_at=run_at)))

    def cancel(self, *, job_key: str) -> None:
        self._pending.append((job_key, lambda: self._inner.cancel(job_key=job_key)))

    def cancel_all_for_instance(self, *, instance_id: str) -> None:
        self._pending.append((instance_id, lambda: self._inner.cancel_all_for_instance(instance_id=instance_id)))

    def schedule_interval(self, *, job_key: str, minutes: int) -> None:
        self._pending.append((job_key, lambda: self._inner.schedule_interval(job_key=job_key, minutes=minutes)))

    def _flush(self, session: Session) -> None:
        pending, self._pending = self._pending, []
        for target, apply in pending:
            # The DB change is already committed, so re-raising here would only turn a
            # successful request into a 500 without undoing anything. Log it and carry on
            # with the remaining calls; startup reconciliation (§4.2) repairs the job store.
            try:
                apply()
            except Exception:
                logger.exception("Job-store update for %r failed after commit; startup reconciliation will repair it.", target)

    def _discard(self, session: Session, previous_transaction: object) -> None:
        self._pending.clear()


__all__ = ["TransactionalJobScheduler"]
