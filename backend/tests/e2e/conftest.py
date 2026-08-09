"""Reuses the db_session/jobs fixtures from tests/integration/conftest.py - e2e Worked
Example tests need the identical DB+recording-scheduler setup, just exercising a full
call chain instead of one function.
"""

from tests.integration.conftest import db_session, jobs, settings

__all__ = ["db_session", "jobs", "settings"]
