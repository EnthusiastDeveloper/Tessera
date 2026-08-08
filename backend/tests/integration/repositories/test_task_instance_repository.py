"""Repository CRUD tests for `TaskInstance`, including the dependency join table. See design doc §3.3, §3.8."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import StatusHistoryEntry
from tests.fixtures.db_entities import make_task_instance, make_task_template


def _persisted_template(db_session: Session) -> str:
    template = TaskTemplateRepository(db_session).create(make_task_template())
    db_session.commit()
    return template.id


def test_create_and_get_round_trip(db_session: Session) -> None:
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    instance = make_task_instance(
        template_id=template_id,
        status_history=(StatusHistoryEntry(status="pending", at=utcnow()),),
    )
    created = repo.create(instance)
    db_session.commit()
    db_session.expire_all()

    fetched = repo.get(instance.id)
    assert fetched == created


def test_get_missing_returns_none(db_session: Session) -> None:
    assert TaskInstanceRepository(db_session).get("does-not-exist") is None


def test_list_pending_flexible_filters_by_status_and_type(db_session: Session) -> None:
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    pending_flexible = repo.create(make_task_instance(template_id=template_id, status="pending", type="flexible"))
    repo.create(make_task_instance(template_id=template_id, status="scheduled", type="flexible"))
    repo.create(make_task_instance(template_id=template_id, status="pending", type="fixed"))
    db_session.commit()

    results = repo.list_pending_flexible()
    assert {instance.id for instance in results} == {pending_flexible.id}


def test_dependencies_persist_and_navigate_both_directions(db_session: Session) -> None:
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    dependency = repo.create(make_task_instance(template_id=template_id, name="Buy groceries", status="pending"))
    dependent = repo.create(
        make_task_instance(template_id=template_id, name="Cook dinner", status="blocked", dependencies=(dependency.id,))
    )
    db_session.commit()
    db_session.expire_all()

    fetched_dependent = repo.get(dependent.id)
    assert fetched_dependent is not None
    assert fetched_dependent.dependencies == (dependency.id,)

    dependents_of_dependency = repo.list_dependents(dependency.id)
    assert [instance.id for instance in dependents_of_dependency] == [dependent.id]


def test_deleting_a_dependency_unlinks_without_cascading(db_session: Session) -> None:
    """§3.8: deleting a depended-upon instance removes the link only - the dependent instance survives."""
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    dependency = repo.create(make_task_instance(template_id=template_id, status="pending"))
    dependent = repo.create(make_task_instance(template_id=template_id, status="blocked", dependencies=(dependency.id,)))
    db_session.commit()

    repo.delete(dependency.id)
    db_session.commit()
    db_session.expire_all()

    survivor = repo.get(dependent.id)
    assert survivor is not None
    assert survivor.dependencies == ()
    assert repo.get(dependency.id) is None


def test_update_persists_changes_and_increments_version(db_session: Session) -> None:
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    created = repo.create(make_task_instance(template_id=template_id, status="pending"))
    db_session.commit()

    updated = repo.update(created.model_copy(update={"status": "scheduled"}))
    db_session.commit()

    assert updated.status == "scheduled"
    assert updated.version == created.version + 1


def test_update_ignores_caller_supplied_version(db_session: Session) -> None:
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    created = repo.create(make_task_instance(template_id=template_id, status="pending"))
    db_session.commit()

    updated = repo.update(created.model_copy(update={"status": "scheduled", "version": 999}))
    db_session.commit()

    assert updated.version == created.version + 1


def test_update_can_change_dependencies(db_session: Session) -> None:
    template_id = _persisted_template(db_session)
    repo = TaskInstanceRepository(db_session)
    dependency_a = repo.create(make_task_instance(template_id=template_id, status="pending"))
    dependency_b = repo.create(make_task_instance(template_id=template_id, status="pending"))
    dependent = repo.create(make_task_instance(template_id=template_id, status="blocked", dependencies=(dependency_a.id,)))
    db_session.commit()

    updated = repo.update(dependent.model_copy(update={"dependencies": (dependency_b.id,)}))
    db_session.commit()

    assert updated.dependencies == (dependency_b.id,)
