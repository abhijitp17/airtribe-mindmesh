"""Clerk: session-token verification and the few Backend API calls Mindmesh needs.

Verification follows Clerk's manual JWT guide (docs/DECISIONS.md #29):
  * RS256 only, signed by the instance key: CLERK_JWT_KEY (PEM, no network) or the
    Frontend API JWKS (`<issuer>/.well-known/jwks.json`, cached) when it isn't set;
  * `iss` is our Frontend API URL; `exp`/`nbf` hold (5 s leeway: tokens live ~60 s);
  * `azp` must be one of CLERK_AUTHORIZED_PARTIES (Clerk: skipping this opens CSRF);
  * `sub` (user id) and `sid` (session id) are present; `sts` is not "pending".
Anything else is a ClerkTokenError, which current_user turns into a 401.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import jwt

from .config import get_settings

LEEWAY_S = 5
_REQUIRED = ["exp", "nbf", "iat", "iss", "sub", "sid"]


class ClerkTokenError(Exception):
    pass


class ClerkAPIError(Exception):
    pass


class ClerkVerifier:
    def __init__(self, issuer: str, authorized_parties: list[str], pem: str | None = None,
                 jwks_client: Any | None = None):
        if not pem and jwks_client is None:
            jwks_client = jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)
        self.issuer = issuer
        self.parties = {p.rstrip("/") for p in authorized_parties}
        self._pem = pem
        self._jwks = jwks_client

    def verify(self, token: str) -> dict[str, Any]:
        try:
            if jwt.get_unverified_header(token).get("alg") != "RS256":
                raise ClerkTokenError("unexpected algorithm")
            key = self._pem or self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer, leeway=LEEWAY_S,
                                options={"require": _REQUIRED, "verify_aud": False})
        except ClerkTokenError:
            raise
        except (jwt.PyJWTError, ValueError) as exc:
            raise ClerkTokenError(str(exc)) from exc
        azp = str(claims.get("azp") or "").rstrip("/")
        if not azp or (self.parties and azp not in self.parties):
            raise ClerkTokenError("token not issued for an authorized party")
        if claims.get("sts") == "pending":
            raise ClerkTokenError("session pending")
        return claims


@lru_cache
def get_verifier() -> ClerkVerifier:
    s = get_settings()
    return ClerkVerifier(s.clerk_frontend_api_url or "", s.clerk_authorized_parties, pem=s.clerk_jwt_key)


# ---------------------------------------------------------------- Backend API

@dataclass(frozen=True)
class ClerkUser:
    id: str
    email: str | None  # primary address
    email_verified: bool
    first_name: str


class ClerkAPI:
    def __init__(self, secret_key: str, base_url: str, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(base_url=base_url, transport=transport, timeout=10.0,
                                    headers={"Authorization": f"Bearer {secret_key}"})

    def get_user(self, user_id: str) -> ClerkUser:
        r = self._call("GET", f"/users/{user_id}")
        data = r.json()
        primary = next((e for e in data.get("email_addresses") or []
                        if e.get("id") == data.get("primary_email_address_id")), None)
        return ClerkUser(
            id=data["id"],
            email=(primary or {}).get("email_address"),
            email_verified=((primary or {}).get("verification") or {}).get("status") == "verified",
            first_name=(data.get("first_name") or "").strip(),
        )

    def delete_user(self, user_id: str) -> None:
        r = self._client.request("DELETE", f"/users/{user_id}")
        if r.status_code not in (200, 404):  # 404: already gone, which is the goal
            raise ClerkAPIError(f"DELETE /users/{user_id} -> {r.status_code}")

    def _call(self, method: str, path: str) -> httpx.Response:
        try:
            r = self._client.request(method, path)
        except httpx.HTTPError as exc:
            raise ClerkAPIError(f"{method} {path}: {exc}") from exc
        if r.status_code != 200:
            raise ClerkAPIError(f"{method} {path} -> {r.status_code}")
        return r


_api: ClerkAPI | None = None


def get_api() -> ClerkAPI:
    global _api
    if _api is None:
        s = get_settings()
        if not s.clerk_secret_key:
            raise ClerkAPIError("CLERK_SECRET_KEY is not set")
        _api = ClerkAPI(s.clerk_secret_key, s.clerk_api_url)
    return _api


def set_api(api: ClerkAPI | None) -> None:
    """Tests swap in a client backed by a fake transport."""
    global _api
    _api = api
