"""Redis-backed rate limits and cache (app/shared_state.py).

Skipped unless MINDMESH_REDIS_URL points at a Redis server, e.g.

    MINDMESH_REDIS_URL=redis://localhost:6379/15 pytest -q tests/test_redis_state.py

Each test uses its own key namespace, so a shared Redis is safe.
"""
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

URL = os.environ.get("MINDMESH_REDIS_URL", "")
if not URL:
    pytest.skip("MINDMESH_REDIS_URL not set", allow_module_level=True)

import redis  # noqa: E402

from app.services.public_report import CachedReport, TTLCache, _dump_report, _load_report  # noqa: E402
from app.shared_state import RedisTokenBucket, RedisTTLCache, connect  # noqa: E402


@pytest.fixture
def client():
    c = redis.Redis.from_url(URL, decode_responses=True)
    yield c
    c.close()


@pytest.fixture
def name():
    return f"test-{uuid.uuid4().hex[:8]}"


def test_bucket_allows_capacity_then_refuses(client, name):
    b = RedisTokenBucket(client, name, rate_per_minute=1, capacity=3)
    assert [b.hit("ip-1").allowed for _ in range(4)] == [True, True, True, False]
    refused = b.hit("ip-1")
    assert refused.retry_after >= 1 and refused.remaining == 0 and refused.limit == 3
    assert b.hit("ip-2").allowed, "keys are independent"
    b.reset()
    assert b.hit("ip-1").allowed


def test_two_processes_share_one_limit(client, name):
    # Two limiter objects = two API processes pointing at the same Redis.
    a = RedisTokenBucket(client, name, rate_per_minute=1, capacity=3)
    b = RedisTokenBucket(client, name, rate_per_minute=1, capacity=3)
    assert a.hit("k").allowed and a.hit("k").allowed
    assert b.hit("k").allowed
    assert not b.hit("k").allowed and not a.hit("k").allowed


def test_bucket_refills_over_time(client, name):
    b = RedisTokenBucket(client, name, rate_per_minute=600, capacity=1)  # 10 tokens/second
    assert b.hit("k").allowed and not b.hit("k").allowed
    time.sleep(0.15)
    assert b.hit("k").allowed


def test_bucket_is_atomic_under_concurrency(client, name):
    b = RedisTokenBucket(client, name, rate_per_minute=1, capacity=10)
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            ok = b.hit("hot").allowed
            with lock:
                results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 40 and sum(results) == 10


def test_idle_buckets_expire(client, name):
    b = RedisTokenBucket(client, name, rate_per_minute=60, capacity=2)
    b.hit("k")
    ttl_ms = client.pttl(f"mindmesh:rl:{name}:k")
    assert 0 < ttl_ms <= 3000  # refill time (2s) + 1s slack


def _report() -> CachedReport:
    return CachedReport(
        resume_text="r", resume_parsed={"bullets": ["a"]}, resume_warnings=["w"], job_text="j",
        job_parsed={"role_title": "Analyst"}, skills=[{"name": "SQL", "rank": 1}],
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


def test_report_cache_round_trips_and_claims_once_across_processes(client, name):
    a = RedisTTLCache(client, name, 60, TTLCache(), _dump_report, _load_report)
    b = RedisTTLCache(client, name, 60, TTLCache(), _dump_report, _load_report)
    r = _report()
    a.put("tok", r)
    got = b.get("tok")
    assert got.skills == r.skills and got.expires_at == r.expires_at and got.job_parsed == r.job_parsed
    assert b.pop("tok") is not None
    assert a.pop("tok") is None, "a report token is single-use"


def test_cache_entries_expire(client, name):
    c = RedisTTLCache(client, name, 0.2, TTLCache())
    c.put("k", {"v": 1})
    assert c.get("k") == {"v": 1} and len(c) == 1
    time.sleep(0.3)
    assert c.get("k") is None
    c.put("k2", 1)
    c.clear()
    assert len(c) == 0


def test_falls_back_to_memory_when_redis_is_down(name):
    dead = connect("redis://127.0.0.1:1/0")  # nothing listens on port 1
    started = time.monotonic()
    b = RedisTokenBucket(dead, name, rate_per_minute=1, capacity=2)
    assert [b.hit("k").allowed for _ in range(3)] == [True, True, False]  # in-memory twin still limits
    c = RedisTTLCache(dead, name, 60, TTLCache())
    c.put("k", "v")
    assert c.pop("k") == "v" and c.pop("k") is None
    # No retries, and the breaker skips Redis after the first failure: an outage must not
    # add seconds to every request.
    assert time.monotonic() - started < 2.0
