"""Auth: OIDC-shaped JWT verification (spec/11).

Two modes behind one interface so the rest of the app never branches on it:
  - dev:  backend issues + verifies HS256 tokens (no AWS) — Phase 0.
  - oidc: verify RS256 against the issuer's JWKS (AWS Cognito), audience-checked.

Swapping issuers later (Keycloak for institute SSO) touches only env, not code.
"""

from __future__ import annotations

import time
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from relearn_backend.config import get_settings

_bearer = HTTPBearer(auto_error=True)


class Principal(BaseModel):
    user_id: str  # Cognito `sub` in prod; dev user id otherwise
    email: str


# --- dev mode: issue tokens locally -----------------------------------------


def issue_dev_token(user_id: str, email: str) -> str:
    s = get_settings()
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "email": email, "iat": now, "exp": now + 7 * 24 * 3600},
        s.auth_dev_secret,
        algorithm="HS256",
    )


def _verify_dev(token: str) -> Principal:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.auth_dev_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc
    return Principal(user_id=claims["sub"], email=claims.get("email", ""))


# --- oidc mode: verify against issuer JWKS ----------------------------------


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{get_settings().oidc_issuer}/.well-known/jwks.json")


def _verify_oidc(token: str) -> Principal:
    s = get_settings()
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=s.oidc_audience or None,
            issuer=s.oidc_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}") from exc
    return Principal(user_id=claims["sub"], email=claims.get("email", ""))


async def current_principal(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Principal:
    if get_settings().auth_mode == "oidc":
        return _verify_oidc(creds.credentials)
    return _verify_dev(creds.credentials)
