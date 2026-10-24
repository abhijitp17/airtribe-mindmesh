"""Job worker for JOB_BACKEND=db.

    python worker.py [--poll 2.0] [--once] [--stale-minutes 15]

Claims jobs from the `jobs` table. `--concurrency N` runs N at a time in this
process; run several processes or containers for more (Postgres uses SKIP LOCKED,
so they don't collide). Periodic work (stale-job recovery, emails, retention
purge) runs on one elected leader at a time (Postgres advisory locks). SIGTERM/SIGINT finish the current job, then exit cleanly.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
import uuid
from datetime import timedelta

log = logging.getLogger("mindmesh.worker")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Mindmesh job worker")
    p.add_argument("--poll", type=float, default=float(os.getenv("WORKER_POLL_SECONDS", "2")),
                   help="seconds to sleep when the queue is empty")
    p.add_argument("--stale-minutes", type=float, default=float(os.getenv("WORKER_STALE_MINUTES", "15")),
                   help="requeue running jobs locked longer than this")
    p.add_argument("--once", action="store_true", help="drain due jobs, then exit")
    p.add_argument("--concurrency", type=int, default=int(os.getenv("WORKER_CONCURRENCY", "1")),
                   help="jobs run in parallel by this process (threads); run more processes for more")
    args = p.parse_args(argv)

    from app.observability import init_error_tracking, setup_logging

    setup_logging()
    init_error_tracking()
    from app.db import SessionLocal, init_db
    from app.jobs import leader, recover_stale, run_one
    from app.services.digests import run_due
    from app.services.retention import run_purge

    init_db()  # no-op once Alembic owns the schema; harmless with create_all
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    stop = threading.Event()

    def _stop(signum: int, _frame: object) -> None:
        log.info("received signal %s; finishing current job then exiting", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    stale_after = timedelta(minutes=args.stale_minutes)
    periodic = [  # (name, every seconds, task): run by one leader across all workers (app.jobs.leader)
        ("recover-stale", 60.0, lambda: _with_session(SessionLocal, lambda db: recover_stale(db, stale_after))),
        ("digests", float(os.getenv("DIGEST_EVERY_SECONDS", "300")), run_due),
        ("purge", float(os.getenv("PURGE_EVERY_SECONDS", "3600")), run_purge),
    ]
    last = {name: 0.0 for name, _, _ in periodic}

    def run_periodic() -> None:
        for name, every, task in periodic:
            if every <= 0 or time.monotonic() - last[name] < every:
                continue
            last[name] = time.monotonic()
            try:
                with leader(name) as lead:
                    if lead:
                        task()
            except Exception:  # noqa: BLE001 - a failed periodic task must not stop job processing
                log.exception("periodic task %s failed", name)

    def job_loop(n: int) -> None:
        wid = f"{worker_id}#{n}"
        while not stop.is_set():
            if n == 0:
                run_periodic()  # one thread per process checks the timers
            db = SessionLocal()
            try:
                job = run_one(db, wid)
            except Exception:  # noqa: BLE001 - DB hiccup: log, back off, keep running
                log.exception("worker loop error")
                db.rollback()
                stop.wait(max(args.poll, 5.0))
                continue
            finally:
                db.close()
            if job is None:
                if args.once:
                    return
                stop.wait(args.poll)  # interruptible sleep

    log.info("worker %s started (poll=%.1fs, concurrency=%d)", worker_id, args.poll, args.concurrency)
    threads = [threading.Thread(target=job_loop, args=(n,), name=f"job-{n}", daemon=True) for n in range(args.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        while t.is_alive():
            t.join(timeout=0.5)
    log.info("worker %s stopped", worker_id)
    return 0


def _with_session(factory, fn):
    db = factory()
    try:
        return fn(db)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
