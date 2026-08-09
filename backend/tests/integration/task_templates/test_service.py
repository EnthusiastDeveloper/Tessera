"""Integration tests for app.task_templates.service. See design doc §3.2, §3.8, §3.10;
Worked Examples A, D, L, M.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.repositories import TaskInstanceRepository, TaskTemplateRepository
from app.db.schemas import Recurrence, UserSettings
from app.task_instances.service import edit_this_occurrence
from app.task_templates.service import (
    TaskTemplateDraft,
    TemplateValidationError,
    archive_template,
    create_template,
    edit_template_this_and_future,
    get_template,
)
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
