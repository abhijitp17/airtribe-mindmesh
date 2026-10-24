"""HTTP hardening middleware (workstream F): request IDs, security headers,
request-size guard and rate limiting.

Everything here is plain ASGI with no Starlette imports at module level, so
it can be unit-tested without FastAPI installed. `install_middleware` only
imports `starlette.middleware.Middleware`.

Stack order (outermost first), placed *inside* CORSMiddleware so error
responses produced here (413/429) still carry CORS headers and the browser
can read them:

    CORS -> RequestId -> Timezone -> SecurityHeaders -> BodySizeLimit -> RateLimit -> routes
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import TYPE_CHECKING, Any

from .config import get_settings
from .ratelimit import Limiter, derive_key, headers_from_asgi, trusted_proxy_hops
from . import metrics

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

log = logging.getLogger("mindmesh.http")
access_log = logging.getLogger("mindmesh.access")

# ---------------------------------------------------------------- request id

REQUEST_ID_HEADER = "x-request-id"
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_RID_RE = re.compile(r"^[A-Za-z0-9._:\-]{8,128}$")


def valid_request_id(value: str | None) -> bool:
    """Accept caller-supplied IDs only if they are short and log/header safe (no spaces, CR/LF, quotes)."""
    return bool(value) and _RID_RE.fullmatch(value) is not None  # type: ignore[arg-type]


def pick_request_id(incoming: str | None) -> str:
    return incoming if incoming is not None and valid_request_id(incoming) else uuid.uuid4().hex


def get_request_id() -> str:
    return request_id_var.get()


class RequestIdFilter(logging.Filter):
    """Adds `record.request_id` so formats can use %(request_id)s."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


_logging_configured = False


