"""Repository CRUD tests for `Notification`. See design doc §3.4, §3.9."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import NotificationRepository, TaskInstanceRepository, TaskTemplateRepository
from tests.fixtures.db_entities import make_notification, make_task_instance, make_task_template


def _persisted_instance(db_session: Session) -> str:
    template = TaskTemplateRepository(db_session).create(make_task_template())
    instance = TaskInstanceRepository(db_session).create(make_task_instance(template_id=template.id))
    db_session.commit()
    return instance.id


def test_create_and_get_round_trip(db_session: Session) -> None:
    instance_id = _persisted_instance(db_session)
    repo = NotificationRepository(db_session)
    notification = make_notification(related_instance_id=instance_id, type="unschedulable")
    created = repo.create(notification)
    db_session.commit()
    db_session.expire_all()

    fetched = repo.get(notification.id)
    assert fetched == created


def test_list_for_instance_returns_every_state(db_session: Session) -> None:
    instance_id = _persisted_instance(db_session)
    repo = NotificationRepository(db_session)
    active = repo.create(make_notification(related_instance_id=instance_id, type="overdue"))
    resolved = repo.create(make_notification(related_instance_id=instance_id, type="dependency_at_risk", resolved_at=utcnow()))
    db_session.commit()

    results = {n.id for n in repo.list_for_instance(instance_id)}
    assert results == {active.id, resolved.id}


def test_update_sets_resolved_at(db_session: Session) -> None:
    instance_id = _persisted_instance(db_session)
    repo = NotificationRepository(db_session)
    created = repo.create(make_notification(related_instance_id=instance_id, type="overdue"))
    db_session.commit()

    resolved_at = utcnow()
    updated = repo.update(created.model_copy(update={"resolved_at": resolved_at}))
    db_session.commit()

    assert updated.resolved_at == resolved_at
