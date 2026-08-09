"""Integration tests for app.task_instances.service. See design doc §3.3, §3.8, §3.10,
§4, §6.5-§6.9; Worked Examples D, F, K.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.base import generate_id, utcnow
from app.db.repositories import (
    ExternalCalendarConnectionRepository,
    ExternalEventRepository,
    NotificationRepository,
    OAuthTokenRepository,
    TaskInstanceRepository,
)
from app.db.schemas import ExternalCalendarConnection, ExternalEvent, Notification, Recurrence, UserSettings
from app.task_instances.service import (
    InstanceValidationError,
    complete,
    delete_instance,
    edit_this_occurrence,
    extend_deadline,
    reschedule,
)
from app.task_templates.service import TaskTemplateDraft, create_template
from tests.fixtures.db_entities import make_oauth_token
from tests.fixtures.jobs import RecordingJobScheduler


def _flexible_draft(**overrides: object) -> TaskTemplateDraft:
    defaults: dict[str, object] = {
        "name": "Deep clean garage",
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 60,
        "deadline_offset_minutes": 60 * 24 * 5,
    }
    defaults.update(overrides)
    return TaskTemplateDraft(**defaults)  # type: ignore[arg-type]


def _fixed_draft(**overrides: object) -> TaskTemplateDraft:
    defaults: dict[str, object] = {
        "name": "Team sync",
        "type": "fixed",
        "fixed_time_of_day": "18:00",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 60,
    }
    defaults.update(overrides)
    return TaskTemplateDraft(**defaults)  # type: ignore[arg-type]


class TestEditThisOccurrence:
    def test_sets_detached_and_touches_only_the_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft(name="Water plants", estimated_duration_minutes=5))
        db_session.commit()

        edited = edit_this_occurrence(db_session, jobs, created.instance.id, patch={"name": "Water all the plants"})
        db_session.commit()

        assert edited.detached is True
        assert edited.name == "Water all the plants"

    def test_scheduled_time_is_not_an_editable_field(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            edit_this_occurrence(db_session, jobs, created.instance.id, patch={"scheduled_time": utcnow()})
        assert exc_info.value.code == "invalid_field"

    def test_deadline_is_only_editable_on_a_flexible_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            edit_this_occurrence(db_session, jobs, created.instance.id, patch={"deadline": utcnow()})
        assert exc_info.value.code == "invalid_field"

    def test_infeasible_duration_override_is_rejected(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            edit_this_occurrence(db_session, jobs, created.instance.id, patch={"estimated_duration_minutes": 999_999})
        assert exc_info.value.code == "infeasible_duration"

    def test_duration_change_re_enters_placement(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()
        assert created.instance.status == "scheduled"

        edited = edit_this_occurrence(db_session, jobs, created.instance.id, patch={"estimated_duration_minutes": 90})
        db_session.commit()

        assert edited.estimated_duration_minutes == 90
        assert edited.status in ("scheduled", "pending")


class TestReschedule:
    def test_moves_a_fixed_instance_and_rewires_its_jobs(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft(reminder_offsets_minutes=(60, 15)))
        db_session.commit()
        jobs.scheduled.clear()

        assert created.instance.scheduled_time is not None
        new_time = created.instance.scheduled_time + timedelta(days=1)
        moved = reschedule(db_session, jobs, created.instance.id, new_scheduled_time=new_time)
        db_session.commit()

        assert moved.scheduled_time == new_time
        assert moved.detached is True
        assert any(key.startswith("overdue:") for key in jobs.scheduled_keys())
        assert sum(1 for key in jobs.scheduled_keys() if key.startswith("reminder:")) == 2

    def test_rejects_rescheduling_a_flexible_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            reschedule(db_session, jobs, created.instance.id, new_scheduled_time=utcnow())
        assert exc_info.value.code == "invalid_field"

    def test_conflicting_time_is_rejected(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        first = create_template(db_session, jobs, _fixed_draft(name="Team sync"))
        db_session.commit()
        second = create_template(db_session, jobs, _fixed_draft(name="1:1", fixed_time_of_day="09:00"))
        db_session.commit()

        assert first.instance.scheduled_time is not None
        with pytest.raises(InstanceValidationError) as exc_info:
            reschedule(db_session, jobs, second.instance.id, new_scheduled_time=first.instance.scheduled_time)
        assert exc_info.value.code == "creation_conflict"

    def test_rescheduling_clear_of_a_colliding_external_event_resolves_its_sync_conflict(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§3.9/§6.4/§6.6 Rev 7: a manual reschedule that clears the collision resolves the
        `sync_conflict` immediately, rather than waiting for the next poll (Stage 7).
        """
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        assert created.instance.scheduled_time is not None
        conflict_start = created.instance.scheduled_time
        conflict_end = conflict_start + timedelta(hours=1)

        token = OAuthTokenRepository(db_session).create(make_oauth_token())
        connection = ExternalCalendarConnectionRepository(db_session).create(
            ExternalCalendarConnection(
                id=generate_id(), provider="google", oauth_credentials_ref=token.id, refresh_interval_minutes=15, enabled=True
            )
        )
        ExternalEventRepository(db_session).upsert(
            ExternalEvent(
                id=generate_id(),
                connection_id=connection.id,
                provider_event_id="evt-1",
                start=conflict_start,
                end=conflict_end,
                title="Surprise meeting",
                fetched_at=utcnow(),
            )
        )
        sync_conflict = NotificationRepository(db_session).create(
            Notification(
                id=generate_id(),
                type="sync_conflict",
                related_instance_id=created.instance.id,
                message="collision",
                created_at=utcnow(),
            )
        )
        db_session.commit()

        new_time = conflict_start + timedelta(days=3)  # clear of the external event
        reschedule(db_session, jobs, created.instance.id, new_scheduled_time=new_time)
        db_session.commit()

        refreshed = NotificationRepository(db_session).get(sync_conflict.id)
        assert refreshed is not None and refreshed.resolved_at is not None


