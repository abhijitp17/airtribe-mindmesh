"""Push notifications (P3) through the Expo push service, which forwards to Apple and Google.

PUSH_BACKEND: off (default) | console (dev: log that a push would go out, no content) | expo.
EXPO_ACCESS_TOKEN is optional (needed only if "enhanced push security" is on for the Expo project).
Messages carry counts only, like the reminder emails. Tokens Expo reports as DeviceNotRegistered are
disabled so we stop sending to uninstalled apps.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models_push import PushToken

log = logging.getLogger("mindmesh.push")
EXPO_URL = "https://exp.host/--/api/v2/push/send"
BATCH = 100
TOKEN_RE = re.compile(r"^Expo(?:nent)?PushToken\[[A-Za-z0-9_-]{10,200}\]$")


class PushError(Exception):
    pass


@dataclass
class PushMessage:
    title: str
    body: str
    data: dict = field(default_factory=dict)  # e.g. {"url": "/"}: where the app opens


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(token or ""))


def active_tokens(db: Session, owner_id: str) -> list[PushToken]:
    return list(db.scalars(select(PushToken).where(PushToken.owner_id == owner_id, PushToken.disabled_at.is_(None))))


def send(db: Session, owner_id: str, msg: PushMessage, client=None) -> int:
    """Send to the user's devices. Returns how many accepted it. Raises PushError on a transport failure."""
    backend = get_settings().push_backend
    tokens = active_tokens(db, owner_id)
    if backend == "off" or not tokens:
        return 0
    if backend == "console":
        log.info("push (console) to %d device(s)", len(tokens))
        return len(tokens)
    import httpx

    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if get_settings().expo_access_token:
        headers["Authorization"] = f"Bearer {get_settings().expo_access_token}"
    http = client or httpx.Client(timeout=10.0)
    ok = 0
    for i in range(0, len(tokens), BATCH):
        batch = tokens[i:i + BATCH]
        body = [{"to": t.token, "title": msg.title, "body": msg.body, "data": msg.data, "sound": "default"} for t in batch]
        try:
            r = http.post(EXPO_URL, json=body, headers=headers)
            r.raise_for_status()
            tickets = r.json().get("data", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise PushError(type(exc).__name__) from exc
        for t, ticket in zip(batch, tickets):
            if ticket.get("status") == "ok":
                ok += 1
            elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                t.disabled_at = datetime.now(timezone.utc)
    db.commit()
    return ok
