"""Repository CRUD tests for `TaskInstance`, including the dependency join table. See design doc §3.3, §3.8."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.db.base import Base, utcnow
from app.db.models.task_instance import TaskInstanceORM
from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import StatusHistoryEntry
from app.db.session import build_engine, sqlite_url
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


def test_update_raises_stale_data_error_on_a_genuine_concurrent_write(tmp_path: Path) -> None:
    """architecture-plan §5's `version_id_col` contract: a write against a row that
    already moved underneath the caller must be rejected, not silently overwritten.

    Needs two truly independent `Session`s on a *file-backed* DB - the suite's usual
    `db_session` fixture is a single session against `sqlite:///:memory:`, which can't
    reproduce this: a single session always sees its own writes immediately, so there is
    never a stale identity-mapped object to provoke the mismatch. See
    `tests/integration/test_session.py` for the same file-backed-engine pattern.

    This is the mechanism `app.api.errors`'s `StaleDataError` handler exists to catch
    (see `tests/integration/api/test_error_envelope.py`'s `TestStaleDataErrorBackstop`
    for the API-layer half of this contract) - this test proves the exception is
    genuinely raised in the first place, not just that the handler would format it.

    One more thing this needs, easy to miss: SQLAlchemy's identity map holds only *weak*
    references to clean (already-flushed, no pending changes) ORM objects. Every
    repository method here returns a converted `_to_domain()` snapshot rather than the
    ORM object itself, so a caller who only keeps that snapshot leaves nothing pinning
    the ORM object in memory - it gets garbage-collected, and the *next* `.get()` inside
    `update()` silently re-fetches a fresh (non-stale) row from the DB instead of
    reusing the cached one, defeating this whole test. Holding `session_a.get(...)`'s
    return value directly (the actual mapped object, not a repository-converted copy) is
    what keeps it alive long enough to go stale.
    """
    db_path = tmp_path / "concurrency.db"
    engine = build_engine(sqlite_url(str(db_path)))
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session_a, session_b = session_factory(), session_factory()
    try:
        template_id = _persisted_template(session_a)
        created = TaskInstanceRepository(session_a).create(make_task_instance(template_id=template_id, status="pending"))
        session_a.commit()

        # A strong reference to the live ORM object, exactly as a service method's local
        # variable would hold one for the duration of a request - this is the copy that
        # will go stale. `session_a.get(...)` directly (not `TaskInstanceRepository.get()`,
        # which would hand back a disposable domain snapshot instead) is what session_a's
        # own identity map will keep finding for the rest of this test.
        pinned_orm_object = session_a.get(TaskInstanceORM, created.id)
        assert pinned_orm_object is not None

        # A concurrent writer (session_b - standing in for a background job or a second
        # request) changes the same row and commits first.
        TaskInstanceRepository(session_b).update(created.model_copy(update={"status": "scheduled"}))
        session_b.commit()

        # session_a's cached object is now stale relative to the DB; its own write must
        # be rejected rather than blindly overwriting session_b's change.
        with pytest.raises(StaleDataError):
            TaskInstanceRepository(session_a).update(created.model_copy(update={"priority": 4}))
        del pinned_orm_object  # silence "assigned but never read" - its only job was staying alive
    finally:
        session_a.close()
        session_b.close()
        engine.dispose()


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


class TestListFiltered:
    """`GET /task-instances?status=&priority=&type=` (architecture-plan §3)."""

    def test_no_filters_returns_everything(self, db_session: Session) -> None:
        template_id = _persisted_template(db_session)
        repo = TaskInstanceRepository(db_session)
        repo.create(make_task_instance(template_id=template_id, status="pending"))
        repo.create(make_task_instance(template_id=template_id, status="scheduled"))
        db_session.commit()

        assert len(repo.list_filtered()) == 2

    def test_filters_by_status(self, db_session: Session) -> None:
        template_id = _persisted_template(db_session)
        repo = TaskInstanceRepository(db_session)
        scheduled = repo.create(make_task_instance(template_id=template_id, status="scheduled"))
        repo.create(make_task_instance(template_id=template_id, status="pending"))
        db_session.commit()

        results = repo.list_filtered(status="scheduled")
        assert {i.id for i in results} == {scheduled.id}

    def test_filters_by_priority(self, db_session: Session) -> None:
        template_id = _persisted_template(db_session)
        repo = TaskInstanceRepository(db_session)
        high = repo.create(make_task_instance(template_id=template_id, status="pending", priority=3))
        repo.create(make_task_instance(template_id=template_id, status="pending", priority=1))
        db_session.commit()

        results = repo.list_filtered(priority=3)
        assert {i.id for i in results} == {high.id}

    def test_filters_by_type(self, db_session: Session) -> None:
        template_id = _persisted_template(db_session)
        repo = TaskInstanceRepository(db_session)
        fixed = repo.create(make_task_instance(template_id=template_id, status="pending", type="fixed"))
        repo.create(make_task_instance(template_id=template_id, status="pending", type="flexible"))
        db_session.commit()

        results = repo.list_filtered(type_="fixed")
        assert {i.id for i in results} == {fixed.id}

    def test_filters_combine_with_and_semantics(self, db_session: Session) -> None:
        template_id = _persisted_template(db_session)
        repo = TaskInstanceRepository(db_session)
        match = repo.create(make_task_instance(template_id=template_id, status="scheduled", priority=3, type="fixed"))
        repo.create(make_task_instance(template_id=template_id, status="scheduled", priority=1, type="fixed"))
        db_session.commit()

        results = repo.list_filtered(status="scheduled", priority=3, type_="fixed")
        assert {i.id for i in results} == {match.id}
