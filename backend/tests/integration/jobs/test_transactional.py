"""`TransactionalJobScheduler` - job-store changes follow the DB transaction (issue #23)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.jobs.transactional import TransactionalJobScheduler
from tests.fixtures.jobs import RecordingJobScheduler

_AT = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)


class _FailingOnce(RecordingJobScheduler):
    def cancel(self, *, job_key: str) -> None:
        raise RuntimeError("job store unavailable")


class TestTransactionalJobScheduler:
    def test_nothing_reaches_the_real_scheduler_before_commit(self, db_session: Session) -> None:
        inner = RecordingJobScheduler()
        jobs = TransactionalJobScheduler(inner, db_session)

        jobs.schedule_at(job_key="overdue:a", run_at=_AT)
        jobs.cancel_all_for_instance(instance_id="b")

        assert inner.scheduled == []
        assert inner.cancelled_instances == []

    def test_commit_replays_every_call(self, db_session: Session) -> None:
        inner = RecordingJobScheduler()
        jobs = TransactionalJobScheduler(inner, db_session)

        jobs.schedule_at(job_key="overdue:a", run_at=_AT)
        jobs.cancel(job_key="reminder:a:15")
        jobs.cancel_all_for_instance(instance_id="b")
        jobs.schedule_interval(job_key="calendar_poll:c", minutes=15)
        db_session.commit()

        assert inner.scheduled == [("overdue:a", _AT)]
        assert inner.cancelled == ["reminder:a:15"]
        assert inner.cancelled_instances == ["b"]
        assert inner.intervals == [("calendar_poll:c", 15)]

    def test_rollback_discards_buffered_calls(self, db_session: Session) -> None:
        inner = RecordingJobScheduler()
        jobs = TransactionalJobScheduler(inner, db_session)

        db_session.execute(text("SELECT 1"))  # a real request always has an open transaction here
        jobs.cancel_all_for_instance(instance_id="a")
        db_session.rollback()
        db_session.execute(text("SELECT 1"))
        db_session.commit()

        assert inner.cancelled_instances == []

    def test_calls_replay_in_their_original_order(self, db_session: Session) -> None:
        order: list[str] = []

        class _Ordered(RecordingJobScheduler):
            def schedule_at(self, *, job_key: str, run_at: datetime) -> None:
                order.append(f"schedule {job_key}")

            def cancel_all_for_instance(self, *, instance_id: str) -> None:
                order.append(f"cancel_all {instance_id}")

        jobs = TransactionalJobScheduler(_Ordered(), db_session)
        jobs.cancel_all_for_instance(instance_id="a")
        jobs.schedule_at(job_key="overdue:a", run_at=_AT)
        db_session.commit()

        assert order == ["cancel_all a", "schedule overdue:a"]

    def test_a_failing_call_after_commit_is_logged_and_the_rest_still_apply(
        self, db_session: Session, caplog: pytest.LogCaptureFixture
    ) -> None:
        inner = _FailingOnce()
        jobs = TransactionalJobScheduler(inner, db_session)

        jobs.cancel(job_key="overdue:a")
        jobs.schedule_at(job_key="overdue:b", run_at=_AT)
        db_session.commit()

        assert inner.scheduled == [("overdue:b", _AT)]
        assert "overdue:a" in caplog.text
