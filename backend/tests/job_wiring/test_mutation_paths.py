"""Job-wiring tests: does each Stage 6 mutation path schedule/cancel the right job(s)?
See architecture-plan §4.1's required test category - distinct from algorithm/behavior
correctness (tests/integration/), this only asserts job-store state.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import TaskInstanceRepository
from app.db.schemas import Recurrence, UserSettings
from app.jobs.interface import dependency_at_risk_job_key, occurrence_boundary_job_key
from app.task_instances.service import complete, delete_instance, dismiss, start_progress
from app.task_templates.service import TaskTemplateDraft, archive_template, create_template
from tests.fixtures.jobs import RecordingJobScheduler


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
