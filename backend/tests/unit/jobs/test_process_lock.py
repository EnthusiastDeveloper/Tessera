"""IRR-2 H14: a second process must not start a second job scheduler."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.jobs.process_lock import (
    SchedulerAlreadyRunningError,
    acquire_scheduler_lock,
    release_scheduler_lock,
    scheduler_lock_path,
)


def test_lock_path_sits_beside_the_database() -> None:
    assert scheduler_lock_path("/data/tessera.db") == "/data/tessera.scheduler.lock"


def test_a_second_process_cannot_take_the_lock_while_the_first_holds_it(tmp_path: Path) -> None:
    lock_path = str(tmp_path / "tessera.scheduler.lock")
    handle = acquire_scheduler_lock(lock_path)
    try:
        other = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from app.jobs.process_lock import acquire_scheduler_lock, SchedulerAlreadyRunningError\n"
                "try:\n    acquire_scheduler_lock(sys.argv[1])\nexcept SchedulerAlreadyRunningError:\n    sys.exit(3)",
                lock_path,
            ],
            cwd=Path(__file__).resolve().parents[3],
            check=False,
        )
        assert other.returncode == 3
    finally:
        release_scheduler_lock(handle)


def test_the_lock_is_free_again_once_released(tmp_path: Path) -> None:
    lock_path = str(tmp_path / "tessera.scheduler.lock")
    release_scheduler_lock(acquire_scheduler_lock(lock_path))
    release_scheduler_lock(acquire_scheduler_lock(lock_path))


def test_the_error_says_what_to_do(tmp_path: Path) -> None:
    lock_path = str(tmp_path / "tessera.scheduler.lock")
    held = acquire_scheduler_lock(lock_path)
    try:
        # flock is per open file description, so a second open in this process conflicts too.
        with pytest.raises(SchedulerAlreadyRunningError, match="single process"):
            acquire_scheduler_lock(lock_path)
    finally:
        release_scheduler_lock(held)
