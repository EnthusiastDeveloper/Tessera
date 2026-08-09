"""External-calendar obstacle wiring: `gather_obstacles`/`has_fixed_conflict` now include
cached `ExternalEvent` rows, filtered per design doc §7 (transparent/all-day excluded).
Also the full end-to-end versions of Worked Examples A and B, now genuinely exercising a
persisted `ExternalEvent` row rather than a bare `Obstacle` fixture (design doc §10).
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

import app.task_templates.service as task_templates_service
from app.db.base import generate_id, utcnow
from app.db.repositories import (
    ExternalCalendarConnectionRepository,
    ExternalEventRepository,
    TaskInstanceRepository,
    TaskTemplateRepository,
    UserSettingsRepository,
)
from app.db.schemas import ActiveHoursWindow, Recurrence, StatusHistoryEntry, TaskInstance, TaskTemplate, UserSettings
from app.scheduling.adapter import attempt_placement, gather_external_obstacles, gather_obstacles
from app.task_templates.service import TaskTemplateDraft, TemplateValidationError, create_template
from tests.fixtures.db_entities import make_external_calendar_connection, make_external_event
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import ny

NY = ZoneInfo("America/New_York")
_DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _persisted_connection(db: Session) -> str:
    connection = ExternalCalendarConnectionRepository(db).create(make_external_calendar_connection())
    db.commit()
    return connection.id


class TestFiltering:
    """Design doc §7's filter: transparent/"Free" events and all-day events never obstruct."""

    def test_opaque_timed_event_is_an_obstacle(self, db_session: Session) -> None:
        connection_id = _persisted_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection_id,
                provider_event_id="evt-1",
                start=ny(2026, 3, 2, 18, 0),
                end=ny(2026, 3, 2, 19, 0),
                is_transparent=False,
                is_all_day=False,
            )
        )
        db_session.commit()

        assert len(gather_external_obstacles(db_session)) == 1

    def test_transparent_event_is_never_an_obstacle(self, db_session: Session) -> None:
        connection_id = _persisted_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection_id,
                provider_event_id="evt-free",
                start=ny(2026, 3, 2, 18, 0),
                end=ny(2026, 3, 2, 19, 0),
                is_transparent=True,
            )
        )
        db_session.commit()

        assert gather_external_obstacles(db_session) == ()

    def test_all_day_event_is_never_an_obstacle(self, db_session: Session) -> None:
        connection_id = _persisted_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection_id,
                provider_event_id="evt-allday",
                start=ny(2026, 3, 2, 0, 0),
                end=ny(2026, 3, 3, 0, 0),
                is_all_day=True,
            )
        )
        db_session.commit()

        assert gather_external_obstacles(db_session) == ()

    def test_soft_deleted_event_is_never_an_obstacle(self, db_session: Session) -> None:
        connection_id = _persisted_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection_id,
                provider_event_id="evt-removed",
                start=ny(2026, 3, 2, 18, 0),
                end=ny(2026, 3, 2, 19, 0),
                deleted_at=ny(2026, 3, 1),
            )
        )
        db_session.commit()

        assert gather_external_obstacles(db_session) == ()

    def test_gather_obstacles_includes_external_events_alongside_instances(self, db_session: Session) -> None:
        connection_id = _persisted_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection_id, provider_event_id="evt-1", start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 19, 0)
            )
        )
        db_session.commit()

        assert len(gather_obstacles(db_session)) == 1


