"""Job-wiring tests: does each Stage 6 mutation path schedule/cancel the right job(s)?
See architecture-plan §4.1's required test category - distinct from algorithm/behavior
correctness (tests/integration/), this only asserts job-store state.
"""

from __future__ import annotations

from datetime import UTC, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.db.repositories import TaskInstanceRepository
from app.db.schemas import Recurrence, UserSettings
from app.jobs.interface import (
    deadline_elapsed_job_key,
    dependency_at_risk_job_key,
    occurrence_boundary_job_key,
    overdue_job_key,
    reminder_job_key,
)
from app.task_instances.service import complete, delete_instance, dismiss, start_progress
from app.task_templates import service as task_templates_service
from app.task_templates.service import (
    TaskTemplateDraft,
    TemplateValidationError,
    archive_template,
    create_template,
    edit_template_this_and_future,
)
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import ny


def _flexible_draft(**overrides: object) -> TaskTemplateDraft:
    defaults: dict[str, object] = {
        "name": "Water plants",
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 30,
        "deadline_offset_minutes": 60 * 24 * 5,
    }
    defaults.update(overrides)
    return TaskTemplateDraft(**defaults)  # type: ignore[arg-type]


def _fixed_draft(**overrides: object) -> TaskTemplateDraft:
    defaults: dict[str, object] = {
        "name": "Team sync",
        "type": "fixed",
        "fixed_time_of_day": "09:00",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 60,
    }
    defaults.update(overrides)
    return TaskTemplateDraft(**defaults)  # type: ignore[arg-type]


class TestCreateWithDependencies:
    def test_a_blocked_flexible_instance_gets_a_dependency_at_risk_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        db_session.commit()
        jobs.scheduled.clear()

        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()

        assert dependency_at_risk_job_key(inspection.instance.id) in jobs.scheduled_keys()


class TestCreateRecurringCalendarAnchor:
    def test_a_recurring_calendar_anchor_template_schedules_an_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session,
            jobs,
            _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar")),
        )
        db_session.commit()

        assert occurrence_boundary_job_key(created.template.id) in jobs.scheduled_keys()

    def test_a_one_time_template_never_schedules_an_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        assert occurrence_boundary_job_key(created.template.id) not in jobs.scheduled_keys()

    def test_a_completion_anchor_template_never_schedules_an_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session,
            jobs,
            _flexible_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="completion")),
        )
        db_session.commit()

        assert occurrence_boundary_job_key(created.template.id) not in jobs.scheduled_keys()


class TestCompleteOnCompletionAnchor:
    def test_completing_the_live_instance_wires_the_generated_successors_jobs(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """Completion-anchor is flexible-only (§3.2), so the generated successor goes
        through place_or_defer rather than the fixed overdue/reminder path - assert its
        deadline-elapsed safety-net job gets wired instead (or, if immediately placed,
        its own overdue/reminder jobs - either way, *some* job for the new instance).
        """
        created = create_template(
            db_session,
            jobs,
            _flexible_draft(
                name="Water plants",
                recurrence=Recurrence(pattern="weekly", interval=1, anchor="completion"),
                reminder_offsets_minutes=(15,),
            ),
        )
        db_session.commit()
        jobs.scheduled.clear()

        complete(db_session, jobs, created.instance.id)
        db_session.commit()

        successors = [
            i for i in TaskInstanceRepository(db_session).list_by_template(created.template.id) if i.id != created.instance.id
        ]
        assert len(successors) == 1
        assert any(successors[0].id in key for key in jobs.scheduled_keys())

    def test_completing_a_non_completion_anchor_instance_generates_nothing(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())  # calendar anchor, default
        db_session.commit()

        complete(db_session, jobs, created.instance.id)
        db_session.commit()

        successors = [
            i for i in TaskInstanceRepository(db_session).list_by_template(created.template.id) if i.id != created.instance.id
        ]
        assert successors == []


class TestArchiveRecurringCalendarAnchor:
    def test_archiving_cancels_the_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session,
            jobs,
            _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar")),
        )
        db_session.commit()

        archive_template(db_session, jobs, created.template.id)
        db_session.commit()

        assert occurrence_boundary_job_key(created.template.id) in jobs.cancelled

    def test_archiving_a_one_time_template_does_not_touch_the_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        jobs.cancelled.clear()

        archive_template(db_session, jobs, created.template.id)
        db_session.commit()

        assert occurrence_boundary_job_key(created.template.id) not in jobs.cancelled


