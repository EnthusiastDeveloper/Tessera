"""Unit tests for app.scheduling.generation. See design doc §9.1, Worked Examples O, P.

Pure function, no DB - builds TaskTemplate/TaskInstance domain objects directly.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.db.base import generate_id
from app.db.schemas import Recurrence, TaskInstance, TaskTemplate
from app.scheduling.generation import generate_next_instance

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


class TestExampleO:
    """Completion-anchored recurrence (§3.2, §9.1)."""

    def test_nominal_date_and_deadline_anchor_on_completed_at_not_the_stale_nominal_date(self) -> None:
        template = _template(
            recurrence=Recurrence(pattern="monthly", interval=1, anchor="completion"), deadline_offset_minutes=7200
        )
        predecessor = _instance(
            template=template,
            status="completed",
            deadline=datetime(2026, 3, 6, 0, 0, tzinfo=NY),  # nominal Sun 3/1 + 5 days
            completed_at=datetime(2026, 3, 7, 14, 20, tzinfo=NY),
        )

        result = generate_next_instance(
            template, predecessor=predecessor, now=datetime(2026, 3, 7, 14, 20, tzinfo=NY), timezone="America/New_York"
        )

        assert result.nominal_date == datetime(2026, 4, 7, 14, 20, tzinfo=NY)
        assert result.deadline == datetime(2026, 4, 12, 14, 20, tzinfo=NY)

    def test_calendar_anchor_would_have_landed_on_the_1st_regardless(self) -> None:
        """Contrast case: had anchor been "calendar", N+1 lands on the rule's own date,
        not completed_at + cadence - the whole point of the anchor field (§9.1).
        """
        template = _template(recurrence=Recurrence(pattern="monthly", interval=1, anchor="calendar"))
        predecessor = _instance(
            template=template,
            type="flexible",
            status="scheduled",
            deadline=datetime(2026, 3, 6, 0, 0, tzinfo=NY),
        )

        result = generate_next_instance(
            template, predecessor=predecessor, now=datetime(2026, 3, 7, 14, 20, tzinfo=NY), timezone="America/New_York"
        )

        assert result.nominal_date.date() == datetime(2026, 4, 1).date()


class TestExampleP:
    """Calendar-anchored recurrence with a stale predecessor (§9.1, §3.8)."""

    def test_next_occurrence_generates_regardless_of_predecessor_completion_state(self) -> None:
        template = _template(
            name="Weekly team sync",
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar"),
            deadline_offset_minutes=None,
        )
        predecessor = _instance(
            template=template,
            type="fixed",
            status="scheduled",  # never marked complete - stale, but still generates (§9.1)
            scheduled_time=datetime(2026, 3, 2, 9, 0, tzinfo=NY),
        )

        result = generate_next_instance(
            template, predecessor=predecessor, now=datetime(2026, 1, 1, tzinfo=NY), timezone="America/New_York"
        )

        assert result.scheduled_time == datetime(2026, 3, 9, 9, 0, tzinfo=NY)


class TestDetachedOverridesNeverLeak:
    """§9.1 (Rev 7): "detached is a property of an instance, not of the template" -
    generation always reads the template's current values, never a predecessor's
    "this occurrence" overrides. Stage 5's own required unit test.
    """

    def test_overridden_duration_does_not_leak_into_the_next_instance(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar"),
            estimated_duration_minutes=30,
        )
        detached_predecessor = _instance(
            template=template,
            type="fixed",
            status="scheduled",
            scheduled_time=datetime(2026, 3, 2, 9, 0, tzinfo=NY),
            estimated_duration_minutes=999,  # a "this occurrence" override, per Example L
            detached=True,
        )

        result = generate_next_instance(
            template, predecessor=detached_predecessor, now=datetime(2026, 1, 1, tzinfo=NY), timezone="America/New_York"
        )

        assert result.estimated_duration_minutes == template.estimated_duration_minutes == 30
        assert result.estimated_duration_minutes != 999

    def test_overridden_name_does_not_leak_into_the_next_instance(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar"),
            name="Weekly team sync",
        )
        detached_predecessor = _instance(
            template=template,
            type="fixed",
            status="scheduled",
            scheduled_time=datetime(2026, 3, 2, 9, 0, tzinfo=NY),
            name="Weekly team sync (moved to Zoom)",
            detached=True,
        )

        result = generate_next_instance(
            template, predecessor=detached_predecessor, now=datetime(2026, 1, 1, tzinfo=NY), timezone="America/New_York"
        )

        assert result.name == template.name == "Weekly team sync"


class TestFirstInstanceAtCreation:
    """§9.1 "The first occurrence" (Rev 10): derived from `start_date`, never from now."""

    _NOW = datetime(2026, 3, 3, 10, 0, tzinfo=NY)  # a Tuesday

    def _first(self, **overrides: object) -> datetime:
        result = generate_next_instance(_template(**overrides), predecessor=None, now=self._NOW, timezone="America/New_York")
        return result.nominal_date

    def test_one_time_starts_at_the_start_of_its_start_date(self) -> None:
        nominal = self._first(recurrence=Recurrence(pattern="one_time", anchor="calendar"), start_date=date(2026, 3, 5))
        assert nominal == datetime(2026, 3, 5, 0, 0, tzinfo=NY)

    def test_a_flexible_deadline_is_counted_from_the_start_of_the_date(self) -> None:
        template = _template(
            recurrence=Recurrence(pattern="one_time", anchor="calendar"),
            start_date=date(2026, 3, 9),  # Monday
            deadline_offset_minutes=3 * 24 * 60,
        )
        result = generate_next_instance(template, predecessor=None, now=self._NOW, timezone="America/New_York")
        assert result.deadline == datetime(2026, 3, 12, 0, 0, tzinfo=NY)  # the end of Wednesday

    def test_completion_anchor_starts_on_its_start_date_not_a_cadence_later(self) -> None:
        nominal = self._first(start_date=date(2026, 3, 3))
        assert nominal == datetime(2026, 3, 3, 0, 0, tzinfo=NY)

    def test_calendar_flexible_starts_on_the_first_date_the_rule_produces(self) -> None:
        weekly_monday = Recurrence(pattern="weekly", interval=1, day_of_week=0, anchor="calendar")
        nominal = self._first(recurrence=weekly_monday, start_date=date(2026, 3, 3))
        assert nominal == datetime(2026, 3, 9, 0, 0, tzinfo=NY)

    def test_calendar_daily_starts_on_the_start_date_itself(self) -> None:
        nominal = self._first(recurrence=Recurrence(pattern="daily", interval=1, anchor="calendar"), start_date=date(2026, 3, 3))
        assert nominal == datetime(2026, 3, 3, 0, 0, tzinfo=NY)

    def test_monthly_rolls_to_next_month_when_the_day_has_passed_and_clamps_to_month_end(self) -> None:
        monthly_31st = Recurrence(pattern="monthly", interval=1, day_of_month=31, anchor="calendar")
        assert self._first(recurrence=monthly_31st, start_date=date(2026, 3, 3)) == datetime(2026, 3, 31, 0, 0, tzinfo=NY)
        monthly_2nd = Recurrence(pattern="monthly", interval=1, day_of_month=2, anchor="calendar")
        assert self._first(recurrence=monthly_2nd, start_date=date(2026, 3, 3)) == datetime(2026, 4, 2, 0, 0, tzinfo=NY)

    def test_calendar_fixed_lands_on_its_start_date_at_its_time(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="18:00",
            deadline_offset_minutes=None,
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=1, anchor="calendar"),  # Tuesday
            start_date=date(2026, 3, 3),
        )
        result = generate_next_instance(template, predecessor=None, now=self._NOW, timezone="America/New_York")
        assert result.scheduled_time == datetime(2026, 3, 3, 18, 0, tzinfo=NY)

    def test_calendar_fixed_skips_to_the_next_date_when_todays_time_has_passed(self) -> None:
        template = _template(
            type="fixed",
            fixed_time_of_day="09:00",  # already past at 10:00
            deadline_offset_minutes=None,
            recurrence=Recurrence(pattern="weekly", interval=1, day_of_week=1, anchor="calendar"),
            start_date=date(2026, 3, 3),
        )
        result = generate_next_instance(template, predecessor=None, now=self._NOW, timezone="America/New_York")
        assert result.scheduled_time == datetime(2026, 3, 10, 9, 0, tzinfo=NY)

    def test_reanchoring_advances_the_rule_from_the_given_moment(self) -> None:
        """§3.8: a dismissed completion-anchored occurrence has no `completed_at` - the
        successor is due a cadence after the dismissal."""
        template = _template(recurrence=Recurrence(pattern="daily", interval=2, anchor="completion"), start_date=date(2026, 3, 1))
        result = generate_next_instance(
            template, predecessor=None, now=self._NOW, timezone="America/New_York", reanchor_at=self._NOW
        )
        assert result.nominal_date == datetime(2026, 3, 5, 10, 0, tzinfo=NY)
