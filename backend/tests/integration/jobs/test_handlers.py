"""Integration tests for app.jobs.handlers - what each job actually does when it fires.
See design doc §6.3, §6.6, §6.7; architecture-plan §4's job breakdown table.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import (
    NotificationRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
)
from app.db.schemas import Recurrence, StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.jobs import handlers
from tests.fixtures.jobs import RecordingJobScheduler


def _persist_template(db: Session, **overrides: object) -> TaskTemplate:
    now = utcnow()
    defaults: dict[str, object] = {
        "id": generate_id(),
        "name": "Water the plants",
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 30,
        "deadline_offset_minutes": 60 * 24 * 5,
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


class TestRunReminder:
    def test_creates_a_reminder_notification_for_a_scheduled_instance(self, db_session: Session, settings: UserSettings) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        instance = _persist_instance(db_session, template=template, status="scheduled", scheduled_time=utcnow())
        db_session.commit()

        handlers.run_reminder(db_session, instance_id=instance.id, offset_minutes=15)
        db_session.commit()

        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        assert any(n.type == "reminder" for n in notifications)

    def test_no_ops_for_an_already_completed_instance(self, db_session: Session, settings: UserSettings) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        instance = _persist_instance(db_session, template=template, status="completed", completed_at=utcnow())
        db_session.commit()

        handlers.run_reminder(db_session, instance_id=instance.id, offset_minutes=15)
        db_session.commit()

        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()


class TestRunOverdueCheck:
    def test_fixed_instance_gets_an_overdue_notification_and_keeps_its_status(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        instance = _persist_instance(
            db_session, template=template, status="scheduled", scheduled_time=utcnow() - timedelta(hours=1)
        )
        db_session.commit()

        handlers.run_overdue_check(db_session, jobs, instance_id=instance.id)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status == "scheduled"
        assert any(n.type == "overdue" for n in NotificationRepository(db_session).list_for_instance(instance.id))

    def test_flexible_instance_reverts_to_pending_and_re_enters_placement(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=30)
        instance = _persist_instance(
            db_session,
            template=template,
            status="scheduled",
            scheduled_time=utcnow() - timedelta(hours=1),
            deadline=utcnow() + timedelta(days=5),
        )
        db_session.commit()

        handlers.run_overdue_check(db_session, jobs, instance_id=instance.id)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status in ("pending", "scheduled")  # re-placed immediately if a slot exists
        assert any(n.type == "overdue" for n in NotificationRepository(db_session).list_for_instance(instance.id))

    def test_no_ops_if_already_completed_by_the_time_the_job_fires(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, type="fixed", fixed_time_of_day="09:00")
        instance = _persist_instance(db_session, template=template, status="completed", completed_at=utcnow())
        db_session.commit()

        handlers.run_overdue_check(db_session, jobs, instance_id=instance.id)
        db_session.commit()

        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()


class TestDeadlineElapsed:
    def test_one_off_check_transitions_a_pending_instance_to_missed(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        instance = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() - timedelta(minutes=1))
        db_session.commit()

        handlers.run_deadline_elapsed_check(db_session, jobs, instance_id=instance.id)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status == "missed"

    def test_one_off_check_no_ops_if_no_longer_pending(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        instance = _persist_instance(
            db_session, template=template, status="scheduled", scheduled_time=utcnow(), deadline=utcnow() - timedelta(minutes=1)
        )
        db_session.commit()

        handlers.run_deadline_elapsed_check(db_session, jobs, instance_id=instance.id)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status == "scheduled"

    def test_sweep_catches_a_blocked_instance_the_one_off_never_covers(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§6.7 check #1 - a blocked instance is never handed to place_or_defer until it
        unblocks, so the periodic sweep is its only safety net.
        """
        template = _persist_template(db_session)
        instance = _persist_instance(
            db_session,
            template=template,
            status="blocked",
            dependencies=("some-other-instance-id",),
            deadline=utcnow() - timedelta(minutes=1),
        )
        db_session.commit()

        handlers.run_deadline_elapsed_sweep(db_session, jobs)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status == "missed"

    def test_sweep_ignores_instances_whose_deadline_has_not_elapsed(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        instance = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=5))
        db_session.commit()

        handlers.run_deadline_elapsed_sweep(db_session, jobs)
        db_session.commit()

        refreshed = TaskInstanceRepository(db_session).get(instance.id)
        assert refreshed is not None
        assert refreshed.status == "pending"


class TestRunDependencyAtRiskCheck:
    def test_creates_a_notification_when_no_slot_remains_before_the_deadline(
        self, db_session: Session, settings: UserSettings
    ) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=60)
        blocking = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=30))
        instance = _persist_instance(
            db_session,
            template=template,
            status="blocked",
            dependencies=(blocking.id,),
            deadline=utcnow() + timedelta(minutes=5),  # too tight to fit 60 minutes
        )
        db_session.commit()

        handlers.run_dependency_at_risk_check(db_session, instance_id=instance.id)
        db_session.commit()

        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        assert any(n.type == "dependency_at_risk" for n in notifications)

    def test_no_ops_once_all_dependencies_are_already_completed(self, db_session: Session, settings: UserSettings) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=60)
        completed_dep = _persist_instance(
            db_session, template=template, status="completed", completed_at=utcnow(), deadline=utcnow() + timedelta(days=1)
        )
        instance = _persist_instance(
            db_session,
            template=template,
            status="blocked",
            dependencies=(completed_dep.id,),
            deadline=utcnow() + timedelta(minutes=5),
        )
        db_session.commit()

        handlers.run_dependency_at_risk_check(db_session, instance_id=instance.id)
        db_session.commit()

        assert NotificationRepository(db_session).list_for_instance(instance.id) == ()

    def test_does_not_duplicate_an_already_active_notification(self, db_session: Session, settings: UserSettings) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=60)
        blocking = _persist_instance(db_session, template=template, status="pending", deadline=utcnow() + timedelta(days=30))
        instance = _persist_instance(
            db_session,
            template=template,
            status="blocked",
            dependencies=(blocking.id,),
            deadline=utcnow() + timedelta(minutes=5),
        )
        db_session.commit()

        handlers.run_dependency_at_risk_check(db_session, instance_id=instance.id)
        db_session.commit()
        handlers.run_dependency_at_risk_check(db_session, instance_id=instance.id)
        db_session.commit()

        notifications = [
            n for n in NotificationRepository(db_session).list_for_instance(instance.id) if n.type == "dependency_at_risk"
        ]
        assert len(notifications) == 1


class TestRunOccurrenceBoundary:
    def test_generates_the_next_instance_and_reschedules_the_next_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(
            db_session,
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"),
        )
        first = _persist_instance(db_session, template=template, status="scheduled", scheduled_time=utcnow())
        db_session.commit()

        handlers.run_occurrence_boundary(db_session, jobs, template_id=template.id)
        db_session.commit()

        instances = TaskInstanceRepository(db_session).list_by_template(template.id)
        assert len(instances) == 2
        assert first.id in {i.id for i in instances}
        assert any(key.startswith("occurrence_boundary:") for key in jobs.scheduled_keys())

    def test_no_ops_for_an_archived_template(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(
            db_session,
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"),
            archived=True,
        )
        _persist_instance(db_session, template=template, status="scheduled", scheduled_time=utcnow())
        db_session.commit()

        handlers.run_occurrence_boundary(db_session, jobs, template_id=template.id)
        db_session.commit()

        instances = TaskInstanceRepository(db_session).list_by_template(template.id)
        assert len(instances) == 1
