"""Schedule repair when the scheduling rules get stricter (design doc §6.10, Rev 11;
architecture-plan §4, §4.2, §5.2). `_NOW` is Mon 2026-03-02 08:00 New York; the default
active hours are 09:00-17:00 every day."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.db.repositories import NotificationRepository, ScheduleRepairRepository, TaskInstanceRepository
from app.db.schemas import ActiveHoursWindow, BlackoutDate, DayName, Recurrence, ScheduleRepair, TaskInstance, UserSettings
from app.jobs import handlers
from app.jobs.interface import schedule_repair_job_key
from app.jobs.reconciliation import reconcile_on_startup
from app.settings import service as settings_service
from app.settings.service import DAY_NAMES
from app.task_instances.service import start_progress
from app.task_templates import service as task_templates_service
from app.task_templates.service import TaskTemplateDraft, create_template, edit_template_this_and_future
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import ny

_NOW = ny(2026, 3, 2, 8, 0)


@pytest.fixture(autouse=True)
def pinned_now(monkeypatch: pytest.MonkeyPatch) -> None:
    for module in (task_templates_service, handlers, settings_service):
        monkeypatch.setattr(module, "utcnow", lambda: _NOW)


def _flexible(db: Session, jobs: RecordingJobScheduler, name: str, **overrides: object) -> TaskInstance:
    fields: dict[str, object] = {
        "name": name,
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 60,
        "deadline_offset_minutes": 60 * 24 * 5,
        "start_date": date(2026, 3, 2),
    }
    fields.update(overrides)
    created = create_template(db, jobs, TaskTemplateDraft(**fields))  # type: ignore[arg-type]
    db.commit()
    return created.instance


def _every_day(start: str, end: str) -> dict[DayName, list[ActiveHoursWindow] | None]:
    return {day: [ActiveHoursWindow(start=start, end=end)] for day in DAY_NAMES}


def _get(db: Session, instance_id: str) -> TaskInstance:
    instance = TaskInstanceRepository(db).get(instance_id)
    assert instance is not None
    return instance


def _save_and_run(db: Session, jobs: RecordingJobScheduler, patch: dict[str, object]) -> ScheduleRepair | None:
    """Saves the settings as `PATCH /settings` does, then runs the repair job it started."""
    settings_service.update_settings(db, jobs, patch=patch)
    db.commit()
    repair = ScheduleRepairRepository(db).latest()
    if repair is not None:
        handlers.run_schedule_repair(db, jobs, repair_id=repair.id)
        db.commit()
        repair = ScheduleRepairRepository(db).get(repair.id)
    return repair


class TestStartingARepair:
    def test_a_narrowed_window_that_strands_a_task_starts_a_repair_due_now(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        stranded = _flexible(db_session, jobs, "Stranded")
        assert stranded.scheduled_time == ny(2026, 3, 2, 9, 0)

        settings_service.update_settings(db_session, jobs, patch={"active_hours": _every_day("10:00", "17:00")})
        db_session.commit()

        repair = ScheduleRepairRepository(db_session).latest()
        assert repair is not None and repair.total == 1 and repair.finished_at is None
        assert (schedule_repair_job_key(repair.id), _NOW) in jobs.scheduled

    @pytest.mark.parametrize(
        "patch",
        [
            {"active_hours": _every_day("08:00", "18:00")},  # wider
            {"timezone": "Europe/London"},  # moves nothing (§14.1, Rev 11)
            {"daily_time_budget_minutes": dict.fromkeys(DAY_NAMES, 30)},  # soft budget: not a rule a slot breaks
        ],
    )
    def test_a_change_that_invalidates_nothing_starts_nothing(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, patch: dict[str, object]
    ) -> None:
        _flexible(db_session, jobs, "Fine where it is")
        settings_service.update_settings(db_session, jobs, patch=patch)
        db_session.commit()
        assert ScheduleRepairRepository(db_session).latest() is None


class TestRunningARepair:
    def test_it_moves_exactly_what_no_longer_fits_and_counts_progress(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        stranded = _flexible(db_session, jobs, "Stranded")
        fine = _flexible(db_session, jobs, "Fine")
        assert fine.scheduled_time == ny(2026, 3, 2, 10, 0)

        repair = _save_and_run(db_session, jobs, {"active_hours": _every_day("10:00", "17:00")})

        assert repair is not None
        assert (repair.total, repair.done, repair.moved, repair.unschedulable) == (1, 1, 1, 0)
        assert repair.finished_at == _NOW
        assert _get(db_session, stranded.id).scheduled_time == ny(2026, 3, 2, 11, 0)
        assert _get(db_session, fine.id).scheduled_time == ny(2026, 3, 2, 10, 0), "a slot that still fits never moves"

    def test_started_work_and_fixed_tasks_are_never_moved(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        started = _flexible(db_session, jobs, "Started")
        start_progress(db_session, started.id)
        fixed = _flexible(
            db_session,
            jobs,
            "Dentist",
            type="fixed",
            fixed_time_of_day="08:30",
            deadline_offset_minutes=None,
            estimated_duration_minutes=30,
        )
        db_session.commit()

        repair = _save_and_run(db_session, jobs, {"active_hours": _every_day("12:00", "17:00")})

        assert repair is None
        assert _get(db_session, started.id).scheduled_time == ny(2026, 3, 2, 9, 0)
        assert _get(db_session, fixed.id).scheduled_time == ny(2026, 3, 2, 8, 30)

    def test_a_task_with_nowhere_left_to_go_is_flagged_unschedulable(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        due_today = _flexible(db_session, jobs, "Due by 17:00", deadline_offset_minutes=17 * 60)
        blackout = (BlackoutDate(start=date(2026, 3, 2), end=date(2026, 3, 2), label="Day off"),)

        repair = _save_and_run(db_session, jobs, {"blackout_dates": blackout})

        assert repair is not None and (repair.moved, repair.unschedulable) == (0, 1)
        stuck = _get(db_session, due_today.id)
        assert stuck.status == "pending" and stuck.scheduled_time is None
        assert [n.type for n in NotificationRepository(db_session).list_for_instance(due_today.id)] == ["unschedulable"]

    def test_a_strict_budget_moves_the_latest_deadline_off_an_over_budget_day(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        urgent = _flexible(db_session, jobs, "Urgent", deadline_offset_minutes=60 * 24 * 2)
        relaxed = _flexible(db_session, jobs, "Relaxed")
        budget = dict.fromkeys(DAY_NAMES, 60)

        repair = _save_and_run(db_session, jobs, {"budget_enforcement": "strict", "daily_time_budget_minutes": budget})

        assert repair is not None and repair.moved == 1
        assert _get(db_session, urgent.id).scheduled_time == ny(2026, 3, 2, 9, 0)
        assert _get(db_session, relaxed.id).scheduled_time == ny(2026, 3, 3, 9, 0)

    def test_a_finished_repair_does_nothing_when_run_again(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        _flexible(db_session, jobs, "Stranded")
        repair = _save_and_run(db_session, jobs, {"active_hours": _every_day("10:00", "17:00")})
        assert repair is not None
        jobs.scheduled.clear()

        handlers.run_schedule_repair(db_session, jobs, repair_id=repair.id)

        assert ScheduleRepairRepository(db_session).get(repair.id) == repair
        assert jobs.scheduled == []


class TestResumingAfterARestart:
    def test_an_unfinished_repair_is_run_again_at_startup(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        repair = ScheduleRepairRepository(db_session).create(ScheduleRepair(id="r1", total=3, done=1, requested_at=_NOW))
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert schedule_repair_job_key(repair.id) in jobs.scheduled_keys()

    def test_a_finished_one_is_left_alone(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        ScheduleRepairRepository(db_session).create(ScheduleRepair(id="r1", total=1, done=1, requested_at=_NOW, finished_at=_NOW))
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert schedule_repair_job_key("r1") not in jobs.scheduled_keys()


class TestATasksOwnOverride:
    def _daily_series(self, db: Session, jobs: RecordingJobScheduler) -> TaskInstance:
        return _flexible(db, jobs, "Stretch", recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))

    def test_narrowing_it_moves_an_occurrence_it_no_longer_covers(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        occurrence = self._daily_series(db_session, jobs)
        assert occurrence.scheduled_time == ny(2026, 3, 2, 9, 0)

        edit_template_this_and_future(
            db_session,
            jobs,
            occurrence.template_id,
            patch={"active_hours_override": {"monday": [ActiveHoursWindow(start="14:00", end="17:00")]}},
            from_instance_id=occurrence.id,
        )
        db_session.commit()

        assert _get(db_session, occurrence.id).scheduled_time == ny(2026, 3, 2, 14, 0)

    def test_a_new_override_that_still_covers_the_slot_leaves_it_alone(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        occurrence = self._daily_series(db_session, jobs)

        edit_template_this_and_future(
            db_session,
            jobs,
            occurrence.template_id,
            patch={"active_hours_override": {"monday": [ActiveHoursWindow(start="08:00", end="12:00")]}},
            from_instance_id=occurrence.id,
        )
        db_session.commit()

        assert _get(db_session, occurrence.id).scheduled_time == ny(2026, 3, 2, 9, 0)
