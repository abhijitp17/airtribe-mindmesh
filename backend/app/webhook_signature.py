"""Standard Webhooks signature check (what Clerk uses, via Svix). No dependencies.

signed content = f"{id}.{timestamp}.{raw body}"; key = base64-decoded secret after "whsec_";
signature header = space-separated "v1,<base64 HMAC-SHA256>" (several during key rotation).
Clerk sends svix-id / svix-timestamp / svix-signature; the standard names are webhook-*.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections.abc import Mapping

TOLERANCE_S = 5 * 60  # reject old or future-dated deliveries (replay protection)


class InvalidSignature(Exception):
    pass


def _header(headers: Mapping[str, str], name: str) -> str:
    for prefix in ("svix-", "webhook-"):
        value = headers.get(prefix + name)
        if value:
            return value
    raise InvalidSignature(f"missing {name} header")


def verify(secret: str, headers: Mapping[str, str], body: bytes, now: float | None = None) -> None:
    msg_id, ts, sigs = _header(headers, "id"), _header(headers, "timestamp"), _header(headers, "signature")
    try:
        sent = int(ts)
    except ValueError as exc:
        raise InvalidSignature("bad timestamp") from exc
    if abs((now if now is not None else time.time()) - sent) > TOLERANCE_S:
        raise InvalidSignature("timestamp outside tolerance")
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"))
    except ValueError as exc:
        raise InvalidSignature("bad signing secret") from exc
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{sent}.".encode() + body, hashlib.sha256).digest()).decode()
    for part in sigs.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig, expected):
            return
    raise InvalidSignature("no matching signature")


def sign(secret: str, msg_id: str, timestamp: int, body: bytes) -> str:
    """The header value a sender would produce (used by tests)."""
    key = base64.b64decode(secret.removeprefix("whsec_"))
    return "v1," + base64.b64encode(hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()).decode()
