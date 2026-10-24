from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..jobs import dispatch
from ..models import User
from ..schemas import LoginIn, SignupIn, TokenOut, UserOut
from ..security import create_token, hash_password, verify_password
from ..services.account import delete_account_data
from ..services import analytics

router = APIRouter(prefix="/auth", tags=["auth"])


def local_auth_only() -> None:
    """Email + password sign-up/login exist only with AUTH_PROVIDER=local; Clerk owns them otherwise."""
    if get_settings().auth_provider != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sign in through the app's sign-in page.")


@router.post("/signup", response_model=TokenOut, status_code=201, dependencies=[Depends(local_auth_only)])
def signup(body: SignupIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(body.password), display_name=body.display_name.strip())
    db.add(user)
    db.commit()
    analytics.record(db, user, "signed_up", {"method": "password"})
    if body.report_token:
        from ..services.public_report import claim

        try:
            if claim(body.report_token, user.id, db):
                analytics.record(db, user, "gap_report_ready", {"source": "claim"})
        except Exception:  # noqa: BLE001 - never fail signup over a stale or expired report
            db.rollback()
    return TokenOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(local_auth_only)])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    # password_hash is None for accounts linked to Clerk: they can't sign in with a password here.
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    return TokenOut(token=create_token(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.delete("/me", status_code=204)
def delete_account(background: BackgroundTasks, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """FR-003: delete the account, all derived data (cascade) and stored files, then the Clerk identity.

    Our data goes first and synchronously. Removing the Clerk user is a job, so a Clerk outage is
    retried (JOB_BACKEND=db) instead of failing the request or leaving our data behind.
    """
    clerk_id = user.external_id if user.auth_provider == "clerk" else None
    delete_account_data(db, user)
    if clerk_id:
        dispatch("delete_clerk_user", {"clerk_id": clerk_id}, background, db=db, max_attempts=8)
