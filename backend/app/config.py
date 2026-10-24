"""Runtime configuration from environment variables (12-factor style)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    storage_dir: str
    jwt_secret: str
    jwt_ttl_hours: int
    cors_origins: list[str]
    ai_provider: str  # "anthropic" | "mock"
    anthropic_api_key: str | None
    model_main: str  # tutoring, grading
    model_fast: str  # question generation / extraction
    max_upload_mb: int
    max_pages: int
    daily_token_budget: int  # per user; 0 disables
    # --- slice 2 settings (owners: E retrieval, F hardening) ---
    embedder: str  # "hash" (built-in, no deps) | "none"
    ocr: str  # "off" | "tesseract" | "vision"
    job_backend: str  # "inline" (FastAPI background task) | "db" (separate worker process)
    rate_limit_per_minute: int  # per user/IP on mutating + AI endpoints; 0 disables
    redis_url: str | None  # shared rate limits + public-report cache across processes; None = in-memory
    # --- auth (P1 wave 2) ---
    auth_provider: str  # "local" (email + password, HS256 JWT; dev/tests/offline) | "clerk"
    clerk_frontend_api_url: str | None  # token issuer, e.g. https://<slug>.clerk.accounts.dev
    clerk_jwt_key: str | None  # PEM public key from the dashboard: networkless verification
    clerk_secret_key: str | None  # Backend API: look up new users, delete accounts
    clerk_authorized_parties: list[str]  # web origins allowed in the token's azp claim
    clerk_webhook_signing_secret: str | None  # whsec_...; verifies /api/webhooks/clerk
    clerk_api_url: str
    # --- email (P1 wave 4): reminders + weekly summary ---
    email_backend: str  # off | console (dev: logs the message) | smtp
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_security: str  # starttls | ssl | none
    email_from: str
    web_url: str  # links in emails
    api_public_url: str  # one-click unsubscribe target
    email_token_secret: str  # signs unsubscribe links
    reminder_hour: int  # user-local hour from which the daily reminder may go out
    weekly_hour: int  # user-local hour on Monday for the weekly summary
    # --- knowledge graph (P1) ---
    concept_extraction: bool = True  # after processing, one fast-model call lists a document's concepts
    # --- analytics and retention (P1) ---
    experiment_onboarding: str = "on"  # on (50/50) | off (control) | goal_first | upload_first
    retention_email_log_days: int = 0  # 0 = keep (legal [DECISION] pending); see services/retention.py
    retention_usage_days: int = 0
    retention_jobs_days: int = 30  # finished job rows (payloads can hold identifiers)
    retention_events_days: int = 0
    # --- learned embeddings (P2; core/dense.py) ---
    dense_embedder: str = "off"  # off | voyage | fake (tests)
    voyage_api_key: str | None = None
    dense_model: str = "voyage-3.5"
    dense_dim: int = 1024
    dense_found_threshold: float | None = None  # gate only after `python -m evals.calibrate_dense`
    push_backend: str = "off"  # off | console | expo (app/push.py)
    expo_access_token: str | None = None
    metrics_token: str | None = None  # GET /api/metrics needs "Authorization: Bearer <token>"; unset = off

    @property
    def is_dev(self) -> bool:
        return self.env in ("dev", "test")


@lru_cache
def get_settings() -> Settings:
    env = os.getenv("APP_ENV", "dev")
    auth_provider = os.getenv("AUTH_PROVIDER", "local").strip().lower()
    if auth_provider not in ("local", "clerk"):
        raise RuntimeError("AUTH_PROVIDER must be 'local' or 'clerk'.")
    secret = os.getenv("JWT_SECRET", "")
    if not secret:
        if env not in ("dev", "test") and auth_provider == "local":
            raise RuntimeError("JWT_SECRET must be set outside dev/test.")
        secret = "dev-insecure-secret-change-me"
    parties = [o.strip().rstrip("/") for o in os.getenv("CLERK_AUTHORIZED_PARTIES", "").split(",") if o.strip()]
    issuer = (os.getenv("CLERK_FRONTEND_API_URL") or "").strip().rstrip("/") or None
    jwt_key = (os.getenv("CLERK_JWT_KEY") or "").replace("\\n", "\n").strip() or None  # PEM may arrive with literal \n
    email_backend = (os.getenv("EMAIL_BACKEND") or ("console" if env in ("dev", "test") else "off")).strip().lower()
    if email_backend not in ("off", "console", "smtp"):
        raise RuntimeError("EMAIL_BACKEND must be off, console or smtp.")
    email_secret = os.getenv("EMAIL_TOKEN_SECRET") or ""
    if email_backend == "smtp" and env not in ("dev", "test") and not email_secret:
        raise RuntimeError("EMAIL_BACKEND=smtp needs EMAIL_TOKEN_SECRET outside dev/test (signs unsubscribe links).")
    if auth_provider == "clerk":
        if not issuer:
            raise RuntimeError("AUTH_PROVIDER=clerk needs CLERK_FRONTEND_API_URL (the token issuer).")
        if env not in ("dev", "test") and not parties:
            raise RuntimeError("AUTH_PROVIDER=clerk needs CLERK_AUTHORIZED_PARTIES outside dev/test (CSRF protection).")
    provider = os.getenv("AI_PROVIDER") or ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "mock")
    return Settings(
        env=env,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./mindmesh.db"),
        storage_dir=os.getenv("STORAGE_DIR", "./data/uploads"),
        jwt_secret=secret,
        jwt_ttl_hours=_int("JWT_TTL_HOURS", 24 * 7),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3300").split(",") if o.strip()],
        ai_provider=provider,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        model_main=os.getenv("ANTHROPIC_MODEL_MAIN", "claude-sonnet-4-5"),
        model_fast=os.getenv("ANTHROPIC_MODEL_FAST", "claude-haiku-4-5"),
        max_upload_mb=_int("MAX_UPLOAD_MB", 50),
        max_pages=_int("MAX_PAGES", 1000),
        daily_token_budget=_int("DAILY_TOKEN_BUDGET", 2_000_000),
        embedder=os.getenv("EMBEDDER", "hash"),
        ocr=os.getenv("OCR", "off"),
        job_backend=os.getenv("JOB_BACKEND", "inline"),
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 60 if env == "prod" else 0),
        redis_url=os.getenv("REDIS_URL") or None,
        auth_provider=auth_provider,
        clerk_frontend_api_url=issuer,
        clerk_jwt_key=jwt_key,
        clerk_secret_key=os.getenv("CLERK_SECRET_KEY") or None,
        clerk_authorized_parties=parties,
        clerk_webhook_signing_secret=os.getenv("CLERK_WEBHOOK_SIGNING_SECRET") or None,
        clerk_api_url=(os.getenv("CLERK_API_URL") or "https://api.clerk.com/v1").rstrip("/"),
        email_backend=email_backend,
        smtp_host=os.getenv("SMTP_HOST") or None,
        smtp_port=_int("SMTP_PORT", 587),
        smtp_username=os.getenv("SMTP_USERNAME") or None,
        smtp_password=os.getenv("SMTP_PASSWORD") or None,
        smtp_security=(os.getenv("SMTP_SECURITY") or "starttls").strip().lower(),
        email_from=os.getenv("EMAIL_FROM") or "Mindmesh <hello@localhost>",
        web_url=(os.getenv("WEB_URL") or "http://localhost:3300").rstrip("/"),
        api_public_url=(os.getenv("API_PUBLIC_URL") or "http://localhost:8300").rstrip("/"),
        email_token_secret=email_secret or secret,
        reminder_hour=_int("REMINDER_LOCAL_HOUR", 18),
        weekly_hour=_int("WEEKLY_SUMMARY_LOCAL_HOUR", 9),
        concept_extraction=(os.getenv("CONCEPT_EXTRACTION") or "on").strip().lower() not in ("off", "0", "false", "no"),
        experiment_onboarding=(os.getenv("EXPERIMENT_ONBOARDING") or "on").strip().lower(),
        retention_email_log_days=_int("RETENTION_EMAIL_LOG_DAYS", 0),
        retention_usage_days=_int("RETENTION_USAGE_DAYS", 0),
        retention_jobs_days=_int("RETENTION_JOBS_DAYS", 30),
        retention_events_days=_int("RETENTION_EVENTS_DAYS", 0),
        dense_embedder=(os.getenv("DENSE_EMBEDDER") or "off").strip().lower(),
        voyage_api_key=os.getenv("VOYAGE_API_KEY") or None,
        dense_model=os.getenv("DENSE_MODEL") or "voyage-3.5",
        dense_dim=_int("DENSE_DIM", 1024),
        dense_found_threshold=float(os.environ["DENSE_FOUND_THRESHOLD"]) if os.getenv("DENSE_FOUND_THRESHOLD") else None,
        metrics_token=os.getenv("METRICS_TOKEN") or None,
        push_backend=(os.getenv("PUSH_BACKEND") or "off").strip().lower(),
        expo_access_token=os.getenv("EXPO_ACCESS_TOKEN") or None,
    )
