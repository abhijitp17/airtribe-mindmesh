"""Clerk session-token verification (app/clerk.py). No network: tokens are signed by a test key."""
import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.clerk import ClerkTokenError, ClerkVerifier

ISS = "https://test-app.clerk.accounts.dev"
WEB = "http://localhost:3000"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, pem.decode()


PRIVATE, PUBLIC_PEM = _keypair()
OTHER_PRIVATE, _ = _keypair()


def claims(**over):
    now = int(time.time())
    c = {"iss": ISS, "sub": "user_2abc", "sid": "sess_1", "azp": WEB, "iat": now, "nbf": now - 2,
         "exp": now + 60, "v": 2, "sts": "active"}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def token(key=PRIVATE, alg="RS256", **over):
    return jwt.encode(claims(**over), key, algorithm=alg, headers={"kid": "ins_test"})


@pytest.fixture
def verifier():
    return ClerkVerifier(ISS, [WEB], pem=PUBLIC_PEM)


def test_valid_token(verifier):
    c = verifier.verify(token())
    assert c["sub"] == "user_2abc" and c["sid"] == "sess_1"


def test_small_clock_skew_is_tolerated(verifier):
    now = int(time.time())
    verifier.verify(token(exp=now - 3, iat=now - 63, nbf=now - 63))


@pytest.mark.parametrize("why, over", [
    ("expired", {"exp": int(time.time()) - 30}),
    ("not yet valid", {"nbf": int(time.time()) + 60}),
    ("wrong issuer", {"iss": "https://evil.clerk.accounts.dev"}),
    ("other web origin", {"azp": "https://evil.example"}),
    ("no azp", {"azp": None}),
    ("no session id", {"sid": None}),
    ("no user id", {"sub": None}),
    ("pending session", {"sts": "pending"}),
])
def test_rejected_claims(verifier, why, over):
    with pytest.raises(ClerkTokenError):
        verifier.verify(token(**over))


def test_rejects_token_signed_by_another_key(verifier):
    with pytest.raises(ClerkTokenError):
        verifier.verify(token(key=OTHER_PRIVATE))


def test_rejects_alg_none(verifier):
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims())}."
    with pytest.raises(ClerkTokenError):
        verifier.verify(unsigned)


def test_rejects_hs256_signed_with_the_public_key(verifier):
    """Key-confusion attack: HMAC "signed" with the public PEM as the secret."""
    forged = jwt.encode(claims(), "x", algorithm="HS256")
    header, payload, _sig = forged.split(".")
    sig = hmac.new(PUBLIC_PEM.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    forged = f"{header}.{payload}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"
    with pytest.raises(ClerkTokenError):
        verifier.verify(forged)


@pytest.mark.parametrize("bad", ["", "garbage", "a.b.c"])
def test_rejects_malformed(verifier, bad):
    with pytest.raises(ClerkTokenError):
        verifier.verify(bad)


def test_jwks_path_used_when_no_pem():
    class FakeJWKS:
        def __init__(self):
            self.calls = 0

        def get_signing_key_from_jwt(self, _token):
            self.calls += 1
            return jwt.PyJWK.from_dict({**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(PRIVATE.public_key())),
                                        "kid": "ins_test", "alg": "RS256"})

    jwks = FakeJWKS()
    v = ClerkVerifier(ISS, [WEB], jwks_client=jwks)
    assert v.verify(token())["sub"] == "user_2abc" and jwks.calls == 1
    with pytest.raises(ClerkTokenError):
        v.verify(token(key=OTHER_PRIVATE))