class TestStartProgress:
    def test_starting_touches_no_jobs(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        """§4: `scheduled` -> `in_progress` has no job side effects - the reminder and
        overdue-check handlers already treat `in_progress` identically to `scheduled`
        (`app/jobs/handlers.py`). `start_progress` doesn't even take a `jobs` param, so
        this just confirms the fixture's job-store state is untouched by the call.
        """
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        scheduled_before = set(jobs.scheduled_keys())
        cancelled_before = set(jobs.cancelled)

        start_progress(db_session, created.instance.id)
        db_session.commit()

        assert set(jobs.scheduled_keys()) == scheduled_before
        assert set(jobs.cancelled) == cancelled_before


class TestDismiss:
    def test_dismissing_cancels_every_job_for_the_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        dismiss(db_session, jobs, created.instance.id)
        db_session.commit()

        assert created.instance.id in jobs.cancelled_instances


class TestDeleteThisAndFuture:
    def test_this_and_future_scope_cancels_the_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()

        delete_instance(db_session, jobs, created.instance.id, scope="this_and_future")
        db_session.commit()

        assert occurrence_boundary_job_key(created.template.id) in jobs.cancelled


#: Mon 2026-03-02 08:00 New York - see tests/integration/task_templates/test_service.py.
_NOW = ny(2026, 3, 2, 8, 0)


@pytest.fixture
def pinned_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_templates_service, "utcnow", lambda: _NOW)


@pytest.mark.usefixtures("pinned_now")
class TestEditThisAndFuture:
    def test_retiming_re_points_overdue_and_reminder_jobs_at_the_new_time(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        sync = create_template(db_session, jobs, _fixed_draft(reminder_offsets_minutes=(15,)))
        db_session.commit()
        jobs.scheduled.clear()

        edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"fixed_time_of_day": "11:00"})
        db_session.commit()

        assert (overdue_job_key(sync.instance.id), ny(2026, 3, 2, 11, 0)) in jobs.scheduled
        assert (reminder_job_key(sync.instance.id, 15), ny(2026, 3, 2, 10, 45)) in jobs.scheduled

    def test_a_rejected_retime_touches_no_jobs(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        create_template(db_session, jobs, _fixed_draft(name="Standup", fixed_time_of_day="09:00"))
        sync = create_template(db_session, jobs, _fixed_draft(fixed_time_of_day="11:00"))
        db_session.commit()
        jobs.scheduled.clear()

        with pytest.raises(TemplateValidationError):
            edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"fixed_time_of_day": "09:30"})

        assert jobs.scheduled == []
        assert jobs.cancelled == []

    def test_dropped_reminder_offsets_are_cancelled(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        sync = create_template(db_session, jobs, _fixed_draft(reminder_offsets_minutes=(60, 15)))
        db_session.commit()
        jobs.scheduled.clear()

        edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"reminder_offsets_minutes": (15, 5)})
        db_session.commit()

        assert reminder_job_key(sync.instance.id, 60) in jobs.cancelled
        assert {reminder_job_key(sync.instance.id, 15), reminder_job_key(sync.instance.id, 5)} <= jobs.scheduled_keys()

    def test_a_time_change_re_points_the_occurrence_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        daily = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()
        jobs.scheduled.clear()

        edit_template_this_and_future(db_session, jobs, daily.template.id, patch={"fixed_time_of_day": "10:15"})
        db_session.commit()

        boundary = [run_at for key, run_at in jobs.scheduled if key == occurrence_boundary_job_key(daily.template.id)]
        assert len(boundary) == 1
        assert boundary[0].astimezone(ZoneInfo("America/New_York")).time() == time(10, 15)

    def test_evicting_a_scheduled_instance_cancels_its_old_slots_jobs(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        chore = create_template(db_session, jobs, _flexible_draft(reminder_offsets_minutes=(10,)))
        db_session.commit()
        assert chore.instance.status == "scheduled"

        # Deadline 08:30 - no slot left, so the instance stays pending after eviction.
        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"deadline_offset_minutes": 30})
        db_session.commit()

        assert overdue_job_key(chore.instance.id) in jobs.cancelled
        assert reminder_job_key(chore.instance.id, 10) in jobs.cancelled
        assert (deadline_elapsed_job_key(chore.instance.id), ny(2026, 3, 2, 8, 30)) in jobs.scheduled

    def test_a_blocked_instances_dependency_at_risk_job_follows_its_new_deadline(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()
        jobs.scheduled.clear()

        edit_template_this_and_future(db_session, jobs, inspection.template.id, patch={"deadline_offset_minutes": 60 * 24 * 10})
        db_session.commit()

        new_deadline = _NOW.astimezone(UTC) + timedelta(days=10)
        assert (dependency_at_risk_job_key(inspection.instance.id), new_deadline - timedelta(days=3)) in jobs.scheduled

    def test_the_boundary_job_is_re_pointed_even_with_no_live_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        daily = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()
        dismiss(db_session, jobs, daily.instance.id)
        db_session.commit()
        jobs.scheduled.clear()

        edit_template_this_and_future(db_session, jobs, daily.template.id, patch={"fixed_time_of_day": "10:15"})
        db_session.commit()

        assert occurrence_boundary_job_key(daily.template.id) in jobs.scheduled_keys()

    def test_switching_to_one_time_cancels_the_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        daily = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()

        edit_template_this_and_future(
            db_session, jobs, daily.template.id, patch={"recurrence": Recurrence(pattern="one_time", anchor="calendar")}
        )
        db_session.commit()

        assert occurrence_boundary_job_key(daily.template.id) in jobs.cancelled