class TestExampleAFixedCreationHardBlock:
    """Design doc §10 Example A: an opaque external event blocks fixed-task creation
    outright - `creation_conflict`, nothing persisted. §6.5 already ran `has_fixed_conflict`
    before Stage 7; this proves it now actually sees external events, end to end through
    `create_template`, not just the underlying obstacle-gathering unit.
    """

    def test_colliding_external_event_hard_blocks_fixed_creation(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection_id = _persisted_connection(db_session)
        ExternalEventRepository(db_session).upsert(
            make_external_event(
                connection_id=connection_id,
                provider_event_id="date-night",
                title="Date night",
                start=ny(2026, 3, 2, 18, 0),
                end=ny(2026, 3, 2, 22, 0),
                is_transparent=False,
                is_all_day=False,
            )
        )
        db_session.commit()

        # `settings.timezone` defaults to America/New_York (tests/integration/conftest.py's
        # `settings` fixture) - "today" at fixed_time_of_day 18:00 must land on the same
        # Mon 2026-03-02 the external event occupies for this to be a real collision.
        monkeypatch.setattr(task_templates_service, "utcnow", lambda: ny(2026, 3, 2, 9, 0))

        draft = TaskTemplateDraft(
            name="Team sync",
            type="fixed",
            fixed_time_of_day="18:00",
            recurrence=Recurrence(pattern="one_time", anchor="calendar"),
            priority="medium",
            estimated_duration_minutes=60,
        )
        with pytest.raises(TemplateValidationError) as exc_info:
            create_template(db_session, jobs, draft)
        assert exc_info.value.code == "creation_conflict"
        # `create_template` only flushes, never commits - production relies on
        # `session_scope()` rolling back the whole request on any raised exception
        # (app/db/session.py) for "creates nothing" to hold; mirror that here since this
        # test drives the raw session directly (same pattern as
        # tests/integration/task_templates/test_service.py's own Example A test).
        db_session.rollback()
        assert TaskTemplateRepository(db_session).list() == ()


class TestExampleBFlexiblePlacementAgainstExternalObstacles:
    """Design doc §10 Example B: merged active-hours override + grid alignment, with the
    obstacles now real persisted `ExternalEvent` rows instead of bare fixtures.
    """

    def test_places_at_the_first_grid_point_after_the_external_obstacle_clears(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        settings = UserSettingsRepository(db_session).update(
            settings.model_copy(
                update={
                    "timezone": "America/New_York",
                    "active_hours": dict.fromkeys(_DAY_NAMES, ActiveHoursWindow(start="18:00", end="21:00")),
                    "daily_time_budget_minutes": dict.fromkeys(_DAY_NAMES, None),
                }
            )
        )
        db_session.commit()

        connection_id = _persisted_connection(db_session)
        event_repo = ExternalEventRepository(db_session)
        event_repo.upsert(
            make_external_event(
                connection_id=connection_id, provider_event_id="mon", start=ny(2026, 3, 2, 18, 0), end=ny(2026, 3, 2, 21, 0)
            )
        )
        event_repo.upsert(
            make_external_event(
                connection_id=connection_id, provider_event_id="tue", start=ny(2026, 3, 3, 18, 0), end=ny(2026, 3, 3, 21, 37)
            )
        )
        db_session.commit()

        template = TaskTemplateRepository(db_session).create(
            TaskTemplate(
                id=generate_id(),
                name="Replace HVAC filters",
                type="flexible",
                recurrence=Recurrence(pattern="monthly", interval=1, anchor="completion"),
                priority="medium",
                estimated_duration_minutes=30,
                deadline_offset_minutes=7200,
                active_hours_override={"tuesday": ActiveHoursWindow(start="18:00", end="22:30")},
                created_at=utcnow(),
                updated_at=utcnow(),
                version=1,
            )
        )
        db_session.commit()

        now = ny(2026, 3, 2, 9, 0)
        instance = TaskInstanceRepository(db_session).create(
            TaskInstance(
                id=generate_id(),
                template_id=template.id,
                name=template.name,
                type=template.type,
                priority=2,
                estimated_duration_minutes=30,
                status="pending",
                deadline=ny(2026, 3, 7, 9, 0),
                status_history=(StatusHistoryEntry(status="pending", at=now),),
                generated_at=now,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        db_session.commit()

        result = attempt_placement(db_session, instance=instance, template=template, settings=settings, now=now)

        assert len(result.placements) == 1
        placed = result.placements[0].scheduled_start.astimezone(NY)
        assert (placed.year, placed.month, placed.day, placed.hour, placed.minute) == (2026, 3, 3, 21, 45)