def configure_logging() -> None:
    """Make every log record carry request_id and show it in the root handlers' format.

    Idempotent. A record factory guarantees the attribute exists for every logger
    (so a format with %(request_id)s never raises), and root handlers using a
    plain format get `[rid=...]` inserted after the level name.
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True
    old_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        record.request_id = request_id_var.get()
        return record

    logging.setLogRecordFactory(factory)
    for h in logging.getLogger().handlers:
        h.addFilter(RequestIdFilter())
        fmt = getattr(h.formatter, "_fmt", None)
        if fmt and "request_id" not in fmt and type(h.formatter) is logging.Formatter:
            new_fmt = fmt.replace("%(levelname)s", "%(levelname)s [rid=%(request_id)s]", 1)
            if new_fmt == fmt:
                new_fmt = f"[rid=%(request_id)s] {fmt}"
            h.setFormatter(logging.Formatter(new_fmt, h.formatter.datefmt))  # type: ignore[union-attr]


def _get_header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers") or []:
        if k.lower() == name:
            return v.decode("latin-1")
    return None


def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: str, *, overwrite: bool) -> None:
    lname = name.lower()
    for i, (k, _) in enumerate(headers):
        if k.lower() == lname:
            if overwrite:
                headers[i] = (name, value.encode("latin-1"))
            return
    headers.append((name, value.encode("latin-1")))


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = pick_request_id(_get_header(scope, REQUEST_ID_HEADER.encode()))
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500  # if the app raises before responding

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message.get("status", 500))
                headers = list(message.get("headers") or [])
                _set_header(headers, b"x-request-id", rid, overwrite=True)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled error %s %s", scope.get("method"), scope.get("path"))
            raise
        finally:
            # One line per request. Path only: query strings can carry tokens or search text.
            metrics.record_request(str(scope.get("method")), metrics.route_label(str(scope.get("path")), status), status,
                                   time.perf_counter() - started)
            access_log.info(
                "%s %s %d", scope.get("method"), scope.get("path"), status,
                extra={"method": scope.get("method"), "path": scope.get("path"), "status": status,
                       "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            request_id_var.reset(token)


# ---------------------------------------------------------------- security headers

API_CSP = "default-src 'none'; frame-ancestors 'none'"
HSTS = "max-age=63072000; includeSubDomains"
# Swagger UI / ReDoc load scripts and styles from a CDN; leave their pages without the strict CSP.
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def is_docs_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in DOCS_PATHS)


def security_headers(path: str, *, prod: bool) -> list[tuple[str, str]]:
    h = [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Cross-Origin-Resource-Policy", "same-site"),
    ]
    if not is_docs_path(path):
        h.append(("Content-Security-Policy", API_CSP))
    if prod:
        h.append(("Strict-Transport-Security", HSTS))
    return h


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, prod: bool = False):
        self.app = app
        self.prod = prod

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(scope.get("path", ""), prod=self.prod)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                for name, value in extra:
                    _set_header(headers, name.lower().encode(), value, overwrite=False)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# ---------------------------------------------------------------- helpers

async def send_json(send: Send, status: int, body: dict[str, Any], headers: list[tuple[str, str]] | None = None) -> None:
    payload = json.dumps(body).encode()
    raw = [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]
    raw += [(k.lower().encode(), v.encode("latin-1")) for k, v in (headers or [])]
    await send({"type": "http.response.start", "status": status, "headers": raw})
    await send({"type": "http.response.body", "body": payload, "more_body": False})


# ---------------------------------------------------------------- body size

class BodySizeLimitMiddleware:
    """Reject oversized requests with 413.

    A declared Content-Length over the limit is rejected before any body is read.
    Bodies without Content-Length (chunked) are counted as they stream; once past
    the limit we answer 413 ourselves, tell the app the client disconnected, and
    drop anything the app tries to send afterwards. (Raising from receive() would
    be turned into a 400 by FastAPI's body parser.)
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        mb = self.max_bytes // (1024 * 1024)
        too_large = {"detail": f"Request body too large (limit {mb} MB)."}
        cl = _get_header(scope, b"content-length")
        if cl is not None:
            try:
                declared = int(cl)
                if declared < 0:
                    raise ValueError
            except ValueError:
                await send_json(send, 400, {"detail": "Invalid Content-Length header."})
                return
            if declared > self.max_bytes:
                await send_json(send, 413, too_large, [("Connection", "close")])
                return
            await self.app(scope, receive, send)
            return

        received = 0
        started = False
        rejected = False

        async def counting_receive() -> Message:
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    rejected = True
                    if not started:
                        await guarded_send_raw(413)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send_raw(status: int) -> None:
            nonlocal started
            started = True
            await send_json(send, status, too_large, [("Connection", "close")])

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # we already answered 413
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except Exception:
            if not rejected:
                raise  # the app's own error; ServerErrorMiddleware handles it


# ---------------------------------------------------------------- rate limit

MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
AUTH_PATHS = frozenset({"/api/auth/login", "/api/auth/signup"})


class RateLimitMiddleware:
    """Token-bucket limit on mutating requests, keyed by user (valid bearer) or IP.

    Login/signup use a separate, tighter per-IP bucket to slow credential stuffing;
    the user key is never used there (there is no authenticated user yet).
    """

    def __init__(
        self,
        app: ASGIApp,
        limiter: Limiter,
        auth_limiter: Limiter,
        proxy_hops: int = 0,
        decode: Callable[[str], str | None] | None = None,
    ):
        self.app = app
        self.limiter = limiter
        self.auth_limiter = auth_limiter
        self.proxy_hops = proxy_hops
        self.decode = decode

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "GET").upper() not in MUTATING:
            await self.app(scope, receive, send)
            return
        path = (scope.get("path") or "").rstrip("/") or "/"
        headers = headers_from_asgi(scope.get("headers") or [])
        client = scope.get("client")
        peer = client[0] if client else None
        if path in AUTH_PATHS:
            key = "auth:" + derive_key(headers, peer, hops=self.proxy_hops, prefer_user=False)
            decision = self.auth_limiter.hit(key)
        else:
            key = derive_key(headers, peer, hops=self.proxy_hops, decode=self.decode)
            decision = self.limiter.hit(key)
        if not decision.allowed:
            log.warning("rate limited %s %s key=%s", scope.get("method"), path, key.split(":", 1)[0])
            await send_json(
                send, 429,
                {"detail": f"Too many requests. Please wait {decision.retry_after} seconds and try again."},
                [("Retry-After", str(decision.retry_after)), ("X-RateLimit-Limit", str(decision.limit)),
                 ("X-RateLimit-Remaining", "0")],
            )
            return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------- user timezone

TIMEZONE_HEADER = b"x-timezone"


class TimezoneMiddleware:
    """Sets clock.user_tz from the client's X-Timezone header for the request (UTC if absent)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from .clock import parse_tz, user_tz

        token = user_tz.set(parse_tz(_get_header(scope, TIMEZONE_HEADER)))
        try:
            await self.app(scope, receive, send)
        finally:
            user_tz.reset(token)


# ---------------------------------------------------------------- install

def _auth_rate() -> int:
    import os

    try:
        return max(1, int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "10")))
    except ValueError:
        return 10


def install_middleware(app: FastAPI) -> None:
    from starlette.middleware import Middleware

    from .shared_state import token_bucket

    from .observability import setup_logging

    s = get_settings()
    setup_logging(s.env)
    configure_logging()
    # Appending to user_middleware puts these *inside* the already-added CORSMiddleware
    # (Starlette builds the stack with user_middleware[0] outermost).
    stack: list[Middleware] = [
        Middleware(RequestIdMiddleware),
        Middleware(TimezoneMiddleware),
        Middleware(SecurityHeadersMiddleware, prod=(s.env == "prod")),
        Middleware(BodySizeLimitMiddleware, max_bytes=(s.max_upload_mb + 1) * 1024 * 1024),
    ]
    if s.rate_limit_per_minute > 0:
        stack.append(Middleware(
            RateLimitMiddleware,
            limiter=token_bucket("api", s.rate_limit_per_minute),
            auth_limiter=token_bucket("auth", _auth_rate()),
            proxy_hops=trusted_proxy_hops(),
        ))
    app.user_middleware.extend(stack)
