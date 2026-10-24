"""Rate limits and the public-report cache, shared across API processes via Redis.

With REDIS_URL unset (dev, tests, a single process) everything stays in memory, using
the pure classes in app.ratelimit and app.services.public_report. With REDIS_URL set:

* RedisTokenBucket keeps the same token-bucket semantics as TokenBucketLimiter, run as
  one atomic Lua script on Redis's own clock, so N processes share one limit.
* RedisTTLCache stores JSON values with a TTL; `pop` is GETDEL, so a report can be
  claimed exactly once even if two processes race.

If Redis stops answering, each object logs a warning and falls back to its in-memory
twin rather than failing requests: limits become per-process (as before) until Redis
is back. The client never retries, and after a failure Redis is skipped for
BREAKER_SECONDS, so an outage costs one short timeout every few seconds, not one per
request. Calls are synchronous; a local round trip is well under a millisecond.
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from .config import get_settings
from .ratelimit import Decision, TokenBucketLimiter

log = logging.getLogger("mindmesh.shared_state")

PREFIX = "mindmesh"
_WARN_EVERY_S = 60.0
BREAKER_SECONDS = 5.0

# KEYS[1] = bucket; ARGV = rate (tokens/s), capacity, cost, ttl_ms. Returns {allowed, tokens}.
_BUCKET_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local rate, cap, cost = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local b = redis.call('HMGET', KEYS[1], 'tokens', 'updated')
local tokens, updated = tonumber(b[1]), tonumber(b[2])
if tokens == nil or updated == nil then tokens = cap; updated = now end
tokens = math.min(cap, tokens + math.max(0, now - updated) * rate)
local allowed = 0
if tokens >= cost then tokens = tokens - cost; allowed = 1 end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'updated', tostring(now))
redis.call('PEXPIRE', KEYS[1], ARGV[4])
return {allowed, tostring(tokens)}
"""


class _Breaker:
    """Skips Redis for BREAKER_SECONDS after a failure; logs at most once a minute."""

    def __init__(self, what: str):
        self.what = what
        self._open_until = 0.0
        self._last_log = 0.0

    def is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def trip(self, exc: Exception) -> None:
        now = time.monotonic()
        self._open_until = now + BREAKER_SECONDS
        if now - self._last_log >= _WARN_EVERY_S:
            self._last_log = now
            log.warning("redis unavailable for %s, using per-process fallback: %s", self.what, exc)


def _redis_errors() -> tuple[type[Exception], ...]:
    import redis

    return (redis.RedisError, OSError)


class RedisTokenBucket:
    def __init__(self, client: Any, name: str, rate_per_minute: float, capacity: float | None = None):
        self.fallback = TokenBucketLimiter(rate_per_minute, capacity)
        self.rate = self.fallback.rate
        self.capacity = self.fallback.capacity
        self._client = client
        self._ns = f"{PREFIX}:rl:{name}:"
        self._ttl_ms = int(math.ceil(self.capacity / self.rate * 1000)) + 1000  # idle buckets expire once full
        self._script = client.register_script(_BUCKET_LUA)
        self._breaker = _Breaker(f"rate limit {name!r}")

    def hit(self, key: str, cost: float = 1.0) -> Decision:
        if cost <= 0:
            raise ValueError("cost must be > 0")
        if self._breaker.is_open():
            return self.fallback.hit(key, cost)
        try:
            allowed, tokens = self._script(keys=[self._ns + key], args=[self.rate, self.capacity, cost, self._ttl_ms])
        except _redis_errors() as exc:
            self._breaker.trip(exc)
            return self.fallback.hit(key, cost)
        tokens = float(tokens)
        if int(allowed):
            return Decision(True, int(math.floor(tokens)), 0, int(self.capacity))
        retry = max(1, int(math.ceil((cost - tokens) / self.rate)))
        return Decision(False, 0, retry, int(self.capacity))

    def reset(self) -> None:
        self.fallback.reset()
        _delete_prefix(self._client, self._ns)


class RedisTTLCache:
    def __init__(self, client: Any, name: str, ttl: float, fallback: Any,
                 dumps: Callable[[Any], str] = json.dumps, loads: Callable[[str], Any] = json.loads):
        self.fallback = fallback
        self._client = client
        self._ns = f"{PREFIX}:cache:{name}:"
        self._ttl_ms = int(ttl * 1000)
        self._dumps, self._loads = dumps, loads
        self._breaker = _Breaker(f"cache {name!r}")

    def put(self, key: str, value: Any) -> None:
        if not self._breaker.is_open():
            try:
                self._client.set(self._ns + key, self._dumps(value), px=self._ttl_ms)
                return
            except _redis_errors() as exc:
                self._breaker.trip(exc)
        self.fallback.put(key, value)

    def _read(self, key: str, op: str) -> Any | None:
        local = getattr(self.fallback, "pop" if op == "getdel" else "get")
        if self._breaker.is_open():
            return local(key)
        try:
            raw = getattr(self._client, op)(self._ns + key)
        except _redis_errors() as exc:
            self._breaker.trip(exc)
            return local(key)
        if raw is None:
            return local(key)  # may have been stored locally during an outage
        return self._loads(raw)

    def get(self, key: str) -> Any | None:
        return self._read(key, "get")

    def pop(self, key: str) -> Any | None:
        return self._read(key, "getdel")  # atomic: only one claimant wins

    def __len__(self) -> int:
        return sum(1 for _ in self._client.scan_iter(match=self._ns + "*", count=500))

    def clear(self) -> None:
        self.fallback.clear()
        _delete_prefix(self._client, self._ns)


def _delete_prefix(client: Any, prefix: str) -> None:
    try:
        keys = list(client.scan_iter(match=prefix + "*", count=500))
        if keys:
            client.delete(*keys)
    except _redis_errors() as exc:
        log.warning("redis cleanup of %s failed: %s", prefix, exc)


# ---------------------------------------------------------------- factories

def connect(url: str) -> Any:
    """A client tuned for request paths: short timeouts and no retries (the breaker handles outages)."""
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5,
                                health_check_interval=30, retry=Retry(NoBackoff(), 0))


@lru_cache
def redis_client() -> Any | None:
    url = get_settings().redis_url
    return connect(url) if url else None


def token_bucket(name: str, rate_per_minute: float, capacity: float | None = None):
    """A shared limiter when REDIS_URL is set, else the in-memory TokenBucketLimiter."""
    client = redis_client()
    if client is None:
        return TokenBucketLimiter(rate_per_minute, capacity)
    return RedisTokenBucket(client, name, rate_per_minute, capacity)


def ttl_cache(name: str, ttl: float, fallback: Any,
              dumps: Callable[[Any], str] = json.dumps, loads: Callable[[str], Any] = json.loads):
    """A shared cache when REDIS_URL is set, else `fallback` (an in-memory cache with put/get/pop/clear)."""
    client = redis_client()
    if client is None:
        return fallback
    return RedisTTLCache(client, name, ttl, fallback, dumps, loads)
