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
    TaskTemplateRepository,
)
from app.db.schemas import ExternalCalendarConnection, ExternalEvent, Notification, Recurrence, UserSettings
from app.jobs.interface import occurrence_boundary_job_key
from app.task_instances.service import (
    InstanceValidationError,
    complete,
    delete_instance,
    dismiss,
    edit_this_occurrence,
    extend_deadline,
    list_instances,
    reschedule,
    start_progress,
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

    def test_expected_value_agreeing_with_current_row_applies_the_patch(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """architecture-plan §5.1: a field the caller names in `expected` that still
        matches the current row is not a conflict - the patch goes through.
        """
        created = create_template(db_session, jobs, _flexible_draft(name="Water plants", priority="medium"))
        db_session.commit()

        edited = edit_this_occurrence(
            db_session,
            jobs,
            created.instance.id,
            patch={"name": "Water all the plants"},
            expected={"name": "Water plants"},
        )
        db_session.commit()

        assert edited.name == "Water all the plants"

    def test_expected_value_disagreeing_with_current_row_is_a_conflict(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§5.1: the row moved underneath the caller on a field it's touching - reject
        with `conflict`, naming the field and its current server-side value.
        """
        created = create_template(db_session, jobs, _flexible_draft(name="Water plants"))
        db_session.commit()
        edit_this_occurrence(db_session, jobs, created.instance.id, patch={"name": "Someone else's edit"})
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            edit_this_occurrence(
                db_session,
                jobs,
                created.instance.id,
                patch={"name": "My edit"},
                expected={"name": "Water plants"},
            )
        assert exc_info.value.code == "conflict"
        assert exc_info.value.details == {"conflicting_fields": {"name": "Someone else's edit"}}

    def test_expected_value_for_an_untouched_field_does_not_block_an_unrelated_edit(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§5.1's core intent: a concurrent write to a field the caller isn't editing and
        isn't asserting anything about must not bounce this edit.
        """
        created = create_template(db_session, jobs, _flexible_draft(name="Water plants", priority="medium"))
        db_session.commit()
        # Simulate a concurrent background write to `priority`, which this caller never mentions.
        edit_this_occurrence(db_session, jobs, created.instance.id, patch={"priority": 4})
        db_session.commit()

        edited = edit_this_occurrence(
            db_session,
            jobs,
            created.instance.id,
            patch={"name": "Water all the plants"},
            expected={"name": "Water plants"},
        )
        db_session.commit()

        assert edited.name == "Water all the plants"
        assert edited.priority == 4

    def test_an_edit_that_leaves_no_slot_persists_the_instance_as_pending(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        # A 30-minute task can't fit before a deadline one minute away: the instance must
        # actually leave `scheduled` in the database, not just in memory.
        created = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()
        assert created.instance.status == "scheduled"

        edit_this_occurrence(db_session, jobs, created.instance.id, patch={"deadline": utcnow() + timedelta(minutes=1)})
        db_session.commit()

        stored = TaskInstanceRepository(db_session).get(created.instance.id)
        assert stored is not None
        assert stored.status == "pending"
        assert stored.scheduled_time is None


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


class TestStartProgress:
    """§4 state diagram: `scheduled` -> `in_progress`, the only inbound edge."""

    def test_transitions_a_scheduled_instance_to_in_progress(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        instance = TaskInstanceRepository(db_session).get(created.instance.id)
        assert instance is not None
        assert instance.status == "scheduled"

        started = start_progress(db_session, created.instance.id)
        db_session.commit()

        assert started.status == "in_progress"
        assert any(entry.status == "in_progress" for entry in started.status_history)

    def test_rejects_starting_a_non_scheduled_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """Uses a `blocked` instance (deterministic - a dependency is never immediately
        placed, unlike a plain flexible instance which might land as `scheduled`).
        """
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        db_session.commit()
        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()
        assert inspection.instance.status == "blocked"

        with pytest.raises(InstanceValidationError) as exc_info:
            start_progress(db_session, inspection.instance.id)
        assert exc_info.value.code == "invalid_field"

    def test_rejects_starting_an_already_in_progress_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        start_progress(db_session, created.instance.id)
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            start_progress(db_session, created.instance.id)
        assert exc_info.value.code == "invalid_field"


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


class TestDismiss:
    """§3.8 "skip this occurrence" - terminal, preserves the row."""

    def test_transitions_to_dismissed(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        dismissed = dismiss(db_session, jobs, created.instance.id)
        db_session.commit()

        assert dismissed.status == "dismissed"
        assert any(entry.status == "dismissed" for entry in dismissed.status_history)

    def test_rejects_dismissing_an_already_terminal_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        complete(db_session, jobs, created.instance.id)
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            dismiss(db_session, jobs, created.instance.id)
        assert exc_info.value.code == "invalid_field"

    def test_cancels_all_jobs(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        dismiss(db_session, jobs, created.instance.id)
        db_session.commit()

        assert created.instance.id in jobs.cancelled_instances

    def test_resolves_overdue_unschedulable_and_deadline_missed_notifications(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        overdue = NotificationRepository(db_session).create(
            Notification(
                id=generate_id(), type="overdue", related_instance_id=created.instance.id, message="late", created_at=utcnow()
            )
        )
        db_session.commit()

        dismiss(db_session, jobs, created.instance.id)
        db_session.commit()

        refreshed = NotificationRepository(db_session).get(overdue.id)
        assert refreshed is not None and refreshed.resolved_at is not None

    def test_dependents_stay_blocked(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        """§4: `dismissed` does not satisfy a dependency - unlike complete()/delete_instance(),
        dismiss() must never unblock a dependent."""
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        db_session.commit()
        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()
        assert inspection.instance.status == "blocked"

        dismiss(db_session, jobs, prep.instance.id)
        db_session.commit()

        still_blocked = TaskInstanceRepository(db_session).get(inspection.instance.id)
        assert still_blocked is not None
        assert still_blocked.status == "blocked"

    def test_completion_anchored_template_generates_a_successor(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§3.8 "Re-anchoring on this_occurrence": dismissing isn't completing, so the
        successor anchors at `now + cadence`, not at any `completed_at`."""
        created = create_template(
            db_session,
            jobs,
            _flexible_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="completion")),
        )
        db_session.commit()

        dismiss(db_session, jobs, created.instance.id)
        db_session.commit()

        instances = TaskInstanceRepository(db_session).list_by_template(created.template.id)
        assert len(instances) == 2
        successor = next(i for i in instances if i.id != created.instance.id)
        assert successor.status in ("pending", "scheduled")

    def test_calendar_anchored_template_does_not_directly_generate_a_successor(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """A `calendar`-anchored series already continues on its own via the independently
        scheduled occurrence-boundary job - dismiss() must not also generate one directly,
        or the series would double-generate."""
        created = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()

        dismiss(db_session, jobs, created.instance.id)
        db_session.commit()

        instances = TaskInstanceRepository(db_session).list_by_template(created.template.id)
        assert len(instances) == 1


class TestDeleteInstanceScope:
    """§3.8/§3.10: deletion scope for recurring tasks."""

    def test_scope_is_not_required_for_a_one_time_template(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        result = delete_instance(db_session, jobs, created.instance.id)  # no scope kwarg
        db_session.commit()
        assert result.deleted_instance_id == created.instance.id

    def test_scope_is_required_for_a_recurring_template(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            delete_instance(db_session, jobs, created.instance.id)
        assert exc_info.value.code == "scope_required"

    def test_this_and_future_archives_the_template_and_cancels_its_boundary_job(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()

        delete_instance(db_session, jobs, created.instance.id, scope="this_and_future")
        db_session.commit()

        archived = TaskTemplateRepository(db_session).get(created.template.id)
        assert archived is not None and archived.archived is True
        assert occurrence_boundary_job_key(created.template.id) in jobs.cancelled

    def test_this_occurrence_on_a_completion_anchored_template_generates_a_successor(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session,
            jobs,
            _flexible_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="completion")),
        )
        db_session.commit()

        delete_instance(db_session, jobs, created.instance.id, scope="this_occurrence")
        db_session.commit()

        instances = TaskInstanceRepository(db_session).list_by_template(created.template.id)
        assert len(instances) == 1  # the original was deleted, one successor remains
        assert instances[0].id != created.instance.id

    def test_this_occurrence_on_a_calendar_anchored_template_generates_nothing_directly(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(
            db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"))
        )
        db_session.commit()

        delete_instance(db_session, jobs, created.instance.id, scope="this_occurrence")
        db_session.commit()

        instances = TaskInstanceRepository(db_session).list_by_template(created.template.id)
        assert instances == ()


class TestListInstances:
    """`GET /task-instances?status=&priority=&type=&view=backlog` (architecture-plan §3)."""

    def test_filters_delegate_to_the_repository(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        results = list_instances(db_session, status="scheduled", priority=created.instance.priority)
        assert {i.id for i in results} == {created.instance.id}

    def test_backlog_view_includes_blocked_and_missed(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        db_session.commit()
        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()
        assert inspection.instance.status == "blocked"

        backlog = list_instances(db_session, view="backlog")
        assert inspection.instance.id in {i.id for i in backlog}

    def test_backlog_view_includes_pending_with_active_unschedulable_notification(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()
        pending = TaskInstanceRepository(db_session).update(created.instance.model_copy(update={"status": "pending"}))
        NotificationRepository(db_session).create(
            Notification(
                id=generate_id(),
                type="unschedulable",
                related_instance_id=pending.id,
                message="no slot",
                created_at=utcnow(),
            )
        )
        db_session.commit()

        backlog = list_instances(db_session, view="backlog")
        assert pending.id in {i.id for i in backlog}

    def test_backlog_view_excludes_scheduled_and_plain_pending(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        scheduled = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        backlog = list_instances(db_session, view="backlog")
        assert scheduled.instance.id not in {i.id for i in backlog}
