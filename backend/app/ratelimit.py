"""In-memory token-bucket rate limiter and request-key derivation (workstream F).

Pure module: no FastAPI/Starlette/SQLAlchemy imports, so it is unit-testable
with a fake clock. The middleware in `app.middleware` wires it to HTTP.

Scope and limits (documented in docs/DECISIONS.md by the integrator):

* State is per process. With N API processes the effective limit is N x the
  configured rate. Good enough for abuse damping; move to Redis for a hard
  global limit.
* Memory is bounded: at most `max_keys` buckets are kept. Buckets that have
  fully refilled carry no information and are swept first; beyond that the
  least-recently-used key is evicted.
"""
from __future__ import annotations

import ipaddress
import math
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

Clock = Callable[[], float]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    remaining: int  # whole tokens left after this request
    retry_after: int  # seconds until the request would be allowed (0 when allowed)
    limit: int  # bucket capacity


class Limiter(Protocol):
    """TokenBucketLimiter here, or the Redis-backed one in app.shared_state."""

    def hit(self, key: str, cost: float = 1.0) -> Decision: ...


class _Bucket:
    __slots__ = ("tokens", "updated")

    def __init__(self, tokens: float, updated: float):
        self.tokens = tokens
        self.updated = updated


class TokenBucketLimiter:
    """Classic token bucket: `capacity` tokens, refilled at `rate_per_minute / 60` per second.

    `capacity` defaults to `rate_per_minute`, i.e. a client may burst one minute's
    worth of requests and is then throttled to the steady rate.
    """

    def __init__(
        self,
        rate_per_minute: float,
        capacity: float | None = None,
        *,
        clock: Clock = time.monotonic,
        max_keys: int = 10_000,
    ):
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be > 0")
        if max_keys < 1:
            raise ValueError("max_keys must be >= 1")
        self.rate = float(rate_per_minute) / 60.0  # tokens per second
        self.capacity = float(capacity if capacity is not None else rate_per_minute)
        if self.capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()  # LRU order: oldest first
        self._full_after = self.capacity / self.rate  # seconds for an empty bucket to refill

    def __len__(self) -> int:
        return len(self._buckets)

    def __contains__(self, key: object) -> bool:
        return key in self._buckets

    def _refill(self, b: _Bucket, now: float) -> None:
        elapsed = max(0.0, now - b.updated)  # clocks may not go backwards; guard anyway
        b.tokens = min(self.capacity, b.tokens + elapsed * self.rate)
        b.updated = now

    def _sweep_idle(self, now: float) -> None:
        # Front of the OrderedDict is least recently used. A bucket idle long enough to be
        # full is indistinguishable from a fresh one, so dropping it loses nothing.
        while self._buckets:
            key, b = next(iter(self._buckets.items()))
            if now - b.updated >= self._full_after:
                del self._buckets[key]
            else:
                break

    def hit(self, key: str, cost: float = 1.0) -> Decision:
        if cost <= 0:
            raise ValueError("cost must be > 0")
        with self._lock:
            now = self._clock()
            self._sweep_idle(now)
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(self.capacity, now)
                self._buckets[key] = b
                while len(self._buckets) > self.max_keys:
                    self._buckets.popitem(last=False)  # evict LRU
            else:
                self._refill(b, now)
                self._buckets.move_to_end(key)
            if b.tokens >= cost:
                b.tokens -= cost
                return Decision(True, int(math.floor(b.tokens)), 0, int(self.capacity))
            deficit = cost - b.tokens
            retry = max(1, int(math.ceil(deficit / self.rate)))
            return Decision(False, 0, retry, int(self.capacity))

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# ---------------------------------------------------------------- key derivation

def trusted_proxy_hops(env: Mapping[str, str] | None = None) -> int:
    """TRUST_PROXY: unset/0/false -> 0 (ignore X-Forwarded-For); true/yes -> 1; an integer -> that many hops."""
    raw = (os.environ if env is None else env).get("TRUST_PROXY", "").strip().lower()
    if raw in ("", "0", "false", "no", "off"):
        return 0
    if raw in ("1", "true", "yes", "on"):
        return 1
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _valid_ip(value: str) -> str | None:
    v = value.strip()
    if v.startswith("[") and "]" in v:  # [v6]:port
        v = v[1 : v.index("]")]
    elif v.count(":") == 1:  # v4:port
        v = v.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return None


def client_ip(peer: str | None, forwarded_for: str | None, hops: int) -> str:
    """Resolve the client IP.

    X-Forwarded-For is client-controlled except for the entries appended by our own
    proxies, so with `hops` trusted proxies we take the `hops`-th entry from the right
    (never the leftmost). Without trust, the socket peer is used.
    """
    if hops > 0 and forwarded_for:
        parts = [p for p in (x.strip() for x in forwarded_for.split(",")) if p]
        if len(parts) >= hops:
            ip = _valid_ip(parts[-hops])
            if ip:
                return ip
    return (_valid_ip(peer) if peer else None) or (peer or "unknown")


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _default_decode(token: str) -> str | None:
    from .security import decode_token  # lazy: keeps this module import-light

    return decode_token(token)


def derive_key(
    headers: Mapping[str, str],
    peer: str | None,
    *,
    hops: int = 0,
    decode: Callable[[str], str | None] | None = None,
    prefer_user: bool = True,
) -> str:
    """Rate-limit key: `user:<id>` for a valid bearer token, else `ip:<addr>`.

    `headers` must have lower-case names. An invalid/expired token falls back to the IP,
    so forged tokens can't mint fresh buckets.
    """
    if prefer_user:
        token = bearer_token(headers.get("authorization"))
        if token:
            uid = (decode or _default_decode)(token)
            if uid:
                return f"user:{uid}"
    return f"ip:{client_ip(peer, headers.get('x-forwarded-for'), hops)}"


def headers_from_asgi(raw: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    """ASGI header list -> {lower-name: value}. Repeated headers are joined with ', ' (RFC 9110)."""
    out: dict[str, str] = {}
    for k, v in raw:
        name = k.decode("latin-1").lower()
        val = v.decode("latin-1")
        out[name] = f"{out[name]}, {val}" if name in out else val
    return out
