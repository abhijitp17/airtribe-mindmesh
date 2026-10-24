"""Deleting an account (FR-003): every stored file, then the user row (FK cascades remove the rest).

Shared by DELETE /api/auth/me and the Clerk `user.deleted` webhook so both remove exactly the same data.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, User
from ..storage import get_storage


def delete_account_data(db: Session, user: User) -> None:
    storage = get_storage()
    for key in db.scalars(select(Document.storage_key).where(Document.owner_id == user.id)):
        storage.delete(key)
    db.delete(user)
    db.commit()
