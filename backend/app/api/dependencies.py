"""Request-scoped FastAPI dependencies shared across route modules."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs.interface import JobScheduler, get_job_scheduler
from app.jobs.transactional import TransactionalJobScheduler

#: The request's DB session. Function-scoped on purpose: FastAPI's default ("request")
#: scope runs a yield dependency's teardown - here, `session_scope()`'s commit - *after*
#: the response has been sent. A client could then act on a response before its data was
#: committed (log in, then have the very next request find no session and get
#: `session_expired`), and a commit that failed would already have been reported as a
#: success. Function scope commits before the response goes out.
#: Every route takes its session through this one object, which also keeps FastAPI's
#: per-request cache handing the route and `get_request_job_scheduler` the same session.
DB_SESSION = Depends(get_db, scope="function")


def get_request_job_scheduler(db: Session = DB_SESSION) -> JobScheduler:
    """The process-wide scheduler, bound to this request's DB transaction: job changes
    apply only if the request's writes commit (see `app.jobs.transactional`). FastAPI
    caches `get_db` per request, so this is the same session the route receives.
    """
    return TransactionalJobScheduler(get_job_scheduler(), db)


__all__ = ["DB_SESSION", "get_request_job_scheduler"]
