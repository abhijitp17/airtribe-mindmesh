from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import TimeoutError as SATimeoutError

from .config import get_settings
from .db import init_db
from .middleware import install_middleware
from .observability import init_error_tracking, setup_logging
from .routers import account, auth, documents, email, engagement, goals, interview, learning, notes, public, webhooks


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev/test: create missing tables on boot for convenience. Elsewhere the schema is owned by
    # Alembic + sql/rls.sql (python -m app.tools.migrate, the compose `migrate` service).
    if get_settings().is_dev:
        init_db()
    yield


settings = get_settings()
setup_logging(settings.env)
init_error_tracking(settings.env)  # before the app, as Sentry recommends; no-op without SENTRY_DSN
app = FastAPI(title="Mindmesh API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(SATimeoutError)
async def _db_busy(_request, _exc):
    # Every pooled DB connection is in use: ask the client to retry instead of a bare 500.
    return JSONResponse({"detail": "We're busy right now. Please try again in a moment."}, status_code=503,
                        headers={"Retry-After": "2"})
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "X-Timezone"],
)

install_middleware(app)

for _r in (auth, documents, learning, interview, goals, account, engagement, public, webhooks, email, notes):
    app.include_router(_r.router, prefix="/api")


@app.get("/api/health")
def health():
    """Liveness: the process answers. Cheap; for container restarts."""
    return {"status": "ok", "ai_provider": settings.ai_provider}


@app.get("/api/health/ready")
def ready():
    """Readiness: dependencies answer (database, and Redis when configured). For load balancers."""
    from sqlalchemy import text

    from .db import engine
    from .shared_state import redis_client

    checks: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - reported, not raised
        checks["database"] = "unavailable"
    client = redis_client()
    if client is not None:
        try:
            client.ping()
            checks["redis"] = "ok"
        except Exception:  # noqa: BLE001
            checks["redis"] = "unavailable"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)


@app.get("/api/metrics", include_in_schema=False)
def service_metrics(request: Request):
    """Prometheus metrics (docs/slo.md). Off unless METRICS_TOKEN is set; then the bearer token is required."""
    import hmac

    from . import metrics as m

    token = get_settings().metrics_token
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(given, token):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return PlainTextResponse(m.render(), media_type="text/plain; version=0.0.4")
