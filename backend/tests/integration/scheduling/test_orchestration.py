"""Integration tests for app.scheduling.orchestration.place_or_defer - the §6.7 missed-gate,
§6.2 placement, and unschedulable/budget_exceeded/deadline_missed notification lifecycle
(design doc §5, §3.9).
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import NotificationRepository, TaskInstanceRepository, TaskTemplateRepository, UserSettingsRepository
from app.db.schemas import Recurrence, StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.scheduling.orchestration import BUDGET_EXCEEDED, DEADLINE_MISSED, UNSCHEDULABLE, place_or_defer
from tests.fixtures.jobs import RecordingJobScheduler


def _persist_template(db: Session, **overrides: object) -> TaskTemplate:
    now = utcnow()
    defaults: dict[str, object] = {
        "id": generate_id(),
        "name": "Deep clean garage",
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 60,
        "deadline_offset_minutes": 60 * 24 * 5,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskTemplateRepository(db).create(TaskTemplate(**defaults))


def _persist_pending_instance(db: Session, *, template: TaskTemplate, **overrides: object) -> TaskInstance:
    now = utcnow()
    defaults: dict[str, object] = {
        "id": generate_id(),
        "template_id": template.id,
        "name": template.name,
        "type": template.type,
        "priority": 2,
        "estimated_duration_minutes": template.estimated_duration_minutes,
        "status": "pending",
        "status_history": (StatusHistoryEntry(status="pending", at=now),),
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskInstanceRepository(db).create(TaskInstance(**defaults))


class TestMissedGate:
    def test_an_already_elapsed_deadline_transitions_to_missed_and_notifies(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session)
        now = utcnow()
        instance = _persist_pending_instance(db_session, template=template, deadline=now - timedelta(minutes=1))
        db_session.commit()

        result = place_or_defer(db_session, jobs, instance=instance, template=template, settings=settings, now=now)
        db_session.commit()

        assert result.status == "missed"
        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        assert any(n.type == DEADLINE_MISSED and n.resolved_at is None for n in notifications)
        assert instance.id in jobs.cancelled_instances


class TestUnschedulable:
    def test_a_deadline_too_tight_to_fit_the_duration_stays_pending_and_notifies(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=60)
        now = utcnow()
        instance = _persist_pending_instance(
            db_session, template=template, estimated_duration_minutes=60, deadline=now + timedelta(minutes=5)
        )
        db_session.commit()

        result = place_or_defer(db_session, jobs, instance=instance, template=template, settings=settings, now=now)
        db_session.commit()

        assert result.status == "pending"
        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        assert any(n.type == UNSCHEDULABLE and n.resolved_at is None for n in notifications)
        assert any(key.startswith("deadline_elapsed:") for key in jobs.scheduled_keys())

    def test_does_not_duplicate_an_already_active_unschedulable_notification(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=60)
        now = utcnow()
        instance = _persist_pending_instance(
            db_session, template=template, estimated_duration_minutes=60, deadline=now + timedelta(minutes=5)
        )
        db_session.commit()

        place_or_defer(db_session, jobs, instance=instance, template=template, settings=settings, now=now)
        db_session.commit()
        place_or_defer(db_session, jobs, instance=instance, template=template, settings=settings, now=now + timedelta(seconds=1))
        db_session.commit()

        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        active_unschedulable = [n for n in notifications if n.type == UNSCHEDULABLE and n.resolved_at is None]
        assert len(active_unschedulable) == 1

    def test_a_successful_placement_self_resolves_a_prior_unschedulable_notification(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        template = _persist_template(db_session, estimated_duration_minutes=60)
        now = utcnow()
        instance = _persist_pending_instance(
            db_session, template=template, estimated_duration_minutes=60, deadline=now + timedelta(minutes=5)
        )
        db_session.commit()
        place_or_defer(db_session, jobs, instance=instance, template=template, settings=settings, now=now)
        db_session.commit()

        # Now editable-in-place with a workable deadline: re-run against a fresh deadline far enough out.
        roomier = TaskInstanceRepository(db_session).update(instance.model_copy(update={"deadline": now + timedelta(days=5)}))
        db_session.commit()
        result = place_or_defer(db_session, jobs, instance=roomier, template=template, settings=settings, now=now)
        db_session.commit()

        assert result.status == "scheduled"
        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        unschedulable = [n for n in notifications if n.type == UNSCHEDULABLE]
        assert len(unschedulable) == 1
        assert unschedulable[0].resolved_at is not None


class TestBudgetExceeded:
    def test_a_soft_override_placement_creates_an_informational_notification(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        tight_budget = UserSettingsRepository(db_session).update(
            settings.model_copy(update={"daily_time_budget_minutes": dict.fromkeys(settings.daily_time_budget_minutes, 30)})
        )
        db_session.commit()
        template = _persist_template(db_session, estimated_duration_minutes=60)
        now = utcnow()
        instance = _persist_pending_instance(
            db_session, template=template, estimated_duration_minutes=60, deadline=now + timedelta(days=3)
        )
        db_session.commit()

        result = place_or_defer(db_session, jobs, instance=instance, template=template, settings=tight_budget, now=now)
        db_session.commit()

        assert result.status == "scheduled"
        notifications = NotificationRepository(db_session).list_for_instance(instance.id)
        assert any(n.type == BUDGET_EXCEEDED for n in notifications)
