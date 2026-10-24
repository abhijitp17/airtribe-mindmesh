"""One-click unsubscribe from reminder emails (RFC 8058 List-Unsubscribe-Post), no sign-in needed.

The signed token in the link identifies the user. POST is what mail apps send for one-click;
GET is the link in the email body. Both turn reminders off and are safe to repeat.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models_engagement import UserPrefs
from ..services.digests import user_from_unsubscribe_token

router = APIRouter(prefix="/email", tags=["email"])


def _turn_off(token: str, db: Session) -> None:
    user_id = user_from_unsubscribe_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This unsubscribe link isn't valid.")
    db.info["user_id"] = user_id  # scopes the RLS hook to this user (Postgres)
    prefs = db.get(UserPrefs, user_id)
    if prefs is not None and prefs.reminders:
        prefs.reminders = False
        db.commit()


@router.post("/unsubscribe", response_class=PlainTextResponse)
def unsubscribe_one_click(token: str = Query(..., max_length=200), db: Session = Depends(get_db)):
    _turn_off(token, db)
    return "Reminders are off."


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str = Query(..., max_length=200), db: Session = Depends(get_db)):
    _turn_off(token, db)
    settings_url = f"{get_settings().web_url}/settings"
    return (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Reminders off · Mindmesh</title>'
        '<body style="font-family:Avenir Next,Avenir,system-ui,sans-serif;color:#1D2321;background:#F4F7F3;'
        'max-width:32rem;margin:4rem auto;padding:0 1rem">'
        "<h1 style=\"font-weight:500\">Reminders are off</h1>"
        "<p>You won't get reminder or weekly summary emails from Mindmesh any more.</p>"
        f'<p><a href="{settings_url}" style="color:#1D2321">Turn them back on in Settings</a></p></body>'
    )
