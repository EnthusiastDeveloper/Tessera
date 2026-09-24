"""Integration tests for app.task_templates.service. See design doc §3.2, §3.8, §3.10;
Worked Examples A, D, L, M.
"""

from __future__ import annotations

from datetime import UTC, timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.base import generate_id
from app.db.repositories import NotificationRepository, TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import Notification, Recurrence, UserSettings
from app.task_instances import service as task_instances_service
from app.task_instances.service import edit_this_occurrence, reschedule
from app.task_templates import service as task_templates_service
from app.task_templates.service import (
    TaskTemplateDraft,
    TemplateValidationError,
    archive_template,
    create_template,
    edit_template_this_and_future,
    get_template,
)
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import ny


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


class TestCreateTemplate:
    def test_flexible_template_spawns_a_pending_or_scheduled_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        result = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()
        assert result.instance.template_id == result.template.id
        assert result.instance.status in ("scheduled", "pending")

    def test_fixed_template_spawns_a_scheduled_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        result = create_template(db_session, jobs, _fixed_draft(reminder_offsets_minutes=(60, 15, 0)))
        db_session.commit()
        assert result.instance.status == "scheduled"
        assert result.instance.scheduled_time is not None
        assert any(key.startswith("overdue:") for key in jobs.scheduled_keys())
        assert sum(1 for key in jobs.scheduled_keys() if key.startswith("reminder:")) == 3

    def test_a_blocked_fixed_instance_schedules_no_jobs_yet(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Buy supplies"))
        db_session.commit()
        jobs.scheduled.clear()

        create_template(db_session, jobs, _fixed_draft(name="Assemble", dependencies=(prep.instance.id,)))
        db_session.commit()

        assert jobs.scheduled == []

    def test_example_a_fixed_conflict_is_a_hard_block_creating_nothing(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        create_template(db_session, jobs, _fixed_draft(name="Team sync"))
        db_session.commit()

        templates_before = len(TaskTemplateRepository(db_session).list(include_archived=True))
        with pytest.raises(TemplateValidationError) as exc_info:
            create_template(db_session, jobs, _fixed_draft(name="Another sync", fixed_time_of_day="18:30"))
        assert exc_info.value.code == "creation_conflict"
        # `create_template` only flushes, never commits - production relies on
        # `session_scope()` rolling back the whole request on any raised exception
        # (app/db/session.py) for "creates nothing" to hold. Mirror that here since this
        # test drives the raw session directly.
        db_session.rollback()
        assert len(TaskTemplateRepository(db_session).list(include_archived=True)) == templates_before

    def test_example_i_infeasible_duration_is_rejected_at_creation(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        with pytest.raises(TemplateValidationError) as exc_info:
            create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=999_999))
        assert exc_info.value.code == "infeasible_duration"

    def test_completion_anchor_on_a_fixed_template_is_rejected(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        with pytest.raises(TemplateValidationError) as exc_info:
            create_template(db_session, jobs, _fixed_draft(recurrence=Recurrence(pattern="monthly", anchor="completion")))
        assert exc_info.value.code == "invalid_recurrence_anchor"

    def test_dependencies_start_the_instance_blocked_not_pending(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        prep = create_template(db_session, jobs, _flexible_draft(name="Prepare car"))
        db_session.commit()

        inspection = create_template(db_session, jobs, _flexible_draft(name="Inspection", dependencies=(prep.instance.id,)))
        db_session.commit()

        assert inspection.instance.status == "blocked"
        assert inspection.instance.scheduled_time is None
        assert inspection.instance.dependencies == (prep.instance.id,)

    def test_cycle_detected_is_rejected(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        """§6.1's wiring, proven directly: a cycle can't arise through creation-only
        dependency-setting alone (a brand-new instance has no existing incoming edges to
        close a loop with), so this constructs the graph state via two real instances and
        asserts the *would-be* cycle is caught, matching the wiring `create_template`
        itself uses (`_ensure_no_cycle` against the real edge graph plus the proposal).
        """
        from app.task_templates.service import _ensure_no_cycle  # the same helper create_template calls

        a = create_template(db_session, jobs, _flexible_draft(name="A"))
        db_session.commit()
        b = create_template(db_session, jobs, _flexible_draft(name="B", dependencies=(a.instance.id,)))
        db_session.commit()

        # Proposing that A depend on B would close A -> B -> A.
        with pytest.raises(TemplateValidationError) as exc_info:
            _ensure_no_cycle(db_session, dependency_ids=(b.instance.id,), dependent_id=a.instance.id)
        assert exc_info.value.code == "cycle_detected"


class TestGetTemplate:
    def test_returns_the_template(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()

        fetched = get_template(db_session, created.template.id)
        assert fetched == created.template

    def test_returns_an_archived_template_rather_than_404ing(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """§3.8: archived, not hard-deleted, specifically to keep template_id references
        valid - a caller reopening a stale reference must see archived: true, not a 404."""
        created = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()
        archive_template(db_session, jobs, created.template.id)
        db_session.commit()

        fetched = get_template(db_session, created.template.id)
        assert fetched.archived is True

    def test_missing_template_raises_not_found(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        with pytest.raises(TemplateValidationError) as exc_info:
            get_template(db_session, "does-not-exist")
        assert exc_info.value.code == "not_found"


class TestArchiveTemplate:
    def test_archive_soft_deletes_and_keeps_history(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        result = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()

        archived = archive_template(db_session, jobs, result.template.id)
        db_session.commit()

        assert archived.template.archived is True
        assert TaskTemplateRepository(db_session).get(result.template.id) is not None  # never hard-deleted


class TestEditThisAndFuture:
    def test_example_l_and_m_detached_instance_is_skipped_by_this_and_future(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        bill_pay = create_template(
            db_session,
            jobs,
            _flexible_draft(
                name="Pay Utility Bills",
                estimated_duration_minutes=10,
                recurrence=Recurrence(pattern="monthly", anchor="calendar"),
            ),
        )
        db_session.commit()

        # Example L: "this occurrence" override detaches the live instance.
        edited = edit_this_occurrence(db_session, jobs, bill_pay.instance.id, patch={"estimated_duration_minutes": 45})
        db_session.commit()
        assert edited.detached is True
        assert edited.estimated_duration_minutes == 45
        unchanged_template = TaskTemplateRepository(db_session).get(bill_pay.template.id)
        assert unchanged_template is not None
        assert unchanged_template.estimated_duration_minutes == 10

        # Example M: "this and future" updates the template but skips the detached instance.
        updated_template = edit_template_this_and_future(
            db_session, jobs, bill_pay.template.id, patch={"estimated_duration_minutes": 15}
        )
        db_session.commit()
        assert updated_template.estimated_duration_minutes == 15

        still_detached = TaskInstanceRepository(db_session).get(bill_pay.instance.id)
        assert still_detached is not None
        assert still_detached.estimated_duration_minutes == 45, "a detached instance must be skipped entirely"

    def test_this_and_future_propagates_to_a_non_detached_live_instance(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        chore = create_template(db_session, jobs, _flexible_draft(name="Water plants", estimated_duration_minutes=5))
        db_session.commit()

        edit_template_this_and_future(
            db_session, jobs, chore.template.id, patch={"name": "Water all plants", "estimated_duration_minutes": 20}
        )
        db_session.commit()

        propagated = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert propagated is not None
        assert propagated.name == "Water all plants"
        assert propagated.estimated_duration_minutes == 20

    def test_infeasible_duration_is_rejected_on_this_and_future_edit(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        result = create_template(db_session, jobs, _flexible_draft())
        db_session.commit()

        with pytest.raises(TemplateValidationError) as exc_info:
            edit_template_this_and_future(db_session, jobs, result.template.id, patch={"estimated_duration_minutes": 999_999})
        assert exc_info.value.code == "infeasible_duration"

    def test_unknown_template_id_is_rejected(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        with pytest.raises(TemplateValidationError) as exc_info:
            edit_template_this_and_future(db_session, jobs, "does-not-exist", patch={"name": "New name"})
        assert exc_info.value.code == "not_found"

    def test_completion_anchor_on_a_fixed_template_is_rejected(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        # §3.2: `anchor: "completion"` is only valid on a flexible template - this is the
        # this-and-future edit path's own copy of that check (create_template's is tested
        # separately), since an edit can change `type` in the same patch a create can't.
        result = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        with pytest.raises(TemplateValidationError) as exc_info:
            edit_template_this_and_future(
                db_session, jobs, result.template.id, patch={"recurrence": Recurrence(pattern="daily", anchor="completion")}
            )
        assert exc_info.value.code == "invalid_recurrence_anchor"


#: Mon 2026-03-02 08:00 New York - before the default 09:00-17:00 active-hours window
#: opens, so a flexible placement's first candidate slot is deterministic (09:00).
_NOW = ny(2026, 3, 2, 8, 0)


@pytest.fixture
def pinned_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_templates_service, "utcnow", lambda: _NOW)
    monkeypatch.setattr(task_instances_service, "utcnow", lambda: _NOW)


@pytest.mark.usefixtures("pinned_now")
class TestThisAndFutureFixedTimeOfDay:
    """§3.10 + §14.1: a `fixed_time_of_day` edit re-projects the live instance's
    `scheduled_time` onto its own local date, subject to §6.5's hard block.
    """

    def test_retimes_a_non_detached_scheduled_instance_on_its_own_date(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        sync = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        assert sync.instance.scheduled_time == ny(2026, 3, 2, 18, 0)

        edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"fixed_time_of_day": "19:30"})
        db_session.commit()

        retimed = TaskInstanceRepository(db_session).get(sync.instance.id)
        assert retimed is not None
        assert retimed.scheduled_time == ny(2026, 3, 2, 19, 30)
        assert retimed.detached is False, "propagation is not a this-occurrence edit"

    def test_a_colliding_new_time_rejects_the_whole_edit(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        create_template(db_session, jobs, _fixed_draft(name="Dinner", fixed_time_of_day="18:00"))
        call = create_template(db_session, jobs, _fixed_draft(name="Call", fixed_time_of_day="20:00"))
        db_session.commit()

        with pytest.raises(TemplateValidationError) as exc_info:
            edit_template_this_and_future(db_session, jobs, call.template.id, patch={"fixed_time_of_day": "18:30"})
        assert exc_info.value.code == "creation_conflict"

        template = TaskTemplateRepository(db_session).get(call.template.id)
        instance = TaskInstanceRepository(db_session).get(call.instance.id)
        assert template is not None and template.fixed_time_of_day == "20:00", "rejected before the template write"
        assert instance is not None and instance.scheduled_time == ny(2026, 3, 2, 20, 0)

    def test_a_detached_instance_keeps_its_manually_chosen_time(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        # §6.6 (Rev 7): a manually rescheduled instance "will not be overwritten if the
        # template's fixed_time_of_day is later edited with 'this and future' scope".
        sync = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        reschedule(db_session, jobs, sync.instance.id, new_scheduled_time=ny(2026, 3, 2, 21, 0))
        db_session.commit()

        updated = edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"fixed_time_of_day": "07:00"})
        db_session.commit()

        assert updated.fixed_time_of_day == "07:00"
        untouched = TaskInstanceRepository(db_session).get(sync.instance.id)
        assert untouched is not None
        assert untouched.scheduled_time == ny(2026, 3, 2, 21, 0)

    def test_resending_the_unchanged_time_moves_nothing(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        # The edit form sends fixed_time_of_day on every save, changed or not.
        sync = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()

        edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"name": "Renamed", "fixed_time_of_day": "18:00"})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(sync.instance.id)
        assert instance is not None
        assert instance.name == "Renamed"
        assert instance.scheduled_time == ny(2026, 3, 2, 18, 0)

    def test_retiming_resolves_a_sync_conflict_the_new_time_clears(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        sync = create_template(db_session, jobs, _fixed_draft())
        db_session.commit()
        conflict = NotificationRepository(db_session).create(
            Notification(
                id=generate_id(),
                type="sync_conflict",
                related_instance_id=sync.instance.id,
                message="collides",
                created_at=_NOW,
            )
        )
        db_session.commit()

        edit_template_this_and_future(db_session, jobs, sync.template.id, patch={"fixed_time_of_day": "19:30"})
        db_session.commit()

        resolved = NotificationRepository(db_session).get(conflict.id)
        assert resolved is not None
        assert resolved.resolved_at is not None


@pytest.mark.usefixtures("pinned_now")
class TestThisAndFutureDeadlineOffset:
    """§3.10 + §9.1: a `deadline_offset_minutes` edit moves the live flexible instance's
    `deadline` by the same delta, re-entering §6.2 only when its placement is invalidated.
    """

    def test_a_longer_offset_extends_the_deadline_and_keeps_the_slot(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        chore = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()
        assert chore.instance.status == "scheduled"
        original_slot = chore.instance.scheduled_time

        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"deadline_offset_minutes": 60 * 24 * 7})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert instance is not None
        # Elapsed minutes, not wall-clock days (§14.1): this window crosses the 2026-03-08
        # DST change, so the deadline lands at 09:00 local rather than 08:00.
        assert instance.deadline == _NOW.astimezone(UTC) + timedelta(days=7)
        assert instance.status == "scheduled"
        assert instance.scheduled_time == original_slot, "incremental fit: a still-valid slot is never moved"

    def test_a_deadline_that_no_longer_covers_the_slot_evicts_it(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        chore = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()
        assert chore.instance.scheduled_time == ny(2026, 3, 2, 9, 0)

        # Deadline now 08:30 - before the active-hours window even opens, so there is
        # no slot left at all: evicted, persisted as pending, flagged unschedulable.
        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"deadline_offset_minutes": 30})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert instance is not None
        assert instance.status == "pending"
        assert instance.scheduled_time is None
        assert instance.deadline == ny(2026, 3, 2, 8, 30)
        assert [n.type for n in NotificationRepository(db_session).list_for_instance(chore.instance.id)] == ["unschedulable"]

    def test_an_already_elapsed_deadline_goes_straight_to_missed(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        chore = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()

        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"deadline_offset_minutes": 0})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert instance is not None
        assert instance.status == "missed"

    def test_a_missed_instance_is_left_for_the_user_to_resolve(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        chore = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30, deadline_offset_minutes=0))
        db_session.commit()
        assert chore.instance.status == "missed"

        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"deadline_offset_minutes": 60 * 24})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert instance is not None
        assert instance.status == "missed"
        assert instance.deadline == _NOW

    def test_a_detached_instance_keeps_its_own_deadline(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        # §6.7 (Rev 7): a later this-and-future offset edit "won't silently re-shorten a
        # deadline the user just deliberately extended".
        chore = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30))
        db_session.commit()
        chosen = _NOW + timedelta(days=10)
        edit_this_occurrence(db_session, jobs, chore.instance.id, patch={"deadline": chosen})
        db_session.commit()

        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"deadline_offset_minutes": 60})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert instance is not None
        assert instance.deadline == chosen


@pytest.mark.usefixtures("pinned_now")
class TestThisAndFutureEviction:
    def test_a_grown_duration_that_no_longer_fits_is_persisted_as_pending(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        # Deadline 10:00, placed 09:00-09:30. At 90 minutes it can't finish by 10:00, so
        # the instance must actually leave `scheduled` in the database - not just in the
        # in-memory copy handed to the placement attempt.
        chore = create_template(db_session, jobs, _flexible_draft(estimated_duration_minutes=30, deadline_offset_minutes=120))
        db_session.commit()
        assert chore.instance.scheduled_time == ny(2026, 3, 2, 9, 0)

        edit_template_this_and_future(db_session, jobs, chore.template.id, patch={"estimated_duration_minutes": 90})
        db_session.commit()

        instance = TaskInstanceRepository(db_session).get(chore.instance.id)
        assert instance is not None
        assert instance.status == "pending"
        assert instance.scheduled_time is None
        assert instance.status_history[-1].status == "pending"
