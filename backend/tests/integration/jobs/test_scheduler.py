"""Integration tests for APSchedulerJobScheduler - the real adapter actually persisting
jobs and firing them, not just the interface being called correctly (that's
tests/job_wiring/). Uses real timing (short waits for the background thread), which is
inherent to testing a background scheduler - there is no synchronous alternative.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.db.base import Base, generate_id, utcnow
from app.db.repositories import (
    NotificationRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
    UserSettingsRepository,
)
from app.db.schemas import ActiveHoursWindow, Recurrence, StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.db.session import build_engine, get_engine, get_session_factory, session_scope, sqlite_url
from app.jobs import handlers
from app.jobs.interface import (
    DEADLINE_ELAPSED_SWEEP_JOB_KEY,
    calendar_poll_job_key,
    deadline_elapsed_job_key,
    dependency_at_risk_job_key,
    occurrence_boundary_job_key,
    overdue_job_key,
    reminder_job_key,
    set_job_scheduler,
)
from app.jobs.scheduler import APSchedulerJobScheduler
from app.settings.service import DAY_NAMES

_POLL_INTERVAL_SECONDS = 0.1
_POLL_TIMEOUT_SECONDS = 5.0


def _wait_until(predicate: Callable[[], bool]) -> bool:
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(_POLL_INTERVAL_SECONDS)
    return False


@pytest.fixture
def wired_scheduler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[APSchedulerJobScheduler]:
    """A real APSchedulerJobScheduler against a temp app DB and a separate temp jobs DB,
    installed as the process-wide singleton (handlers fetch it via get_job_scheduler()).
    """
    db_path = tmp_path / "tessera.db"
    jobs_path = tmp_path / "tessera.jobs.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    Base.metadata.create_all(get_engine())

    jobs_engine = build_engine(sqlite_url(str(jobs_path)))
    scheduler = APSchedulerJobScheduler(jobs_engine)
    set_job_scheduler(scheduler)
    scheduler.start()

    yield scheduler

    scheduler.shutdown(wait=True)  # block until the background thread's connections are released
    jobs_engine.dispose()
    get_engine().dispose()
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


def _seed_settings() -> UserSettings:
    with session_scope() as db:
        return UserSettingsRepository(db).create(
            UserSettings(
                id=generate_id(),
                timezone="UTC",
                active_hours=dict.fromkeys(DAY_NAMES, ActiveHoursWindow(start="00:00", end="23:59")),
                blackout_dates=(),
                daily_time_budget_minutes=dict.fromkeys(DAY_NAMES, None),
                budget_enforcement="soft",
                first_day_of_week="monday",
            )
        )


def _seed_fixed_instance(*, scheduled_time: datetime) -> TaskInstance:
    now = utcnow()
    with session_scope() as db:
        template = TaskTemplateRepository(db).create(
            TaskTemplate(
                id=generate_id(),
                name="Doctor's appointment",
                type="fixed",
                fixed_time_of_day="09:00",
                recurrence=Recurrence(pattern="one_time", anchor="calendar"),
                priority="medium",
                estimated_duration_minutes=30,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        return TaskInstanceRepository(db).create(
            TaskInstance(
                id=generate_id(),
                template_id=template.id,
                name=template.name,
                type="fixed",
                priority=2,
                estimated_duration_minutes=30,
                status="scheduled",
                scheduled_time=scheduled_time,
                status_history=(StatusHistoryEntry(status="scheduled", at=now),),
                generated_at=now,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )


class TestScheduleAtFiring:
    def test_a_due_job_fires_and_runs_its_handler(self, wired_scheduler: APSchedulerJobScheduler) -> None:
        _seed_settings()
        instance = _seed_fixed_instance(scheduled_time=utcnow())

        wired_scheduler.schedule_at(job_key=reminder_job_key(instance.id, 0), run_at=utcnow())

        def _reminder_created() -> bool:
            with session_scope() as db:
                return any(n.type == "reminder" for n in NotificationRepository(db).list_for_instance(instance.id))

        assert _wait_until(_reminder_created), "reminder job never fired"


class TestDispatchRoutesEveryJobKind:
    """`_dispatch` (`app/jobs/scheduler.py`) is the single place a fired APScheduler job
    turns back into a handler call, by string-matching the `job_key`'s kind prefix - a
    typo there would silently no-op a job in production (falls into the `else`
    "unrecognized" branch, logged and swallowed, nothing else to surface it) rather than
    fail loudly. Every other test either calls `handlers.run_*` directly (bypassing
    key-parsing entirely) or only asserts *scheduling* happened (`tests/job_wiring/`),
    never firing. `TestScheduleAtFiring` above already proves the `reminder` branch
    fires for real through a live APScheduler thread; this proves the rest of the elif
    chain routes correctly too, by monkeypatching each handler to a recording stub so
    only the dispatch/parsing logic itself is under test, not each handler's own
    (separately-tested) domain behavior.
    """

    def test_overdue_kind_dispatches_to_run_overdue_check(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(handlers, "run_overdue_check", lambda db, jobs, *, instance_id: calls.append(instance_id))

        wired_scheduler.schedule_at(job_key=overdue_job_key("instance-abc"), run_at=utcnow())

        assert _wait_until(lambda: calls == ["instance-abc"]), "overdue job never dispatched"

    def test_deadline_elapsed_kind_dispatches_to_run_deadline_elapsed_check(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(handlers, "run_deadline_elapsed_check", lambda db, jobs, *, instance_id: calls.append(instance_id))

        wired_scheduler.schedule_at(job_key=deadline_elapsed_job_key("instance-def"), run_at=utcnow())

        assert _wait_until(lambda: calls == ["instance-def"]), "deadline_elapsed job never dispatched"

    def test_dependency_at_risk_kind_dispatches_to_run_dependency_at_risk_check(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(handlers, "run_dependency_at_risk_check", lambda db, *, instance_id: calls.append(instance_id))

        wired_scheduler.schedule_at(job_key=dependency_at_risk_job_key("instance-ghi"), run_at=utcnow())

        assert _wait_until(lambda: calls == ["instance-ghi"]), "dependency_at_risk job never dispatched"

    def test_occurrence_boundary_kind_dispatches_to_run_occurrence_boundary(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(handlers, "run_occurrence_boundary", lambda db, jobs, *, template_id: calls.append(template_id))

        wired_scheduler.schedule_at(job_key=occurrence_boundary_job_key("template-jkl"), run_at=utcnow())

        assert _wait_until(lambda: calls == ["template-jkl"]), "occurrence_boundary job never dispatched"

    def test_calendar_poll_kind_dispatches_to_run_calendar_poll(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(handlers, "run_calendar_poll", lambda db, jobs, *, connection_id: calls.append(connection_id))

        wired_scheduler.schedule_at(job_key=calendar_poll_job_key("connection-mno"), run_at=utcnow())

        assert _wait_until(lambda: calls == ["connection-mno"]), "calendar_poll job never dispatched"

    def test_sweep_deadline_elapsed_kind_dispatches_to_run_deadline_elapsed_sweep(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []
        monkeypatch.setattr(handlers, "run_deadline_elapsed_sweep", lambda db, jobs: calls.append(True))

        wired_scheduler.schedule_at(job_key=DEADLINE_ELAPSED_SWEEP_JOB_KEY, run_at=utcnow())

        assert _wait_until(lambda: calls == [True]), "sweep:deadline_elapsed job never dispatched"

    def test_an_unrecognized_kind_is_logged_and_swallowed_rather_than_raised(
        self, wired_scheduler: APSchedulerJobScheduler, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="app.jobs.scheduler"):
            wired_scheduler.schedule_at(job_key="not_a_real_kind:xyz", run_at=utcnow())
            assert _wait_until(lambda: "Unrecognized job key fired" in caplog.text)

    def test_a_handler_that_raises_is_logged_and_does_not_kill_the_scheduler_thread(
        self, wired_scheduler: APSchedulerJobScheduler, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        def _boom(db: object, jobs: object, *, instance_id: str) -> None:
            raise RuntimeError("simulated handler failure")

        monkeypatch.setattr(handlers, "run_overdue_check", _boom)

        with caplog.at_level(logging.ERROR, logger="app.jobs.scheduler"):
            wired_scheduler.schedule_at(job_key=overdue_job_key("instance-boom"), run_at=utcnow())
            assert _wait_until(lambda: "raised" in caplog.text)

        # The scheduler thread survived the raise - a second, unrelated job still fires.
        calls: list[str] = []
        monkeypatch.setattr(handlers, "run_overdue_check", lambda db, jobs, *, instance_id: calls.append(instance_id))
        wired_scheduler.schedule_at(job_key=overdue_job_key("instance-after-boom"), run_at=utcnow())
        assert _wait_until(lambda: calls == ["instance-after-boom"])


class TestCancel:
    def test_cancelling_before_it_fires_prevents_the_side_effect(self, wired_scheduler: APSchedulerJobScheduler) -> None:
        _seed_settings()
        instance = _seed_fixed_instance(scheduled_time=utcnow())

        run_at = utcnow()
        wired_scheduler.schedule_at(job_key=reminder_job_key(instance.id, 0), run_at=run_at)
        wired_scheduler.cancel(job_key=reminder_job_key(instance.id, 0))

        time.sleep(1.5)  # give a wrongly-still-scheduled job a chance to fire
        with session_scope() as db:
            assert NotificationRepository(db).list_for_instance(instance.id) == ()

    def test_cancelling_an_unknown_key_is_a_no_op(self, wired_scheduler: APSchedulerJobScheduler) -> None:
        wired_scheduler.cancel(job_key="reminder:does-not-exist:0")  # must not raise


class TestCancelAllForInstance:
    def test_cancels_every_instance_scoped_job_but_not_others(self, wired_scheduler: APSchedulerJobScheduler) -> None:
        _seed_settings()
        far_future = utcnow() + timedelta(hours=1)
        instance = _seed_fixed_instance(scheduled_time=far_future)
        other = _seed_fixed_instance(scheduled_time=far_future)

        wired_scheduler.schedule_at(job_key=reminder_job_key(instance.id, 15), run_at=far_future)
        wired_scheduler.schedule_at(job_key=overdue_job_key(instance.id), run_at=far_future)
        wired_scheduler.schedule_at(job_key=dependency_at_risk_job_key(instance.id), run_at=far_future)
        wired_scheduler.schedule_at(job_key=overdue_job_key(other.id), run_at=far_future)

        wired_scheduler.cancel_all_for_instance(instance_id=instance.id)

        remaining = {job.id for job in wired_scheduler._scheduler.get_jobs()}  # test-only introspection
        assert remaining == {overdue_job_key(other.id)}


class TestScheduleInterval:
    def test_registers_a_recurring_job_with_the_right_cadence(self, wired_scheduler: APSchedulerJobScheduler) -> None:
        """IntervalTrigger's first fire lands a full interval after `now`, not
        immediately - waiting out a real interval to prove firing isn't worth a minute-plus
        test given `schedule_at`'s firing path (tested above) exercises the identical
        `_dispatch` mechanism. This proves the registration side: the job exists with the
        expected interval, matching implementation-plan Stage 6's "mechanism only" scope
        for the interval-based jobs (the periodic sweep, Stage 7's external poll).
        """
        from apscheduler.triggers.interval import IntervalTrigger

        wired_scheduler.schedule_interval(job_key="sweep:deadline_elapsed", minutes=15)

        job = wired_scheduler._scheduler.get_job("sweep:deadline_elapsed")  # test-only introspection
        assert job is not None
        assert isinstance(job.trigger, IntervalTrigger)
        assert job.trigger.interval == timedelta(minutes=15)

    def test_replaces_an_existing_interval_job_under_the_same_key(self, wired_scheduler: APSchedulerJobScheduler) -> None:
        wired_scheduler.schedule_interval(job_key="sweep:deadline_elapsed", minutes=15)
        wired_scheduler.schedule_interval(job_key="sweep:deadline_elapsed", minutes=30)

        jobs_with_that_key = [j for j in wired_scheduler._scheduler.get_jobs() if j.id == "sweep:deadline_elapsed"]
        assert len(jobs_with_that_key) == 1
        assert jobs_with_that_key[0].trigger.interval == timedelta(minutes=30)
