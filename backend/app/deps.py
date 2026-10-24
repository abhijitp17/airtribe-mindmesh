from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

from .ai.gateway import AnthropicProvider, BudgetExceeded, Gateway, Usage
from .ai.mock import MockProvider
from .config import get_settings
from .db import get_db, release_if_idle
from .models import UsageEvent, User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


@event.listens_for(Session, "after_begin")
def _rls_scope(session, transaction, connection):
    """Defence in depth (sql/rls.sql): scope every Postgres transaction to the caller.

    App-level owner_id filters remain the primary control; RLS fails closed if one is missed.
    """
    if connection.dialect.name != "postgresql":
        return
    from .jobs import rls_system

    uid = session.info.get("user_id")
    if uid:
        connection.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": uid})
    elif rls_system.get():
        connection.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if get_settings().auth_provider == "clerk":
        return _clerk_user(creds.credentials, db)
    user_id = decode_token(creds.credentials)
    if user_id:
        db.info["user_id"] = user_id  # read by the Postgres RLS hook below
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user


def _clerk_user(token: str, db: Session) -> User:
    from .clerk import ClerkTokenError, get_verifier
    from .services.identity import IdentityError, user_for_clerk_id

    try:
        claims = get_verifier().verify(token)
    except ClerkTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from None
    try:
        user = user_for_clerk_id(db, claims["sub"])
    except IdentityError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    db.info["user_id"] = user.id
    # The lookup above ran in a transaction that began before the user was known, so the RLS
    # hook couldn't scope it. End it (commit, not rollback, which would expire `user`): the
    # request's next query starts a transaction scoped to this user.
    if db.in_transaction():
        db.commit()
    return user


_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        s = get_settings()
        if s.ai_provider == "anthropic":
            if not s.anthropic_api_key:
                raise RuntimeError("AI_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
            _provider = AnthropicProvider(s.anthropic_api_key)
        else:
            _provider = MockProvider()
    return _provider


def gateway_for(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Gateway:
    return user_gateway(user.id, db, release_during_calls=True)


def user_gateway(owner_id: str, db: Session, release_during_calls: bool = False) -> Gateway:
    """A gateway that charges the user's daily budget and records usage. Background jobs use it directly."""
    s = get_settings()

    def budget_check(requested: int) -> None:
        if s.daily_token_budget <= 0:
            return
        since = datetime.now(timezone.utc) - timedelta(days=1)
        used = db.scalar(
            select(func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0)).where(
                UsageEvent.owner_id == owner_id, UsageEvent.created_at >= since
            )
        )
        if (used or 0) + requested > s.daily_token_budget:
            raise BudgetExceeded("Daily AI usage limit reached. It resets 24 hours after your first heavy use.")

    def on_usage(u: Usage) -> None:
        db.add(UsageEvent(
            owner_id=owner_id, task=u.task, model=u.model, input_tokens=u.input_tokens,
            output_tokens=u.output_tokens, latency_ms=u.latency_ms, prompt_version=u.prompt_version,
        ))
        db.commit()

    return Gateway(_get_provider(), s.model_main, s.model_fast, budget_check=budget_check, on_usage=on_usage,
                   before_call=(lambda: release_if_idle(db)) if release_during_calls else None)
