"""Worker scale-out: parallel jobs in one process; periodic work on one leader."""
import os
import tempfile
import threading
import time

tmp = tempfile.mkdtemp()
os.environ.update({"APP_ENV": "test", "DATABASE_URL": f"sqlite:///{tmp}/t.db", "STORAGE_DIR": tmp, "AI_PROVIDER": "mock",
                   "DIGEST_EVERY_SECONDS": "0", "PURGE_EVERY_SECONDS": "0"})

from sqlalchemy import select  # noqa: E402

from app import jobs  # noqa: E402
from app.db import SessionLocal  # noqa: E402

RAN: list[str] = []
_lock = threading.Lock()


@jobs.register("test_sleep")
def _sleep(payload):
    time.sleep(0.3)
    with _lock:
        RAN.append(threading.current_thread().name)


def test_concurrency_runs_jobs_in_parallel(client):  # `client` gives a fresh database
    with SessionLocal() as db:
        for i in range(6):
            jobs.enqueue(db, "test_sleep", {"i": i})
    import worker

    start = time.monotonic()
    assert worker.main(["--once", "--concurrency", "3", "--poll", "0.05"]) == 0
    took = time.monotonic() - start
    assert len(RAN) == 6 and len(set(RAN)) > 1, RAN
    assert took < 6 * 0.3 * 0.75, f"not parallel: {took:.2f}s"
    with SessionLocal() as db:
        assert {j.status for j in db.scalars(select(jobs.Job))} == {"done"}


def test_leader_on_sqlite_is_always_this_process():
    with jobs.leader("x") as a:
        assert a is True
