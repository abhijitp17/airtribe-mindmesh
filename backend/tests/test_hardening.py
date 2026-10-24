"""Workstream F: pure hardening logic (no FastAPI/SQLAlchemy needed).

Covers the token bucket, rate-limit key derivation, job retry backoff, request-ID
validation, security headers, the export serialiser, and the ASGI middleware
driven by hand-rolled scope/receive/send (no Starlette).
"""
import asyncio
import json
import os
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

os.environ.setdefault("APP_ENV", "test")

import pytest  # noqa: E402

from app.core.hardening import build_export, export_filename, next_run_after, row_to_dict, to_jsonable  # noqa: E402
from app.ratelimit import (  # noqa: E402
    TokenBucketLimiter, bearer_token, client_ip, derive_key, headers_from_asgi, trusted_proxy_hops,
)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


# ---------------------------------------------------------------- token bucket

def test_bucket_allows_burst_then_blocks():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, clock=clk)  # 1 token/s, capacity 60
    results = [lim.hit("k").allowed for _ in range(60)]
    assert all(results)
    d = lim.hit("k")
    assert not d.allowed and d.retry_after == 1 and d.remaining == 0 and d.limit == 60


def test_bucket_refills_over_time_and_caps_at_capacity():
    clk = FakeClock()
    lim = TokenBucketLimiter(6, clock=clk)  # 0.1 token/s, capacity 6
    for _ in range(6):
        assert lim.hit("k").allowed
    blocked = lim.hit("k")
    assert not blocked.allowed and blocked.retry_after == 10
    clk.advance(9.9)
    assert not lim.hit("k").allowed
    clk.advance(0.2)
    assert lim.hit("k").allowed
    clk.advance(10_000)  # long idle never yields more than capacity
    assert sum(lim.hit("k").allowed for _ in range(10)) == 6


def test_bucket_custom_capacity_and_remaining():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, capacity=3, clock=clk)
    assert [lim.hit("k").remaining for _ in range(3)] == [2, 1, 0]
    assert not lim.hit("k").allowed


def test_bucket_keys_are_independent():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, capacity=1, clock=clk)
    assert lim.hit("a").allowed
    assert not lim.hit("a").allowed
    assert lim.hit("b").allowed


def test_bucket_lru_eviction_bounds_memory():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, capacity=5, clock=clk, max_keys=3)
    for k in ("a", "b", "c"):
        lim.hit(k)
    lim.hit("a")  # a is now most recent; b is LRU
    lim.hit("d")
    assert len(lim) == 3 and "b" not in lim and {"a", "c", "d"} <= {k for k in ("a", "c", "d") if k in lim}


def test_bucket_sweeps_idle_full_buckets():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, capacity=60, clock=clk)  # refills fully in 60s
    lim.hit("a")
    lim.hit("b")
    clk.advance(61)
    lim.hit("c")
    assert len(lim) == 1 and "c" in lim


def test_bucket_eviction_does_not_reset_active_throttle():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, capacity=2, clock=clk, max_keys=10)
    lim.hit("a")
    lim.hit("a")
    assert not lim.hit("a").allowed
    clk.advance(0.5)  # not idle long enough to be swept
    lim.hit("z")
    assert not lim.hit("a").allowed


def test_bucket_clock_going_backwards_is_safe():
    clk = FakeClock()
    lim = TokenBucketLimiter(60, capacity=1, clock=clk)
    assert lim.hit("k").allowed
    clk.advance(-100)
    assert not lim.hit("k").allowed


