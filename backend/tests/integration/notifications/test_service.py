"""Integration tests for app.notifications.service. See design doc §3.4, §3.9, §5.

Creation/self-resolution triggers themselves are covered where they're owned
(tests/integration/scheduling/test_orchestration.py for unschedulable/budget_exceeded/
deadline_missed; tests/integration/task_instances/test_service.py's extend_deadline and
complete tests for deadline_missed resolution). This file covers the shared read/dismiss
surface plus a table-driven audit of design doc §5's full notification-type list, so a
type silently going unhandled is a visible test gap, not a silent one.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import NotificationRepository, TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import (
    Notification,
    NotificationType,
    Recurrence,
    StatusHistoryEntry,
    TaskInstance,
    TaskTemplate,
    UserSettings,
)
from app.notifications.service import NotificationNotFoundError, dismiss, list_active


def _persist_instance(db: Session) -> TaskInstance:
    """A real, FK-satisfying TaskInstance - `notifications.related_instance_id` has a
    foreign key to `task_instances` (design doc §3.4), so tests can't use a bare string id.
    """
    now = utcnow()
    template = TaskTemplateRepository(db).create(
        TaskTemplate(
            id=generate_id(),
            name="Some task",
            type="flexible",
            recurrence=Recurrence(pattern="one_time", anchor="calendar"),
            priority="medium",
            estimated_duration_minutes=30,
            deadline_offset_minutes=60 * 24,
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
            type=template.type,
            priority=2,
            estimated_duration_minutes=template.estimated_duration_minutes,
            status="pending",
            status_history=(StatusHistoryEntry(status="pending", at=now),),
            generated_at=now,
            created_at=now,
            updated_at=now,
            version=1,
        )
    )


#: design doc §5's full type list, and which Stage 5 owns creating (see module docstrings
#: in app.scheduling.orchestration and app.task_instances.service for the trigger points).
#: Everything else is job/periodic-scan driven and explicitly deferred to Stage 6/7.
_STAGE_5_OWNED: dict[NotificationType, bool] = {
    "unschedulable": True,
    "budget_exceeded": True,
    "deadline_missed": True,
    "creation_conflict": False,  # synchronous rejection only (Example A) - never persisted
    "reminder": False,  # job-driven, Stage 6
    "sync_conflict": False,  # calendar sync, Stage 7
    "dependency_at_risk": False,  # periodic scan, Stage 6
    "overdue": False,  # job-driven, Stage 6
}


def test_every_design_doc_notification_type_is_accounted_for() -> None:
    expected_types = set(NotificationType.__args__)  # type: ignore[attr-defined]
    assert set(_STAGE_5_OWNED) == expected_types, "a new/renamed notification type needs an explicit ownership decision here"


class TestListActive:
    def test_lists_only_undismissed_and_unresolved(self, db_session: Session, settings: UserSettings) -> None:
        repo = NotificationRepository(db_session)
        now = utcnow()
        instance_1, instance_2, instance_3 = (_persist_instance(db_session) for _ in range(3))
        active = repo.create(
            Notification(id=generate_id(), type="unschedulable", related_instance_id=instance_1.id, message="a", created_at=now)
        )
        repo.create(
            Notification(
                id=generate_id(),
                type="unschedulable",
                related_instance_id=instance_2.id,
                message="b",
                created_at=now,
                resolved_at=now,
            )
        )
        repo.create(
            Notification(
                id=generate_id(),
                type="unschedulable",
                related_instance_id=instance_3.id,
                message="c",
                created_at=now,
                dismissed_at=now,
            )
        )
        db_session.commit()

        result = list_active(db_session)

        assert [n.id for n in result] == [active.id]


class TestDismiss:
    def test_sets_dismissed_at(self, db_session: Session, settings: UserSettings) -> None:
        repo = NotificationRepository(db_session)
        now = utcnow()
        instance = _persist_instance(db_session)
        created = repo.create(
            Notification(id=generate_id(), type="budget_exceeded", related_instance_id=instance.id, message="x", created_at=now)
        )
        db_session.commit()

        dismissed = dismiss(db_session, created.id)
        db_session.commit()

        assert dismissed.dismissed_at is not None

    def test_dismissing_an_already_resolved_notification_still_succeeds(
        self, db_session: Session, settings: UserSettings
    ) -> None:
        """§3.9: an auto-resolved notification is still explicitly dismissible - dismiss
        never rejects on "already resolved", that's purely a frontend display concern.
        """
        repo = NotificationRepository(db_session)
        now = utcnow()
        instance = _persist_instance(db_session)
        created = repo.create(
            Notification(
                id=generate_id(),
                type="unschedulable",
                related_instance_id=instance.id,
                message="x",
                created_at=now,
                resolved_at=now,
            )
        )
        db_session.commit()

        dismissed = dismiss(db_session, created.id)
        db_session.commit()

        assert dismissed.dismissed_at is not None
        assert dismissed.resolved_at is not None

    def test_dismissing_an_unknown_id_raises(self, db_session: Session, settings: UserSettings) -> None:
        with pytest.raises(NotificationNotFoundError):
            dismiss(db_session, "does-not-exist")
