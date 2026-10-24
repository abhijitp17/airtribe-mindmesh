"""Inbound webhooks. Not behind session auth: each request is verified by its signature.

POST /api/webhooks/clerk
  user.deleted  -> delete the Mindmesh account and files (the Clerk user is already gone)
  user.updated  -> follow a change of verified primary email
  anything else -> acknowledged and ignored
Handlers are idempotent (Svix delivers at least once). Off (404) until
CLERK_WEBHOOK_SIGNING_SECRET is set.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..jobs import system_context
from ..models import User
from ..services.account import delete_account_data
from ..webhook_signature import InvalidSignature, verify

log = logging.getLogger("mindmesh.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/clerk", status_code=204)
async def clerk_webhook(request: Request, db: Session = Depends(get_db)):
    secret = get_settings().clerk_webhook_signing_secret
    if not secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    body = await request.body()  # raw bytes: the signature covers them exactly
    try:
        verify(secret, request.headers, body)
    except InvalidSignature as exc:
        log.warning("clerk webhook rejected: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature") from None
    try:
        event = json.loads(body)
        kind, data = event.get("type"), event.get("data") or {}
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not a JSON event") from None
    with system_context():  # no signed-in user: run as trusted system work (RLS bypass on Postgres)
        if kind == "user.deleted" and data.get("id"):
            _user_deleted(db, data["id"])
        elif kind == "user.updated" and data.get("id"):
            _user_updated(db, data)
    return Response(status_code=204)


def _user_deleted(db: Session, clerk_id: str) -> None:
    user = db.scalar(select(User).where(User.external_id == clerk_id))
    if user is None:
        return  # never signed in to Mindmesh, or already deleted
    delete_account_data(db, user)
    log.info("deleted account for removed Clerk user")


def _user_updated(db: Session, data: dict) -> None:
    user = db.scalar(select(User).where(User.external_id == data["id"]))
    if user is None:
        return
    primary = next((e for e in data.get("email_addresses") or [] if e.get("id") == data.get("primary_email_address_id")), None)
    if not primary or (primary.get("verification") or {}).get("status") != "verified":
        return  # only follow verified addresses
    email = (primary.get("email_address") or "").strip().lower()
    if not email or email == user.email:
        return
    if db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != user.id)):
        log.warning("clerk email change skipped: address already used by another account")
        return
    user.email = email
    db.commit()
