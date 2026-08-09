"""Startup reconciliation tests. See architecture-plan §4.2 - simulate a killed process by
writing inconsistent state directly via repositories (bypassing the normal service-layer
mutation paths, which is exactly what a mid-batch crash leaves behind), then assert
reconcile_on_startup restores consistency.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import ExternalCalendarConnectionRepository, TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import ExternalCalendarConnection, Recurrence, StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.jobs.interface import (
    calendar_poll_job_key,
    deadline_elapsed_job_key,
    dependency_at_risk_job_key,
    occurrence_boundary_job_key,
    overdue_job_key,
    reminder_job_key,
)
from app.jobs.reconciliation import reconcile_on_startup
from tests.fixtures.jobs import RecordingJobScheduler


def _persist_template(db: Session, **overrides: object) -> TaskTemplate:
    now = utcnow()
    defaults: dict[str, object] = {
        "id": generate_id(),
        "name": "Some task",
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 30,
        "deadline_offset_minutes": 60 * 24 * 5,
        "reminder_offsets_minutes": (15,),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskTemplateRepository(db).create(TaskTemplate(**defaults))


def _persist_instance(db: Session, *, template: TaskTemplate, status: str, **overrides: object) -> TaskInstance:
    now = utcnow()
    defaults: dict[str, object] = {
        "id": generate_id(),
        "template_id": template.id,
        "name": template.name,
        "type": template.type,
        "priority": 2,
        "estimated_duration_minutes": template.estimated_duration_minutes,
        "status": status,
        "status_history": (StatusHistoryEntry(status=status, at=now),),
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskInstanceRepository(db).create(TaskInstance(**defaults))


class TestRecreatesMissingJobsForLiveInstances:
    def test_a_scheduled_fixed_instance_gets_its_overdue_and_reminder_jobs_back(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        instance = _persist_instance(db_session, template=template, status="scheduled", scheduled_time=utcnow())
        db_session.commit()

        reconcile_on_startup(db_session, jobs)  # jobs starts empty - simulates the crashed process's job store

        assert overdue_job_key(instance.id) in jobs.scheduled_keys()
        assert reminder_job_key(instance.id, 15) in jobs.scheduled_keys()

    def test_a_pending_flexible_instance_gets_its_deadline_elapsed_job_back(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        instance = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=3))
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert deadline_elapsed_job_key(instance.id) in jobs.scheduled_keys()

    def test_a_blocked_instance_gets_its_dependency_at_risk_job_back(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        blocking = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=30))
        instance = _persist_instance(
            db_session,
            template=template,
            status="blocked",
            dependencies=(blocking.id,),
            deadline=utcnow() + timedelta(days=3),
        )
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert dependency_at_risk_job_key(instance.id) in jobs.scheduled_keys()


class TestCancelsOrphansForNonLiveInstances:
    def test_terminal_instances_have_all_their_jobs_cancelled(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        completed = _persist_instance(db_session, template=template, status="completed", completed_at=utcnow())
        dismissed = _persist_instance(db_session, template=template, status="dismissed")
        missed = _persist_instance(db_session, template=template, status="missed")
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert {completed.id, dismissed.id, missed.id} <= set(jobs.cancelled_instances)

    def test_a_pending_instance_never_carries_a_stray_dependency_at_risk_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        instance = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=3))
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert dependency_at_risk_job_key(instance.id) in jobs.cancelled


class TestOccurrenceBoundaryReconciliation:
    def test_a_non_archived_recurring_calendar_anchor_template_gets_its_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(
            db_session,
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"),
        )
        _persist_instance(db_session, template=template, status="scheduled", scheduled_time=utcnow())
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert occurrence_boundary_job_key(template.id) in jobs.scheduled_keys()

    def test_an_archived_templates_boundary_job_is_cancelled(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(
            db_session,
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"),
            archived=True,
        )
        _persist_instance(db_session, template=template, status="completed", completed_at=utcnow())
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert occurrence_boundary_job_key(template.id) in jobs.cancelled


class TestMissedUnblocks:
    def test_a_blocked_instance_whose_dependency_completed_while_the_process_was_down_gets_unblocked(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=30)
        dependency = _persist_instance(db_session, template=template, status="completed", completed_at=utcnow())
        dependent = _persist_instance(
            db_session,
            template=template,
            status="blocked",
            dependencies=(dependency.id,),
            deadline=utcnow() + timedelta(days=5),
        )
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        refreshed = TaskInstanceRepository(db_session).get(dependent.id)
        assert refreshed is not None
        assert refreshed.status != "blocked"

    def test_a_blocked_instance_with_an_incomplete_dependency_stays_blocked(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        dependency = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=5))
        dependent = _persist_instance(
            db_session, template=template, status="blocked", dependencies=(dependency.id,), deadline=utcnow() + timedelta(days=5)
        )
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        refreshed = TaskInstanceRepository(db_session).get(dependent.id)
        assert refreshed is not None
        assert refreshed.status == "blocked"


class TestCalendarPollJobs:
    """Stage 7 addition to reconciliation - every enabled connection keeps its poll
    interval job, every disabled one has it cancelled.
    """

    def test_enabled_connection_gets_its_poll_job_scheduled(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        connection = ExternalCalendarConnectionRepository(db_session).create(
            ExternalCalendarConnection(
                id=generate_id(), provider="google", oauth_credentials_ref="ref-1", refresh_interval_minutes=20, enabled=True
            )
        )
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert (calendar_poll_job_key(connection.id), 20) in jobs.intervals

    def test_disabled_connection_has_its_poll_job_cancelled(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        connection = ExternalCalendarConnectionRepository(db_session).create(
            ExternalCalendarConnection(
                id=generate_id(), provider="google", oauth_credentials_ref="ref-1", refresh_interval_minutes=20, enabled=False
            )
        )
        db_session.commit()

        reconcile_on_startup(db_session, jobs)

        assert calendar_poll_job_key(connection.id) in jobs.cancelled


class TestIdempotent:
    def test_running_reconciliation_twice_in_a_row_is_harmless(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        _persist_instance(db_session, template=template, status="scheduled", scheduled_time=utcnow())
        db_session.commit()

        reconcile_on_startup(db_session, jobs)
        reconcile_on_startup(db_session, jobs)  # must not raise, must not duplicate meaningfully
