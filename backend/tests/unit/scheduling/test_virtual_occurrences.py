"""Unit tests for `app.scheduling.generation.project_virtual_occurrences`. See design doc
§9.2 (Timeline "ghost" projections) and Example O (the completion-anchor rebase rule).

Pure function, no DB - builds TaskTemplate/TaskInstance domain objects directly, same
style as test_generation.py.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.base import generate_id
from app.db.schemas import Recurrence, TaskInstance, TaskTemplate
from app.scheduling.generation import PROJECTION_HORIZON_DAYS, project_virtual_occurrences

NY = ZoneInfo("America/New_York")


def _template(**overrides: object) -> TaskTemplate:
    now = datetime(2026, 1, 1, tzinfo=NY)
    defaults: dict[str, object] = {
        "id": generate_id(),
        "name": "Replace HVAC filters",
        "type": "flexible",
        "recurrence": Recurrence(pattern="monthly", interval=1, anchor="completion"),
        "priority": "medium",
        "estimated_duration_minutes": 30,
        "deadline_offset_minutes": 7200,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "archived": False,
    }
    defaults.update(overrides)
    return TaskTemplate(**defaults)


def _instance(*, template: TaskTemplate, **overrides: object) -> TaskInstance:
    now = datetime(2026, 1, 1, tzinfo=NY)
    defaults: dict[str, object] = {
        "id": generate_id(),
        "template_id": template.id,
        "name": template.name,
        "type": template.type,
        "priority": 2,
        "estimated_duration_minutes": template.estimated_duration_minutes,
        "status": "completed",
        "generated_at": now,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    defaults.update(overrides)
    return TaskInstance(**defaults)


class TestCalendarAnchorProjection:
    """§9.2: "project the recurrence rule forward from the last nominal occurrence date" -
    straightforward repeated advance, agrees with §9.1 by construction.
    """

    def test_projects_weekly_occurrences_from_the_latest_instances_nominal_date(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar"),  # Monday
            deadline_offset_minutes=None,
        )
        latest = _instance(
            template=template, type="fixed", status="scheduled", scheduled_time=datetime(2026, 3, 2, 9, 0, tzinfo=NY)
        )
        now = datetime(2026, 3, 3, 10, 0, tzinfo=NY)  # a Tuesday, mid-week

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: latest}, now=now, timezone="America/New_York", horizon_days=21
        )

        occurs_ats = sorted(o.occurs_at for o in occurrences)
        assert occurs_ats == [
            datetime(2026, 3, 9, 9, 0, tzinfo=NY),
            datetime(2026, 3, 16, 9, 0, tzinfo=NY),
            datetime(2026, 3, 23, 9, 0, tzinfo=NY),
        ]
        assert all(o.anchor == "calendar" for o in occurrences)

    def test_stale_predecessor_still_projects_from_its_own_nominal_date(self) -> None:
        """Design doc Example P: a never-completed calendar-anchored predecessor does not
        change the projection - only its nominal date is read, never its status.
        """
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar"),
            deadline_offset_minutes=None,
        )
        latest = _instance(
            template=template,
            type="fixed",
            status="scheduled",  # never completed - stale, per Example P
            scheduled_time=datetime(2026, 3, 9, 9, 0, tzinfo=NY),
        )
        now = datetime(2026, 3, 10, 0, 0, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: latest}, now=now, timezone="America/New_York", horizon_days=7
        )

        assert [o.occurs_at for o in occurrences] == [datetime(2026, 3, 16, 9, 0, tzinfo=NY)]


class TestCompletionAnchorProjection:
    """§9.2's completion-anchor rule and Example O's rebase branch."""

    def test_on_time_live_instance_projects_from_its_nominal_date_plus_cadence(self) -> None:
        """Example O: N+1's nominal date is 2026-04-07 14:20; if it is still in the future
        relative to `now`, the next ghost shown is 2026-05-07 14:20 (nominal + cadence),
        assuming on-time completion.
        """
        template = _template(
            recurrence=Recurrence(pattern="monthly", interval=1, anchor="completion"), deadline_offset_minutes=7200
        )
        live = _instance(
            template=template,
            status="pending",
            deadline=datetime(2026, 4, 12, 14, 20, tzinfo=NY),  # nominal 2026-04-07 14:20 + 5 days
        )
        now = datetime(2026, 4, 1, 0, 0, tzinfo=NY)  # before N+1's nominal date - not yet overdue

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: live}, now=now, timezone="America/New_York", horizon_days=40
        )

        assert [o.occurs_at for o in occurrences] == [datetime(2026, 5, 7, 14, 20, tzinfo=NY)]
        assert occurrences[0].anchor == "completion"

    def test_overdue_live_instance_rebases_to_today_plus_cadence(self) -> None:
        """Example O's closing sentence: "If N+1 is itself still incomplete on, say,
        2026-04-20, the projection rebases to `today + cadence` rather than continuing to
        draw occurrences in the past" - i.e. NOT 2026-05-07 (nominal + cadence), but
        2026-05-20 (today + cadence).
        """
        template = _template(
            recurrence=Recurrence(pattern="monthly", interval=1, anchor="completion"), deadline_offset_minutes=7200
        )
        live = _instance(
            template=template,
            status="pending",
            deadline=datetime(2026, 4, 12, 14, 20, tzinfo=NY),  # nominal 2026-04-07 14:20 - now in the past
        )
        now = datetime(2026, 4, 20, 9, 0, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: live}, now=now, timezone="America/New_York", horizon_days=40
        )

        assert [o.occurs_at for o in occurrences] == [datetime(2026, 5, 20, 9, 0, tzinfo=NY)]

    def test_no_instance_yet_projects_from_now(self) -> None:
        """Defensive fallback - every template gets an instance at creation, but a
        template with none yet must not crash the endpoint.
        """
        template = _template(
            recurrence=Recurrence(pattern="monthly", interval=1, anchor="completion"), deadline_offset_minutes=7200
        )
        now = datetime(2026, 1, 1, 9, 0, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: None}, now=now, timezone="America/New_York", horizon_days=40
        )

        assert [o.occurs_at for o in occurrences] == [datetime(2026, 2, 1, 9, 0, tzinfo=NY)]


class TestHorizonBoundary:
    def test_occurrence_exactly_at_the_horizon_is_included(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="daily", interval=PROJECTION_HORIZON_DAYS, anchor="calendar"),
            deadline_offset_minutes=None,
        )
        latest = _instance(
            template=template, type="fixed", status="scheduled", scheduled_time=datetime(2026, 3, 1, 9, 0, tzinfo=NY)
        )
        now = datetime(2026, 3, 1, 9, 0, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: latest}, now=now, timezone="America/New_York"
        )

        assert [o.occurs_at for o in occurrences] == [datetime(2026, 3, 31, 9, 0, tzinfo=NY)]

    def test_occurrence_one_day_beyond_the_horizon_is_excluded(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="daily", interval=PROJECTION_HORIZON_DAYS + 1, anchor="calendar"),
            deadline_offset_minutes=None,
        )
        latest = _instance(
            template=template, type="fixed", status="scheduled", scheduled_time=datetime(2026, 3, 1, 9, 0, tzinfo=NY)
        )
        now = datetime(2026, 3, 1, 9, 0, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: latest}, now=now, timezone="America/New_York"
        )

        assert occurrences == []


class TestExclusions:
    def test_archived_template_is_excluded(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar"),
            deadline_offset_minutes=None,
            archived=True,
        )
        latest = _instance(
            template=template, type="fixed", status="scheduled", scheduled_time=datetime(2026, 3, 2, 9, 0, tzinfo=NY)
        )
        now = datetime(2026, 3, 3, 0, 0, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: latest}, now=now, timezone="America/New_York"
        )

        assert occurrences == []

    def test_one_time_template_is_excluded(self) -> None:
        template = _template(recurrence=Recurrence(pattern="one_time", anchor="calendar"))
        latest = _instance(template=template, status="pending", deadline=datetime(2026, 1, 5, tzinfo=NY))
        now = datetime(2026, 1, 1, tzinfo=NY)

        occurrences = project_virtual_occurrences(
            [template], latest_instance_by_template={template.id: latest}, now=now, timezone="America/New_York"
        )

        assert occurrences == []
