"""Real, production-facing `JobScheduler` backed by APScheduler with a persistent,
SQLAlchemy-backed job store (architecture-plan §4 - "persistence is not optional ... every
scheduled reminder/overdue check is silently lost on container restart, which will happen
on any self-hosted deployment"). The job store uses its own dedicated SQLite file
(`app.db.session.jobs_database_path`), not the app's own - see that function's docstring
for why: architecture-plan flags a *shared* file as "should be fine (WAL mode), but verify
explicitly", and that verification found the assumption doesn't hold once §4.1's
co-location rule is in play (a job-store write routinely happens on a second connection
while the triggering request's own transaction is still open on the first).

`schedule_at`/`cancel`/`schedule_interval` never receive a callback, only a `job_key` and a
time - APScheduler's persistent job store requires an importable function reference, not a
closure, so every job is registered against the single module-level `_dispatch` function
below. At fire time, `_dispatch` re-derives what to do by parsing the key's type prefix and
re-reading fresh state from the database via `app.jobs.handlers` - jobs are fire-and-forget
against state that can have moved on since they were scheduled, never a snapshot.
"""

from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import Engine

from app.db.session import session_scope
from app.jobs import handlers
from app.jobs.interface import JobScheduler, get_job_scheduler
from app.jobs.transactional import TransactionalJobScheduler

logger = logging.getLogger(__name__)

#: job-key prefixes that identify an instance-scoped job - `cancel_all_for_instance`
#: matches against these; `occurrence_boundary` (template-scoped) and `sweep` (global) are
#: deliberately excluded, see their own key builders' docstrings.
_INSTANCE_SCOPED_PREFIXES = frozenset({"reminder", "overdue", "deadline_elapsed", "dependency_at_risk"})


class APSchedulerJobScheduler(JobScheduler):
    def __init__(self, engine: Engine) -> None:
        """`engine` should be `app.db.session.get_jobs_engine()` in production - its own
        dedicated SQLite file, deliberately not the app's own engine (see this module's
        docstring). Takes an engine rather than reaching for that itself so tests can pass
        an isolated one.
        """
        jobstore = SQLAlchemyJobStore(engine=engine)
        self._scheduler = BackgroundScheduler(jobstores={"default": jobstore})

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self, *, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)

    def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
        # misfire_grace_time=None: always fire when the scheduler catches up, however late -
        # a dropped reminder/overdue/deadline-elapsed check has no other path to notice it.
        self._scheduler.add_job(
            _dispatch, "date", run_date=run_at, args=[job_key], id=job_key, replace_existing=True, misfire_grace_time=None
        )

    def cancel(self, *, job_key: str) -> None:
        try:
            self._scheduler.remove_job(job_key)
        except JobLookupError:
            pass

    def cancel_all_for_instance(self, *, instance_id: str) -> None:
        for job in self._scheduler.get_jobs():
            parts = job.id.split(":")
            if len(parts) >= 2 and parts[0] in _INSTANCE_SCOPED_PREFIXES and parts[1] == instance_id:
                self.cancel(job_key=job.id)

    def schedule_interval(self, *, job_key: str, minutes: int) -> None:
        self._scheduler.add_job(
            _dispatch,
            IntervalTrigger(minutes=minutes),
            args=[job_key],
            id=job_key,
            replace_existing=True,
            misfire_grace_time=None,
        )


def _dispatch(job_key: str) -> None:
    """The one function reference APScheduler ever stores - routes `job_key` to the
    matching `app.jobs.handlers` function against a fresh session. Exceptions are caught
    and logged rather than left to propagate into APScheduler's executor: one job failing
    must not take down the scheduler thread or silently cancel jobs still pending.
    """
    try:
        with session_scope() as db:
            # Bound to this job's own transaction, same as a request's (issue #23): a
            # handler that raises must not leave half its job-store changes applied.
            jobs = TransactionalJobScheduler(get_job_scheduler(), db)
            parts = job_key.split(":")
            kind = parts[0]
            if kind == "reminder":
                handlers.run_reminder(db, instance_id=parts[1], offset_minutes=int(parts[2]))
            elif kind == "overdue":
                handlers.run_overdue_check(db, jobs, instance_id=parts[1])
            elif kind == "deadline_elapsed":
                handlers.run_deadline_elapsed_check(db, jobs, instance_id=parts[1])
            elif kind == "dependency_at_risk":
                handlers.run_dependency_at_risk_check(db, instance_id=parts[1])
            elif kind == "occurrence_boundary":
                handlers.run_occurrence_boundary(db, jobs, template_id=parts[1])
            elif kind == "sweep" and len(parts) > 1 and parts[1] == "deadline_elapsed":
                handlers.run_deadline_elapsed_sweep(db, jobs)
            elif kind == "calendar_poll":
                handlers.run_calendar_poll(db, jobs, connection_id=parts[1])
            else:
                logger.warning("Unrecognized job key fired: %s", job_key)
    except Exception:
        logger.exception("Job %r raised - its effects rolled back; the scheduler continues.", job_key)


__all__ = ["APSchedulerJobScheduler"]
