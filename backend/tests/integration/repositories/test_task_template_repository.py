"""Repository CRUD tests for `TaskTemplate`. See design doc §3.2, implementation-plan Stage 2."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.repositories import TaskTemplateRepository
from app.db.schemas import ActiveHoursWindow
from tests.fixtures.db_entities import make_task_template


def test_create_and_get_round_trip(db_session: Session) -> None:
    repo = TaskTemplateRepository(db_session)
    template = make_task_template(
        active_hours_override={"monday": None, "saturday": ActiveHoursWindow(start="09:00", end="21:00")}
    )
    created = repo.create(template)
    db_session.commit()
    db_session.expire_all()  # force a real DB read, not the identity map

    fetched = repo.get(template.id)
    assert fetched == created


def test_get_missing_returns_none(db_session: Session) -> None:
    repo = TaskTemplateRepository(db_session)
    assert repo.get("does-not-exist") is None


def test_list_excludes_archived_by_default(db_session: Session) -> None:
    repo = TaskTemplateRepository(db_session)
    active = repo.create(make_task_template(name="Active"))
    archived_template = repo.create(make_task_template(name="Archived"))
    repo.archive(archived_template.id)
    db_session.commit()

    listed_ids = {template.id for template in repo.list()}
    assert active.id in listed_ids
    assert archived_template.id not in listed_ids

    all_ids = {template.id for template in repo.list(include_archived=True)}
    assert archived_template.id in all_ids


def test_update_persists_changes_and_increments_version(db_session: Session) -> None:
    repo = TaskTemplateRepository(db_session)
    created = repo.create(make_task_template(name="Original"))
    db_session.commit()

    updated = repo.update(created.model_copy(update={"name": "Renamed"}))
    db_session.commit()

    assert updated.name == "Renamed"
    assert updated.version == created.version + 1


def test_update_ignores_caller_supplied_version(db_session: Session) -> None:
    """`version` is the optimistic-lock token (architecture-plan §5) - a caller can't set it directly."""
    repo = TaskTemplateRepository(db_session)
    created = repo.create(make_task_template())
    db_session.commit()

    updated = repo.update(created.model_copy(update={"name": "Renamed", "version": 999}))
    db_session.commit()

    assert updated.version == created.version + 1


def test_archive_sets_archived_true(db_session: Session) -> None:
    repo = TaskTemplateRepository(db_session)
    created = repo.create(make_task_template())
    archived = repo.archive(created.id)
    assert archived.archived is True


def test_active_hours_override_none_is_distinct_from_empty_dict(db_session: Session) -> None:
    """§3.2: `None` means "no override at all"; a per-day `null` inside the dict means "excluded"."""
    repo = TaskTemplateRepository(db_session)
    no_override = repo.create(make_task_template(active_hours_override=None))
    excluded_monday = repo.create(make_task_template(active_hours_override={"monday": None}))
    db_session.commit()
    db_session.expire_all()

    fetched_no_override = repo.get(no_override.id)
    fetched_excluded_monday = repo.get(excluded_monday.id)
    assert fetched_no_override is not None
    assert fetched_excluded_monday is not None
    assert fetched_no_override.active_hours_override is None
    assert fetched_excluded_monday.active_hours_override == {"monday": None}
