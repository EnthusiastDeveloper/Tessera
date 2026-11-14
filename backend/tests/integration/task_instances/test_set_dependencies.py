"""Changing an occurrence's dependencies after creation - design doc §6.1 (Rev 17).

The light-bulb case is the motivating one: "Change the flickering lights" is already on
the Timeline when the user remembers there are no spare bulbs, adds "Buy bulbs", and
makes the first wait on the second.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.repositories import NotificationRepository, TaskInstanceRepository
from app.db.schemas import Recurrence, TaskInstance, UserSettings
from app.jobs.interface import dependency_at_risk_job_key, overdue_job_key
from app.scheduling.orchestration import UNSCHEDULABLE, create_notification
from app.task_instances.service import (
    InstanceValidationError,
    complete,
    dismiss,
    extend_deadline,
    set_dependencies,
    start_progress,
)
from app.task_templates.service import TaskTemplateDraft, create_template
from tests.fixtures.jobs import RecordingJobScheduler
from tests.fixtures.scheduling import local_today


def _flexible(name: str, **overrides: object) -> TaskTemplateDraft:
    defaults: dict[str, object] = {
        "start_date": local_today(),
        "name": name,
        "type": "flexible",
        "recurrence": Recurrence(pattern="one_time", anchor="calendar"),
        "priority": "medium",
        "estimated_duration_minutes": 30,
        "deadline_offset_minutes": 60 * 24 * 5,
    }
    defaults.update(overrides)
    return TaskTemplateDraft(**defaults)  # type: ignore[arg-type]


def _fixed(name: str) -> TaskTemplateDraft:
    return TaskTemplateDraft(
        start_date=local_today() + timedelta(days=2),
        name=name,
        type="fixed",
        fixed_time_of_day="18:00",
        recurrence=Recurrence(pattern="one_time", anchor="calendar"),
        priority="medium",
        estimated_duration_minutes=60,
    )


def _make(db: Session, jobs: RecordingJobScheduler, draft: TaskTemplateDraft) -> TaskInstance:
    created = create_template(db, jobs, draft)
    db.commit()
    return created.instance


def _reload(db: Session, instance_id: str) -> TaskInstance:
    instance = TaskInstanceRepository(db).get(instance_id)
    assert instance is not None
    return instance


class TestAddingAnUnfinishedDependency:
    def test_a_scheduled_flexible_task_is_blocked_and_leaves_its_slot(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        lights = _make(db_session, jobs, _flexible("Change the flickering lights"))
        assert lights.status == "scheduled"
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs", start_date=local_today() + timedelta(days=1)))

        result = set_dependencies(db_session, jobs, lights.id, dependency_ids=(bulbs.id,))
        db_session.commit()

        assert result.status == "blocked"
        assert result.scheduled_time is None
        assert result.dependencies == (bulbs.id,)
        assert result.detached is False  # not a "this occurrence" edit (§6.1 rule 6)
        assert overdue_job_key(lights.id) in jobs.cancelled
        assert dependency_at_risk_job_key(lights.id) in jobs.scheduled_keys()
        assert _reload(db_session, lights.id).status == "blocked"

    def test_it_is_placed_again_once_the_new_dependency_is_done(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        lights = _make(db_session, jobs, _flexible("Change the flickering lights"))
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))
        set_dependencies(db_session, jobs, lights.id, dependency_ids=(bulbs.id,))
        db_session.commit()

        complete(db_session, jobs, bulbs.id)
        db_session.commit()

        assert _reload(db_session, lights.id).status in ("scheduled", "pending")

    def test_a_fixed_task_is_blocked_but_keeps_its_time(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        dinner = _make(db_session, jobs, _fixed("Dinner party"))
        assert dinner.status == "scheduled"
        shopping = _make(db_session, jobs, _flexible("Buy groceries"))

        result = set_dependencies(db_session, jobs, dinner.id, dependency_ids=(shopping.id,))
        db_session.commit()

        assert result.status == "blocked"
        assert result.scheduled_time == dinner.scheduled_time
        assert overdue_job_key(dinner.id) not in jobs.cancelled  # it still holds its slot (§6.5)
        assert dependency_at_risk_job_key(dinner.id) in jobs.scheduled_keys()

    def test_a_pending_task_flagged_unschedulable_is_blocked_and_the_flag_resolves(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        stuck = _make(db_session, jobs, _flexible("Repaint the fence"))
        repo = TaskInstanceRepository(db_session)
        repo.update(stuck.model_copy(update={"status": "pending", "scheduled_time": None}))
        create_notification(db_session, type_=UNSCHEDULABLE, instance_id=stuck.id, message="no room", now=utcnow())
        paint = _make(db_session, jobs, _flexible("Buy paint"))

        result = set_dependencies(db_session, jobs, stuck.id, dependency_ids=(paint.id,))
        db_session.commit()

        assert result.status == "blocked"
        notes = NotificationRepository(db_session).list_for_instance(stuck.id)
        assert all(n.resolved_at is not None for n in notes if n.type == UNSCHEDULABLE)

    def test_a_completed_dependency_changes_nothing(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        lights = _make(db_session, jobs, _flexible("Change the flickering lights"))
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))
        complete(db_session, jobs, bulbs.id)
        db_session.commit()

        result = set_dependencies(db_session, jobs, lights.id, dependency_ids=(bulbs.id,))

        assert result.status == "scheduled"
        assert result.scheduled_time == lights.scheduled_time
        assert result.dependencies == (bulbs.id,)


class TestRemovingDependencies:
    def test_removing_the_last_unfinished_one_unblocks_and_places_it(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))
        lights = _make(db_session, jobs, _flexible("Change the flickering lights", dependencies=(bulbs.id,)))
        assert lights.status == "blocked"

        result = set_dependencies(db_session, jobs, lights.id, dependency_ids=())
        db_session.commit()

        assert result.status in ("scheduled", "pending")
        assert result.dependencies == ()
        assert dependency_at_risk_job_key(lights.id) in jobs.cancelled

    def test_it_stays_blocked_while_another_is_unfinished(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))
        ladder = _make(db_session, jobs, _flexible("Borrow a ladder"))
        lights = _make(db_session, jobs, _flexible("Change the lights", dependencies=(bulbs.id, ladder.id)))

        result = set_dependencies(db_session, jobs, lights.id, dependency_ids=(ladder.id,))

        assert result.status == "blocked"
        assert result.dependencies == (ladder.id,)

    def test_a_fixed_task_goes_back_to_scheduled_at_its_own_time(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        shopping = _make(db_session, jobs, _flexible("Buy groceries"))
        dinner = _make(db_session, jobs, _fixed("Dinner party"))
        blocked = set_dependencies(db_session, jobs, dinner.id, dependency_ids=(shopping.id,))
        db_session.commit()

        result = set_dependencies(db_session, jobs, dinner.id, dependency_ids=())

        assert result.status == "scheduled"
        assert result.scheduled_time == blocked.scheduled_time


class TestWhatIsRefused:
    @pytest.mark.parametrize("finish", ["start", "complete", "dismiss"])
    def test_a_task_in_progress_or_finished(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler, finish: str
    ) -> None:
        task = _make(db_session, jobs, _fixed("Team sync"))
        other = _make(db_session, jobs, _flexible("Prepare slides"))
        if finish == "start":
            start_progress(db_session, task.id)
        elif finish == "complete":
            complete(db_session, jobs, task.id)
        else:
            dismiss(db_session, jobs, task.id)
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            set_dependencies(db_session, jobs, task.id, dependency_ids=(other.id,))
        assert exc_info.value.code == "invalid_field"

    def test_a_dismissed_dependency(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        lights = _make(db_session, jobs, _flexible("Change the lights"))
        skipped = _make(db_session, jobs, _flexible("Buy bulbs"))
        dismiss(db_session, jobs, skipped.id)
        db_session.commit()

        with pytest.raises(InstanceValidationError) as exc_info:
            set_dependencies(db_session, jobs, lights.id, dependency_ids=(skipped.id,))
        assert exc_info.value.code == "invalid_field"

    def test_an_unknown_dependency(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        lights = _make(db_session, jobs, _flexible("Change the lights"))
        with pytest.raises(InstanceValidationError) as exc_info:
            set_dependencies(db_session, jobs, lights.id, dependency_ids=("no-such-task",))
        assert exc_info.value.code == "invalid_field"

    def test_depending_on_itself(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        lights = _make(db_session, jobs, _flexible("Change the lights"))
        with pytest.raises(InstanceValidationError) as exc_info:
            set_dependencies(db_session, jobs, lights.id, dependency_ids=(lights.id,))
        assert exc_info.value.code == "cycle_detected"

    def test_a_cycle_through_another_task(self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler) -> None:
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))
        lights = _make(db_session, jobs, _flexible("Change the lights", dependencies=(bulbs.id,)))

        with pytest.raises(InstanceValidationError) as exc_info:
            set_dependencies(db_session, jobs, bulbs.id, dependency_ids=(lights.id,))
        assert exc_info.value.code == "cycle_detected"
        assert _reload(db_session, bulbs.id).dependencies == ()

    def test_replacing_its_own_edges_is_not_a_cycle(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        """The task's current edges are replaced, not added to, before the cycle check."""
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))
        ladder = _make(db_session, jobs, _flexible("Borrow a ladder"))
        lights = _make(db_session, jobs, _flexible("Change the lights", dependencies=(bulbs.id,)))

        result = set_dependencies(db_session, jobs, lights.id, dependency_ids=(ladder.id,))
        assert result.dependencies == (ladder.id,)


class TestMissed:
    def test_only_the_list_changes_and_extending_the_deadline_respects_it(
        self, db_session: Session, settings: UserSettings, jobs: RecordingJobScheduler
    ) -> None:
        lights = _make(db_session, jobs, _flexible("Change the lights"))
        repo = TaskInstanceRepository(db_session)
        repo.update(lights.model_copy(update={"status": "missed", "scheduled_time": None}))
        db_session.commit()
        bulbs = _make(db_session, jobs, _flexible("Buy bulbs"))

        changed = set_dependencies(db_session, jobs, lights.id, dependency_ids=(bulbs.id,))
        db_session.commit()
        assert changed.status == "missed"

        extended = extend_deadline(db_session, jobs, lights.id, new_deadline=utcnow() + timedelta(days=3))
        db_session.commit()

        assert extended.status == "blocked"  # §6.1 rule 5: back through the gate, not placed
        assert extended.scheduled_time is None
        assert dependency_at_risk_job_key(lights.id) in jobs.scheduled_keys()
