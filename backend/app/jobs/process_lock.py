"""IRR-2 H14: the in-process APScheduler must run in exactly one process.

Every job fires in whichever process runs the scheduler, so a second process - uvicorn
`--workers 2`, or a second container on the same data volume - would send every
reminder twice, run every scheduling pass twice and generate every occurrence twice.
Architecture-plan §7 says "single container, single process"; this is what enforces it.

The guard is an exclusive, non-blocking `flock` on a file beside the database. The OS
drops it when the holding process exits, however it exits, so a crash never leaves a
stale lock behind to block the next start.
"""

from __future__ import annotations

import fcntl
import os
from typing import IO


class SchedulerAlreadyRunningError(RuntimeError):
    """Another process already holds the scheduler lock for this database."""


def scheduler_lock_path(database_path: str) -> str:
    root, _ = os.path.splitext(database_path)
    return f"{root}.scheduler.lock"


def acquire_scheduler_lock(lock_path: str) -> IO[str]:
    """Takes the lock, or raises `SchedulerAlreadyRunningError` without waiting. Keep the
    returned handle open for the life of the process - closing it releases the lock."""
    directory = os.path.dirname(lock_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handle = open(lock_path, "a+")  # noqa: SIM115 - held open for the process lifetime by design
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise SchedulerAlreadyRunningError(
            f"Another Tessera process is already running against this database (lock: {lock_path}). "
            "Tessera must run as a single process - do not start it with more than one worker "
            "or point two containers at the same data volume."
        ) from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def release_scheduler_lock(handle: IO[str]) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()