class TestComplete:
    def test_example_f_completes_directly_from_pending(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§4: a flexible instance can complete directly from `pending` - the user already
        did the task, `scheduled_time` need never have been set (Common Pitfall #5).
        """
        created = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()
        instance = TaskInstanceRepository(db_session).get(created.instance.id)
        assert instance is not None
        assert instance.status in ("pending", "scheduled")

        completed = complete(db_session, jobs, created.instance.id)
        db_session.commit()

        assert completed.status == "completed"
        assert completed.completed_at is not None

    def test_cancels_all_jobs_for_the_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        complete(db_session, jobs, created.instance.id)
        db_session.commit()

        assert created.instance.id in jobs.cancelled_instances

    def test_rejects_completing_an_already_terminal_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()
        complete(db_session, jobs, created.instance.id)
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            complete(db_session, jobs, created.instance.id)
        assert exc_info.value.code == "invalid_field"

    def test_example_d_completing_the_last_dependency_unblocks_and_places_immediately(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car", estimated_duration_minutes=30))
        db_session.commit()
        inspection = create_template(
            db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,), estimated_duration_minutes=30)
        )
        db_session.commit()
        assert inspection.instance.status == "blocked"

        complete(db_session, jobs, prep.instance.id)
        db_session.commit()

        unblocked = TaskInstanceRepository(db_session).get(inspection.instance.id)
        assert unblocked is not None
        assert unblocked.status in ("scheduled", "pending")  # promoted out of blocked, placed in the same transaction


class TestExtendDeadline:
    def test_example_k_missed_instance_extends_and_re_enters_placement(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft(deadline_offset_minutes=5))
        db_session.commit()
        now = utcnow()
        missed = TaskInstanceRepository(db_session).get(created.instance.id)
        assert missed is not None
        # Force it into `missed` directly - the gate itself is `place_or_defer`'s job and
        # is covered by the scheduling-orchestration tests; this test is extend_deadline's contract.
        forced = TaskInstanceRepository(db_session).update(missed.model_copy(update={"status": "missed"}))
        db_session.commit()
        assert forced.status == "missed"

        extended = extend_deadline(db_session, jobs, created.instance.id, new_deadline=now + timedelta(days=3))
        db_session.commit()

        assert extended.status in ("scheduled", "pending")
        assert extended.detached is True

    def test_rejects_extending_a_non_missed_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            extend_deadline(db_session, jobs, created.instance.id, new_deadline=utcnow() + timedelta(days=1))
        assert exc_info.value.code == "invalid_field"


class TestDeleteInstance:
    def test_deleting_a_dependency_unlinks_rather_than_cascades(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        db_session.commit()
        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()

        result = delete_instance(db_session, jobs, prep.instance.id)
        db_session.commit()

        assert result.deleted_instance_id == prep.instance.id
        assert TaskInstanceRepository(db_session).get(prep.instance.id) is None

        survivor = TaskInstanceRepository(db_session).get(inspection.instance.id)
        assert survivor is not None
        assert survivor.dependencies == ()

    def test_cancels_all_jobs_for_the_deleted_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        delete_instance(db_session, jobs, created.instance.id)
        db_session.commit()

        assert created.instance.id in jobs.cancelled_instances

    def test_example_d_deleting_the_last_dependency_unblocks_and_places_immediately(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car", estimated_duration_minutes=30))
        db_session.commit()
        inspection = create_template(
            db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,), estimated_duration_minutes=30)
        )
        db_session.commit()

        result = delete_instance(db_session, jobs, prep.instance.id)
        db_session.commit()

        assert inspection.instance.id in result.unblocked_instance_ids
        unblocked = TaskInstanceRepository(db_session).get(inspection.instance.id)
        assert unblocked is not None
        assert unblocked.status != "blocked"
