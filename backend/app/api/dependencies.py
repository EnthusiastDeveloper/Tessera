"""Request-scoped FastAPI dependencies shared across route modules."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.interface import JobScheduler, get_job_scheduler
from app.jobs.transactional import TransactionalJobScheduler


def get_request_job_scheduler(db: Session = Depends(get_db)) -> JobScheduler:
    """The process-wide scheduler, bound to this request's DB transaction: job changes
    apply only if the request's writes commit (see `app.jobs.transactional`). FastAPI
    caches `get_db` per request, so this is the same session the route receives.
    """
    return TransactionalJobScheduler(get_job_scheduler(), db)


__all__ = ["get_request_job_scheduler"]