def test_bucket_thread_safety():
    lim = TokenBucketLimiter(60, capacity=500, clock=FakeClock())
    allowed = []
    lock = threading.Lock()

    def worker():
        n = sum(lim.hit("k").allowed for _ in range(100))
        with lock:
            allowed.append(n)

    ts = [threading.Thread(target=worker) for _ in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(allowed) == 500


@pytest.mark.parametrize("kw", [dict(rate_per_minute=0), dict(rate_per_minute=10, max_keys=0),
                                dict(rate_per_minute=10, capacity=0.5)])
def test_bucket_rejects_bad_config(kw):
    with pytest.raises(ValueError):
        TokenBucketLimiter(**kw)


# ---------------------------------------------------------------- key derivation

def _decode(tok):
    return {"good": "u1"}.get(tok)


def test_key_prefers_valid_user_token():
    assert derive_key({"authorization": "Bearer good"}, "10.0.0.1", decode=_decode) == "user:u1"
    assert derive_key({"authorization": "bearer   good "}, "10.0.0.1", decode=_decode) == "user:u1"


def test_key_falls_back_to_ip_for_invalid_or_missing_token():
    assert derive_key({"authorization": "Bearer forged"}, "10.0.0.1", decode=_decode) == "ip:10.0.0.1"
    assert derive_key({"authorization": "Basic Zm9vOmJhcg=="}, "10.0.0.1", decode=_decode) == "ip:10.0.0.1"
    assert derive_key({}, "10.0.0.1", decode=_decode) == "ip:10.0.0.1"


def test_key_prefer_user_false_ignores_token():
    assert derive_key({"authorization": "Bearer good"}, "10.0.0.1", decode=_decode, prefer_user=False) == "ip:10.0.0.1"


def test_key_with_real_jwt_decoder():
    from app.security import create_token

    tok = create_token("abc123")
    assert derive_key({"authorization": f"Bearer {tok}"}, "1.2.3.4") == "user:abc123"
    assert derive_key({"authorization": f"Bearer {tok}x"}, "1.2.3.4") == "ip:1.2.3.4"


def test_xff_ignored_without_trust():
    h = {"x-forwarded-for": "6.6.6.6"}
    assert derive_key(h, "10.0.0.1", hops=0) == "ip:10.0.0.1"


def test_xff_uses_rightmost_trusted_hop_not_spoofable_leftmost():
    xff = "6.6.6.6, 203.0.113.7"  # client spoofed 6.6.6.6; our proxy appended the real peer
    assert client_ip("10.0.0.1", xff, 1) == "203.0.113.7"
    assert client_ip("10.0.0.1", "6.6.6.6, 203.0.113.7, 10.0.0.9", 2) == "203.0.113.7"
    assert client_ip("10.0.0.1", "203.0.113.7", 3) == "10.0.0.1"  # fewer entries than hops
    assert client_ip("10.0.0.1", "not-an-ip", 1) == "10.0.0.1"
    assert client_ip("10.0.0.1", "[2001:db8::1]:443", 1) == "2001:db8::1"
    assert client_ip("10.0.0.1", "198.51.100.2:5555", 1) == "198.51.100.2"
    assert client_ip(None, None, 0) == "unknown"
    assert client_ip("testclient", None, 0) == "testclient"


@pytest.mark.parametrize("raw,hops", [("", 0), ("0", 0), ("false", 0), ("true", 1), ("yes", 1), ("2", 2), ("junk", 0), ("-3", 0)])
def test_trust_proxy_env(raw, hops):
    assert trusted_proxy_hops({"TRUST_PROXY": raw}) == hops


def test_bearer_token_parsing_and_header_merge():
    assert bearer_token(None) is None and bearer_token("Bearer ") is None and bearer_token("Token x") is None
    h = headers_from_asgi([(b"X-Forwarded-For", b"1.1.1.1"), (b"x-forwarded-for", b"2.2.2.2"), (b"Authorization", b"Bearer t")])
    assert h == {"x-forwarded-for": "1.1.1.1, 2.2.2.2", "authorization": "Bearer t"}


# ---------------------------------------------------------------- backoff

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _delay(attempts, **kw):
    return (next_run_after(attempts, NOW, **kw) - NOW).total_seconds()


def test_backoff_exponential_monotonic_and_capped():
    delays = [_delay(n, base=10, cap=3600) for n in range(1, 15)]
    assert delays[:4] == [10, 20, 40, 80]
    assert all(a <= b for a, b in zip(delays, delays[1:]))
    assert max(delays) == 3600 and delays[-1] == 3600


def test_backoff_handles_zero_negative_and_huge_attempts():
    assert _delay(0, base=10) == 10 and _delay(-5, base=10) == 10
    assert _delay(10_000, base=10, cap=3600) == 3600


def test_backoff_jitter_bounds():
    for r in (0.0, 0.3, 0.999999):
        d = _delay(3, base=10, cap=3600, jitter=0.25, rng=lambda r=r: r)
        assert 40 * 0.75 <= d <= 40
    assert _delay(30, base=10, cap=100, jitter=0.5, rng=lambda: 0.0) == 100  # never above cap
    assert _delay(30, base=10, cap=100, jitter=0.5, rng=lambda: 1.0) == 50
    assert _delay(3, base=10, jitter=5.0, rng=lambda: 1.0) == 0  # jitter clamped to 1


# ---------------------------------------------------------------- request id + headers

from app.middleware import (  # noqa: E402
    API_CSP, BodySizeLimitMiddleware, RateLimitMiddleware, RequestIdFilter, RequestIdMiddleware,
    SecurityHeadersMiddleware, get_request_id, pick_request_id, request_id_var, security_headers,
    valid_request_id,
)


@pytest.mark.parametrize("rid,ok", [
    ("abcdef12", True), (uuid.uuid4().hex, True), (str(uuid.uuid4()), True), ("req.1:2_3-4", True),
    ("short", False), ("", False), (None, False), ("a" * 129, False), ("has space1", False),
    ("evil\r\nSet-Cookie:x", False), ('quote"id12', False), ("ünïcödé-id", False),
])
def test_request_id_validation(rid, ok):
    assert valid_request_id(rid) is ok


def test_pick_request_id_replaces_invalid():
    assert pick_request_id("client-req-0001") == "client-req-0001"
    new = pick_request_id("bad id")
    assert len(new) == 32 and valid_request_id(new)
    assert pick_request_id(None) != pick_request_id(None)


def test_request_id_logging_filter():
    import logging

    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    tok = request_id_var.set("rid-12345678")
    try:
        assert RequestIdFilter().filter(rec) and rec.request_id == "rid-12345678"
    finally:
        request_id_var.reset(tok)
    assert get_request_id() == "-"


def test_security_headers_csp_except_docs_and_hsts_only_prod():
    api = dict(security_headers("/api/documents", prod=False))
    assert api["Content-Security-Policy"] == API_CSP == "default-src 'none'; frame-ancestors 'none'"
    assert api["X-Content-Type-Options"] == "nosniff" and api["X-Frame-Options"] == "DENY"
    assert api["Referrer-Policy"] == "no-referrer" and "Strict-Transport-Security" not in api
    for p in ("/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"):
        assert "Content-Security-Policy" not in dict(security_headers(p, prod=False))
    assert "Content-Security-Policy" in dict(security_headers("/docsx", prod=False))
    assert "Strict-Transport-Security" in dict(security_headers("/api/x", prod=True))


# ---------------------------------------------------------------- ASGI middleware (hand-driven)

def _run(mw, method="GET", path="/api/x", headers=(), body=b"", client=("9.9.9.9", 1), chunks=None):
    sent = []
    msgs = [{"type": "http.request", "body": c, "more_body": i < len(chunks) - 1} for i, c in enumerate(chunks)] \
        if chunks is not None else [{"type": "http.request", "body": body, "more_body": False}]

    async def receive():
        return msgs.pop(0) if msgs else {"type": "http.disconnect"}

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": method, "path": path, "client": client,
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers]}
    asyncio.run(mw(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    hdrs = {k.decode(): v.decode() for k, v in start["headers"]}
    body_out = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], hdrs, body_out, scope


def _echo_app(seen=None):
    async def app(scope, receive, send):
        data = b""
        while True:
            m = await receive()
            if m["type"] == "http.disconnect":
                break
            data += m.get("body", b"")
            if not m.get("more_body"):
                break
        if seen is not None:
            seen.append(get_request_id())
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": data or b"ok"})
    return app


def test_request_id_middleware_echoes_valid_and_generates_otherwise():
    seen = []
    mw = RequestIdMiddleware(_echo_app(seen))
    _, h, _, scope = _run(mw, headers=[("X-Request-ID", "client-req-0001")])
    assert h["x-request-id"] == "client-req-0001" and seen[-1] == "client-req-0001"
    assert scope["state"]["request_id"] == "client-req-0001"
    _, h, _, _ = _run(mw, headers=[("X-Request-ID", "bad\tid")])
    assert valid_request_id(h["x-request-id"]) and h["x-request-id"] != "bad\tid"
    assert get_request_id() == "-"  # contextvar reset after the request


def test_security_headers_middleware_does_not_override_route_headers():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-security-policy", b"default-src 'self'")]})
        await send({"type": "http.response.body", "body": b""})

    _, h, _, _ = _run(SecurityHeadersMiddleware(app, prod=True))
    assert h["content-security-policy"] == "default-src 'self'"
    assert h["x-frame-options"] == "DENY" and "strict-transport-security" in h


def test_body_limit_rejects_declared_length_before_reading():
    reached = []

    async def app(scope, receive, send):
        reached.append(1)

    mw = BodySizeLimitMiddleware(app, max_bytes=10)
    status, h, body, _ = _run(mw, "POST", headers=[("Content-Length", "11")])
    assert status == 413 and not reached and "too large" in json.loads(body)["detail"]
    status, _, _, _ = _run(mw, "POST", headers=[("Content-Length", "abc")])
    assert status == 400
    status, _, body, _ = _run(BodySizeLimitMiddleware(_echo_app(), 10), "POST", headers=[("Content-Length", "5")], body=b"hello")
    assert status == 200 and body == b"hello"


def test_body_limit_counts_chunked_bodies():
    status, _, body, _ = _run(BodySizeLimitMiddleware(_echo_app(), 10), "POST", chunks=[b"123456", b"789012"])
    assert status == 413
    status, _, body, _ = _run(BodySizeLimitMiddleware(_echo_app(), 10), "POST", chunks=[b"12345", b"678"])
    assert status == 200 and body == b"12345678"


def test_rate_limit_middleware_mutating_only_and_separate_auth_bucket():
    clk = FakeClock()
    mw = RateLimitMiddleware(
        _echo_app(), TokenBucketLimiter(60, capacity=2, clock=clk), TokenBucketLimiter(10, capacity=1, clock=clk),
        decode=_decode,
    )
    for _ in range(5):
        assert _run(mw, "GET")[0] == 200  # reads are never limited
    assert _run(mw, "POST")[0] == 200
    assert _run(mw, "DELETE")[0] == 200
    status, h, body, _ = _run(mw, "PATCH")
    assert status == 429 and h["retry-after"] == "1" and "Too many requests" in json.loads(body)["detail"]
    # a different user from the same IP has its own bucket
    assert _run(mw, "POST", headers=[("Authorization", "Bearer good")])[0] == 200
    # auth endpoints: own per-IP bucket, token ignored
    assert _run(mw, "POST", "/api/auth/login", headers=[("Authorization", "Bearer good")])[0] == 200
    status, h, _, _ = _run(mw, "POST", "/api/auth/signup/")
    assert status == 429 and h["retry-after"] == "6"
    assert _run(mw, "POST", "/api/auth/login", client=("8.8.8.8", 1))[0] == 200


# ---------------------------------------------------------------- export serialiser

def test_to_jsonable_types():
    naive = datetime(2026, 5, 1, 12, 30)
    aware = datetime(2026, 5, 1, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    assert to_jsonable(naive) == "2026-05-01T12:30:00+00:00"
    assert to_jsonable(aware) == "2026-05-01T12:30:00+02:00"
    assert to_jsonable(date(2026, 5, 1)) == "2026-05-01"
    assert to_jsonable(b"\x00\x01\x02") == {"omitted_bytes": 3}
    assert to_jsonable({"a": [date(2026, 1, 2), (1, 2)], 3: None}) == {"a": ["2026-01-02", [1, 2]], "3": None}
    assert to_jsonable(float("nan")) is None and to_jsonable(1.5) == 1.5 and to_jsonable(True) is True
    u = uuid.uuid4()
    assert to_jsonable(u) == u.hex


def test_row_to_dict_strips_password_hash():
    row = {"id": "u1", "email": "a@b.c", "password_hash": "scrypt$...", "created_at": datetime(2026, 1, 1)}
    out = row_to_dict(row)
    assert "password_hash" not in out and out["created_at"] == "2026-01-01T00:00:00+00:00"
    assert "email" not in row_to_dict(row, exclude=["email"])


def test_build_export_shape_and_is_json_serialisable():
    gen = datetime(2026, 10, 10, 8, 0, 0, tzinfo=timezone.utc)
    user = {"id": "u1", "email": "a@b.c", "password_hash": "secret", "created_at": gen}
    tables = {
        "documents": [{"id": "d1", "owner_id": "u1", "storage_key": "u1/abc.pdf", "created_at": gen},
                      {"id": "d2", "owner_id": "u1", "storage_key": "u1/def.pdf", "created_at": gen}],
        "goals": [{"id": "g1", "owner_id": "u1", "deadline": date(2026, 12, 1), "password_hash": "x"}],
        "attempts": [],
    }
    doc = build_export(user, tables, gen)
    s = json.dumps(doc)
    assert "secret" not in s and "password_hash" not in s
    assert doc["user"]["email"] == "a@b.c" and doc["generated_at"] == "2026-10-10T08:00:00+00:00"
    assert list(doc["tables"]) == ["attempts", "documents", "goals"]
    assert doc["files"]["storage_keys"] == ["u1/abc.pdf", "u1/def.pdf"]
    assert doc["counts"] == {"attempts": 0, "documents": 2, "goals": 1}
    assert doc["tables"]["goals"][0]["deadline"] == "2026-12-01"
    assert export_filename(gen) == "mindmesh-export-20261010-080000.json"
