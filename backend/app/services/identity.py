"""Map a verified Clerk identity to a Mindmesh user (AUTH_PROVIDER=clerk).

users.id stays the key for owner_id, RLS, export and deletion; Clerk's user id lives
in users.external_id. A new Clerk user gets a row on their first request (one Backend
API call). An existing local account is linked only when Clerk reports the same email
as *verified*, otherwise anyone could sign up with someone else's address and inherit
their data.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..clerk import ClerkAPIError, get_api
from ..models import User


class IdentityError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def user_for_clerk_id(db: Session, clerk_id: str) -> User:
    user = db.scalar(select(User).where(User.external_id == clerk_id))
    if user is not None:
        return user
    try:
        cu = get_api().get_user(clerk_id)
    except ClerkAPIError as exc:
        raise IdentityError(503, "Sign-in is temporarily unavailable. Please try again in a moment.") from exc
    if not cu.email or not cu.email_verified:
        raise IdentityError(403, "Verify your email address to continue.")
    email = cu.email.strip().lower()

    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        if existing.external_id and existing.external_id != clerk_id:
            raise IdentityError(409, "This email is already linked to a different sign-in. Contact support to merge them.")
        existing.external_id = clerk_id
        existing.auth_provider = "clerk"
        existing.password_hash = None  # passwords now live with Clerk only
        if not existing.display_name and cu.first_name:
            existing.display_name = cu.first_name[:120]
        user = existing
    else:
        user = User(email=email, password_hash=None, auth_provider="clerk", external_id=clerk_id,
                    display_name=cu.first_name[:120])
        db.add(user)
    created = user is not existing
    try:
        db.commit()
        if created:
            from . import analytics

            db.info["user_id"] = user.id  # RLS scope for the event row (deps sets the same id next)
            analytics.record(db, user, "signed_up", {"method": "clerk"})
    except IntegrityError:  # a concurrent first request created or linked it
        db.rollback()
        user = db.scalar(select(User).where(User.external_id == clerk_id))
        if user is None:
            raise IdentityError(409, "This email is already linked to a different sign-in.") from None
    return user
