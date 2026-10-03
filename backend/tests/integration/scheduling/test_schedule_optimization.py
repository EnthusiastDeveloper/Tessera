"""Schedule optimization - "Optimize Schedule" (design doc §6.11, Rev 14; architecture-plan
§4, §4.1, §5.4). `_NOW` is Mon 2026-04-06 12:00 New York with 18:00-20:00 windows every day,
the fixtures of Worked Examples S-V; the job is run by hand, the way the scheduler would."""

from __future__ import annotations

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.repositories import (
    ExternalCalendarConnectionRepository,
    ExternalEventRepository,
    NotificationRepository,
    ScheduleOptimizationRepository,
    ScheduleRepairRepository,
    TaskInstanceRepository,
)
from app.db.schemas import ActiveHoursWindow, Recurrence, ScheduleRepair, TaskInstance, UserSettings
from app.jobs import handlers
from app.jobs.interface import deadline_elapsed_job_key, overdue_job_key, schedule_optimization_job_key
from app.jobs.reconciliation import reconcile_on_startup
from app.scheduling import optimization
from app.scheduling.optimization import OptimizationError
from app.settings import service as settings_service
from app.settings.service import DAY_NAMES
from app.task_instances.service import complete
from app.task_templates import service as task_templates_service
from app.task_templates.service import TaskTemplateDraft, create_template
from tests.fixtures.db_entities import make_external_calendar_connection, make_external_event
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import ny

_NOW = ny(2026, 4, 6, 12, 0)
NY = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def pinned_now(monkeypatch: pytest.MonkeyPatch, db_session: Session, settings: UserSettings) -> None:
    for module in (task_templates_service, handlers, settings_service, optimization):
        monkeypatch.setattr(module, "utcnow", lambda: _NOW)
    settings_service.update_settings(
        db_session,
        RecordingJobScheduler(),
        patch={"active_hours": {day: [ActiveHoursWindow(start="18:00", end="20:00")] for day in DAY_NAMES}},
    )
    db_session.commit()


def _task(db: Session, jobs: RecordingJobScheduler, name: str, minutes: int, priority: str, deadline_day: int) -> TaskInstance:
    """A one-time flexible task due at 20:00 on day `deadline_day` (0 = Mon 6 Apr), created now."""
    created = create_template(
        db,
        jobs,
        TaskTemplateDraft(
            name=name,
            type="flexible",
            recurrence=Recurrence(pattern="one_time", anchor="calendar"),
            priority=priority,  # type: ignore[arg-type]
            estimated_duration_minutes=minutes,
            deadline_offset_minutes=(deadline_day * 24 + 20) * 60,
            start_date=date(2026, 4, 6),
        ),
    )
    db.commit()
    return created.instance


def _get(db: Session, instance_id: str) -> TaskInstance:
    instance = TaskInstanceRepository(db).get(instance_id)
    assert instance is not None
    return instance


def _slot(db: Session, instance_id: str) -> tuple[str, str | None]:
    instance = _get(db, instance_id)
    when = instance.scheduled_time.astimezone(NY).strftime("%a %H:%M") if instance.scheduled_time else None
    return instance.status, when


def _request_and_run(db: Session, jobs: RecordingJobScheduler):  # type: ignore[no-untyped-def]
    row = optimization.request_optimization(db, jobs, now=_NOW)
    db.commit()
    handlers.run_schedule_optimization(db, jobs, optimization_id=row.id)
    db.commit()
    return ScheduleOptimizationRepository(db).get(row.id)


def _example_s(db: Session, jobs: RecordingJobScheduler) -> dict[str, TaskInstance]:
    return {
        "B": _task(db, jobs, "B", 30, "high", 2),
        "C": _task(db, jobs, "C", 60, "low", 1),
        "A": _task(db, jobs, "A", 60, "low", 0),
    }


def _example_t(db: Session, jobs: RecordingJobScheduler) -> dict[str, TaskInstance]:
    return {
        "B": _task(db, jobs, "B", 60, "high", 0),
        "A": _task(db, jobs, "A", 60, "low", 0),
        "C": _task(db, jobs, "C", 60, "medium", 0),
    }


