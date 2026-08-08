"""Reuses the db_session/settings/jobs fixtures from tests/integration/conftest.py -
job-wiring tests need the identical DB+settings+recording-scheduler setup, just asserting
job-store state instead of business-logic outcomes.
"""

from tests.integration.conftest import db_session, jobs, settings

__all__ = ["db_session", "jobs", "settings"]
