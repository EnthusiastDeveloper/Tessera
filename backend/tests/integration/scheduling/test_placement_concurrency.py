"""Concurrent placement must not double-book a slot (issue #24).

Needs a real file-backed SQLite database and two threads with their own sessions -
the shared in-memory fixture can't show a race between two connections.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, generate_id
from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository, UserSettingsRepository
from app.db.schemas import Recurrence, TaskInstance, UserSettings
from app.db.session import build_engine
from app.jobs.interface import NoOpJobScheduler
from app.scheduling import adapter
from app.scheduling.orchestration import place_or_defer
from app.settings.service import DEFAULT_ACTIVE_HOURS, DEFAULT_DAILY_TIME_BUDGET
from app.task_templates.service import TaskTemplateDraft, create_template
from tests.fixtures.scheduling import ny

#: Mon 2026-03-02 08:00 New York - the first free grid point is 09:00.
_NOW = ny(2026, 3, 2, 8, 0)


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def _seed_two_pending_instances(factory: sessionmaker[Session]) -> list[str]:
    """Two 60-minute flexible instances, both `pending` and unplaced."""
    with factory() as db:
        UserSettingsRepository(db).create(
            UserSettings(
                id=generate_id(),
                timezone="America/New_York",
                active_hours=dict(DEFAULT_ACTIVE_HOURS),
                blackout_dates=(),
                daily_time_budget_minutes=dict(DEFAULT_DAILY_TIME_BUDGET),
                budget_enforcement="soft",
                first_day_of_week="monday",
            )
        )
        ids = []
        for name in ("Task A", "Task B"):
            draft = TaskTemplateDraft(
                name=name,
                type="flexible",
                recurrence=Recurrence(pattern="one_time", anchor="calendar"),
                priority="medium",
                estimated_duration_minutes=60,
                deadline_offset_minutes=60 * 24 * 30,
            )
            created = create_template(db, NoOpJobScheduler(), draft)
            TaskInstanceRepository(db).update(created.instance.model_copy(update={"status": "pending", "scheduled_time": None}))
            ids.append(created.instance.id)
        db.commit()
        return ids


def _place(factory: sessionmaker[Session], instance_id: str) -> None:
    with factory() as db:
        instance = TaskInstanceRepository(db).get(instance_id)
        assert instance is not None
        template = TaskTemplateRepository(db).get(instance.template_id)
        settings = UserSettingsRepository(db).get()
        assert template is not None and settings is not None
        place_or_defer(db, NoOpJobScheduler(), instance=instance, template=template, settings=settings, now=_NOW)
        db.commit()


def test_two_concurrent_placements_do_not_share_a_slot(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    first_id, second_id = _seed_two_pending_instances(session_factory)

    # Force the interleaving from the issue: the first placement has read the obstacle
    # set and chosen a slot but not yet committed when the second one starts.
    first_has_read = threading.Event()
    real_engine_call = adapter.schedule_pending_flexible_tasks

    def _slow_first(*args: Any, **kwargs: Any) -> Any:
        result = real_engine_call(*args, **kwargs)
        if threading.current_thread().name == "first":
            first_has_read.set()
            time.sleep(0.5)
        return result

    monkeypatch.setattr(adapter, "schedule_pending_flexible_tasks", _slow_first)

    errors: list[BaseException] = []

    def _run(instance_id: str) -> None:
        try:
            _place(session_factory, instance_id)
        except BaseException as exc:  # surfaced below; a thread can't fail the test directly
            errors.append(exc)

    first = threading.Thread(target=_run, args=(first_id,), name="first")
    second = threading.Thread(target=_run, args=(second_id,), name="second")
    first.start()
    assert first_has_read.wait(timeout=5)
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    assert errors == []

    with session_factory() as db:
        placed: list[TaskInstance] = [i for i in (TaskInstanceRepository(db).get(x) for x in (first_id, second_id)) if i]
    assert [i.status for i in placed] == ["scheduled", "scheduled"]
    a, b = sorted(placed, key=lambda i: i.scheduled_time or _NOW)
    assert a.scheduled_time is not None and b.scheduled_time is not None
    assert a.scheduled_time + timedelta(minutes=a.estimated_duration_minutes) <= b.scheduled_time, "double-booked"