class TestACleanOptimizationAppliesAtOnce:
    """Example S."""

    def test_it_applies_without_asking_and_records_the_summary_and_undo(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_s(db_session, jobs)
        assert _slot(db_session, tasks["B"].id) == ("scheduled", "Mon 18:00")
        assert _slot(db_session, tasks["A"].id)[0] == "pending"

        row = optimization.request_optimization(db_session, jobs, now=_NOW)
        db_session.commit()
        assert row.status == "running"
        assert (schedule_optimization_job_key(row.id), _NOW) in jobs.scheduled
        handlers.run_schedule_optimization(db_session, jobs, optimization_id=row.id)
        db_session.commit()

        done = ScheduleOptimizationRepository(db_session).get(row.id)
        assert done is not None and done.status == "applied"
        assert done.undo_until == _NOW + optimization.UNDO_WINDOW
        assert _slot(db_session, tasks["A"].id) == ("scheduled", "Mon 18:00")
        assert _slot(db_session, tasks["C"].id) == ("scheduled", "Mon 19:00")
        assert _slot(db_session, tasks["B"].id) == ("scheduled", "Tue 18:00")
        assert set(done.applied_versions or {}) == {t.id for t in tasks.values()}

        summary = optimization.build_summary(db_session, done)
        assert summary is not None
        assert summary["counts"] == {
            "newly_scheduled": 1, "moved": 2, "lost": 0, "over_budget": 0, "unchanged": 0, "still_unplaced": 0,
        }  # fmt: skip
        assert [m["name"] for m in summary["moved"]] == ["C", "B"]  # chronological by new time

    def test_every_moved_task_has_its_jobs_re_pointed_and_the_placed_one_gets_them(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_s(db_session, jobs)
        jobs.scheduled.clear()
        jobs.cancelled.clear()

        _request_and_run(db_session, jobs)

        scheduled = dict(jobs.scheduled)
        assert scheduled[overdue_job_key(tasks["B"].id)] == ny(2026, 4, 7, 18, 0)  # moved Mon -> Tue
        assert scheduled[overdue_job_key(tasks["C"].id)] == ny(2026, 4, 6, 19, 0)
        assert scheduled[overdue_job_key(tasks["A"].id)] == ny(2026, 4, 6, 18, 0)  # newly scheduled
        assert deadline_elapsed_job_key(tasks["A"].id) in jobs.cancelled  # no longer waiting for a slot

    def test_the_placed_task_s_unschedulable_notification_is_resolved(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_s(db_session, jobs)
        before = [n for n in NotificationRepository(db_session).list_for_instance(tasks["A"].id) if n.type == "unschedulable"]
        assert before and before[0].resolved_at is None

        _request_and_run(db_session, jobs)

        after = [n for n in NotificationRepository(db_session).list_for_instance(tasks["A"].id) if n.type == "unschedulable"]
        assert after[0].resolved_at is not None


class TestADegradationNeedsApproval:
    """Example T."""

    def test_nothing_is_written_until_the_user_approves(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        tasks = _example_t(db_session, jobs)
        row = _request_and_run(db_session, jobs)

        assert row is not None and row.status == "awaiting_approval"
        assert row.valid_until == _NOW + optimization.PLAN_VALID_FOR
        assert _slot(db_session, tasks["A"].id) == ("scheduled", "Mon 19:00")  # still has its place
        assert _slot(db_session, tasks["C"].id)[0] == "pending"
        summary = optimization.build_summary(db_session, row)
        assert summary is not None and [x["name"] for x in summary["lost"]] == ["A"]
        assert summary["lost"][0]["reason"] == "no_slot_before_deadline"
        assert not optimization.is_locked(db_session, now=_NOW)  # the user thinking locks nothing

    def test_approving_applies_exactly_that_plan(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        tasks = _example_t(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None

        approved = optimization.approve(db_session, jobs, row.id, now=_NOW)
        db_session.commit()
        assert approved.status == "running" and approved.approved
        handlers.run_schedule_optimization(db_session, jobs, optimization_id=row.id)
        db_session.commit()

        done = ScheduleOptimizationRepository(db_session).get(row.id)
        assert done is not None and done.status == "applied"
        assert _slot(db_session, tasks["C"].id) == ("scheduled", "Mon 19:00")
        assert _slot(db_session, tasks["A"].id) == ("pending", None)
        unschedulable = [
            n for n in NotificationRepository(db_session).list_for_instance(tasks["A"].id) if n.type == "unschedulable"
        ]
        assert unschedulable and unschedulable[-1].resolved_at is None
        assert overdue_job_key(tasks["A"].id) in jobs.cancelled  # a task with no slot keeps no overdue job

    def test_declining_changes_nothing_and_offers_no_undo(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        tasks = _example_t(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None

        declined = optimization.decline(db_session, row.id, now=_NOW)
        db_session.commit()

        assert declined.status == "declined" and declined.undo_until is None
        assert _slot(db_session, tasks["A"].id) == ("scheduled", "Mon 19:00")
        with pytest.raises(OptimizationError) as undo_error:
            optimization.undo(db_session, jobs, row.id, now=_NOW)
        assert undo_error.value.code == "undo_unavailable"

    def test_a_plan_that_changed_after_approval_is_judged_again_by_the_ordinary_rules(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        """The user approved "A loses its place". Before the job ran, C (the task that would have
        taken it) was completed: that plan is gone and nobody approved what is left."""
        tasks = _example_t(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None
        optimization.approve(db_session, jobs, row.id, now=_NOW)
        complete(db_session, jobs, tasks["C"].id)
        db_session.commit()

        handlers.run_schedule_optimization(db_session, jobs, optimization_id=row.id)
        db_session.commit()

        after = ScheduleOptimizationRepository(db_session).get(row.id)
        assert after is not None and after.plan_changed
        assert after.status == "nothing_to_do" and after.reason == "identical"
        assert _slot(db_session, tasks["A"].id) == ("scheduled", "Mon 19:00")  # nothing the user did not see

    def test_a_changed_plan_that_is_now_clean_applies_and_says_it_changed(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_t(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None
        optimization.approve(db_session, jobs, row.id, now=_NOW)
        complete(db_session, jobs, tasks["B"].id)  # frees 18:00: now C simply fits beside A
        db_session.commit()

        handlers.run_schedule_optimization(db_session, jobs, optimization_id=row.id)
        db_session.commit()

        after = ScheduleOptimizationRepository(db_session).get(row.id)
        assert after is not None and after.plan_changed and after.status == "applied"
        assert _slot(db_session, tasks["C"].id) == ("scheduled", "Mon 18:00")
        assert _slot(db_session, tasks["A"].id) == ("scheduled", "Mon 19:00")  # nobody lost anything

    def test_a_held_plan_expires_and_can_no_longer_be_approved(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        _example_t(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None

        later = _NOW + optimization.PLAN_VALID_FOR + timedelta(seconds=1)
        latest = optimization.latest(db_session, now=later)
        assert latest is not None and latest.status == "expired"
        with pytest.raises(OptimizationError) as error:
            optimization.approve(db_session, jobs, row.id, now=later)
        assert error.value.code == "optimization_expired"


class TestNothingToDo:
    def test_a_plan_that_would_place_fewer_tasks_is_not_offered(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        """Example U."""
        tasks = {
            "B": _task(db_session, jobs, "B", 60, "medium", 0),
            "C": _task(db_session, jobs, "C", 60, "low", 0),
            "A": _task(db_session, jobs, "A", 90, "high", 0),
        }
        row = _request_and_run(db_session, jobs)

        assert row is not None and row.status == "nothing_to_do" and row.reason == "would_place_fewer"
        assert row.undo_until is None
        assert _slot(db_session, tasks["B"].id) == ("scheduled", "Mon 18:00")
        assert _slot(db_session, tasks["C"].id) == ("scheduled", "Mon 19:00")

    def test_an_already_best_schedule_changes_nothing(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        task = _task(db_session, jobs, "Only", 60, "medium", 0)
        row = _request_and_run(db_session, jobs)
        assert row is not None and row.status == "nothing_to_do" and row.reason == "identical"
        assert _slot(db_session, task.id) == ("scheduled", "Mon 18:00")


class TestWhatStaysPut:
    def test_a_fixed_task_and_an_external_event_are_obstacles_the_plan_works_around(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        waiting = _task(db_session, jobs, "Waiting", 60, "low", 0)
        connection = ExternalCalendarConnectionRepository(db_session).create(make_external_calendar_connection())
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection.id, start=ny(2026, 4, 6, 18, 0), end=ny(2026, 4, 6, 19, 0), is_transparent=False
            )
        )
        db_session.commit()
        # The task was placed at 18:00 before the event existed (a sync that did not evict it).
        TaskInstanceRepository(db_session).update(
            _get(db_session, waiting.id).model_copy(update={"scheduled_time": ny(2026, 4, 6, 18, 0)})
        )
        db_session.commit()

        row = _request_and_run(db_session, jobs)

        assert row is not None and row.status == "applied"
        assert _slot(db_session, waiting.id) == ("scheduled", "Mon 19:00")  # around the event, never into it


class TestTheLock:
    def test_a_running_optimization_locks_edits_and_a_second_request_is_refused(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        optimization.request_optimization(db_session, jobs, now=_NOW)
        db_session.commit()

        assert optimization.is_locked(db_session, now=_NOW)
        with pytest.raises(OptimizationError) as error:
            optimization.request_optimization(db_session, jobs, now=_NOW)
        assert error.value.code == "optimization_in_progress"

    def test_a_repair_in_progress_refuses_one(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        ScheduleRepairRepository(db_session).create(ScheduleRepair(id="r", total=3, requested_at=_NOW))
        db_session.commit()
        with pytest.raises(OptimizationError) as error:
            optimization.request_optimization(db_session, jobs, now=_NOW)
        assert error.value.code == "repair_in_progress"

    def test_a_run_past_its_limit_is_declared_failed_and_releases_the_lock(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        row = optimization.request_optimization(db_session, jobs, now=_NOW)
        db_session.commit()
        late = _NOW + optimization.limits().timeout + timedelta(seconds=1)

        assert not optimization.is_locked(db_session, now=late)
        failed = optimization.latest(db_session, now=late)
        assert failed is not None and failed.id == row.id and failed.status == "failed"
        assert "Nothing was changed" in (failed.reason or "")

    def test_a_job_that_wakes_after_its_limit_applies_nothing(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        tasks = _example_s(db_session, jobs)
        row = optimization.request_optimization(db_session, jobs, now=_NOW)
        db_session.commit()
        late = _NOW + optimization.limits().timeout + timedelta(seconds=1)

        optimization.run(db_session, jobs, row.id, now=late)
        db_session.commit()

        assert _slot(db_session, tasks["A"].id)[0] == "pending"  # nothing was applied
        assert ScheduleOptimizationRepository(db_session).get(row.id).status == "running"  # type: ignore[union-attr]
        assert optimization.latest(db_session, now=late).status == "failed"  # type: ignore[union-attr]

    def test_the_limits_come_from_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert optimization.limits().slow_after == timedelta(seconds=10)
        assert optimization.limits().timeout == timedelta(seconds=30)
        monkeypatch.setenv("OPTIMIZATION_SLOW_AFTER_SECONDS", "3")
        monkeypatch.setenv("OPTIMIZATION_TIMEOUT_SECONDS", "7")
        get_settings.cache_clear()
        try:
            assert optimization.limits().slow_after == timedelta(seconds=3)
            assert optimization.limits().timeout == timedelta(seconds=7)
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_a_restart_fails_a_run_that_died_with_the_process(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        row = optimization.request_optimization(db_session, jobs, now=_NOW)
        db_session.commit()

        reconcile_on_startup(db_session, jobs)
        db_session.commit()

        restarted = ScheduleOptimizationRepository(db_session).get(row.id)
        assert restarted is not None and restarted.status == "failed" and "restart" in (restarted.reason or "")
        assert not optimization.is_locked(db_session, now=_NOW)

    def test_a_crash_during_the_run_is_recorded_as_failed_with_the_schedule_untouched(
        self, db_session: Session, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tasks = _example_s(db_session, jobs)
        row = optimization.request_optimization(db_session, jobs, now=_NOW)
        db_session.commit()

        def explode(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(optimization, "_apply", explode)
        handlers.run_schedule_optimization(db_session, jobs, optimization_id=row.id)
        db_session.commit()

        failed = ScheduleOptimizationRepository(db_session).get(row.id)
        assert failed is not None and failed.status == "failed"
        assert _slot(db_session, tasks["B"].id) == ("scheduled", "Mon 18:00")


class TestUndo:
    def test_it_puts_every_placement_back_with_jobs_and_notifications_following(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_s(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None and optimization.undo_blockers(db_session, row, now=_NOW) == []
        jobs.scheduled.clear()

        undone = optimization.undo(db_session, jobs, row.id, now=_NOW + timedelta(minutes=3))
        db_session.commit()

        assert undone.status == "undone" and undone.undo_until is None
        assert _slot(db_session, tasks["B"].id) == ("scheduled", "Mon 18:00")
        assert _slot(db_session, tasks["C"].id) == ("scheduled", "Mon 18:30")
        assert _slot(db_session, tasks["A"].id) == ("pending", None)
        scheduled = dict(jobs.scheduled)
        assert scheduled[overdue_job_key(tasks["B"].id)] == ny(2026, 4, 6, 18, 0)
        unschedulable = [
            n for n in NotificationRepository(db_session).list_for_instance(tasks["A"].id) if n.type == "unschedulable"
        ]
        assert unschedulable[-1].resolved_at is None  # A is waiting for a slot again

    def test_undoing_an_approved_degradation_gives_the_lost_task_its_place_back(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_t(db_session, jobs)
        held = _request_and_run(db_session, jobs)
        assert held is not None
        optimization.approve(db_session, jobs, held.id, now=_NOW)
        db_session.commit()
        handlers.run_schedule_optimization(db_session, jobs, optimization_id=held.id)
        db_session.commit()

        optimization.undo(db_session, jobs, held.id, now=_NOW + timedelta(minutes=1))
        db_session.commit()

        assert _slot(db_session, tasks["A"].id) == ("scheduled", "Mon 19:00")
        assert _slot(db_session, tasks["C"].id)[0] == "pending"

    @pytest.mark.parametrize("instance", ["B", "C", "A"])
    def test_it_is_unavailable_once_any_changed_task_was_touched(
        self, db_session: Session, jobs: RecordingJobScheduler, instance: str
    ) -> None:
        tasks = _example_s(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None
        complete(db_session, jobs, tasks[instance].id)
        db_session.commit()

        blockers = optimization.undo_blockers(db_session, row, now=_NOW)
        assert [b["reason"] for b in blockers] == ["instance_changed"]
        assert blockers[0]["instance_id"] == tasks[instance].id
        with pytest.raises(OptimizationError) as error:
            optimization.undo(db_session, jobs, row.id, now=_NOW)
        assert error.value.code == "undo_unavailable" and error.value.details == {"reasons": blockers}
        assert _slot(db_session, tasks["A"].id)[0] in ("scheduled", "completed")  # nothing was restored

    def test_it_is_unavailable_when_an_event_now_sits_in_a_slot_to_restore(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        tasks = _example_s(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None
        connection = ExternalCalendarConnectionRepository(db_session).create(make_external_calendar_connection())
        # B's old slot was Mon 18:00-18:30: an event synced there without evicting anyone.
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection.id, start=ny(2026, 4, 6, 18, 15), end=ny(2026, 4, 6, 18, 20), is_transparent=False
            )
        )
        db_session.commit()

        blockers = optimization.undo_blockers(db_session, row, now=_NOW)
        assert blockers and {b["reason"] for b in blockers} == {"slot_taken"}
        assert tasks["B"].id in {b["instance_id"] for b in blockers}

    def test_it_is_unavailable_after_the_window(self, db_session: Session, jobs: RecordingJobScheduler) -> None:
        _example_s(db_session, jobs)
        row = _request_and_run(db_session, jobs)
        assert row is not None
        late = _NOW + optimization.UNDO_WINDOW + timedelta(seconds=1)
        assert [b["reason"] for b in optimization.undo_blockers(db_session, row, now=late)] == ["window_elapsed"]
        with pytest.raises(OptimizationError) as error:
            optimization.undo(db_session, jobs, row.id, now=late)
        assert error.value.code == "optimization_expired"

    def test_only_the_latest_operation_can_be_undone_and_undo_is_not_repeatable(
        self, db_session: Session, jobs: RecordingJobScheduler
    ) -> None:
        _example_s(db_session, jobs)
        first = _request_and_run(db_session, jobs)
        assert first is not None
        optimization.undo(db_session, jobs, first.id, now=_NOW)
        db_session.commit()
        with pytest.raises(OptimizationError):
            optimization.undo(db_session, jobs, first.id, now=_NOW)  # already undone

        again = _request_and_run(db_session, jobs)
        assert again is not None and again.status == "applied"
        with pytest.raises(OptimizationError) as error:
            optimization.undo(db_session, jobs, first.id, now=_NOW)  # a newer one replaced it
        assert error.value.code == "undo_unavailable"
