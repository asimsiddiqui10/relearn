"""Dev auth: email/password signup + login issuing local JWTs.

Phase 0 only — in prod, Cognito owns signup/login/reset and the frontend talks
to it directly via OIDC; the backend just verifies tokens (app/auth.py oidc mode).
"""

from __future__ import annotations

import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import Space, SpaceMember, User

from relearn_backend.auth import Principal, current_principal, issue_dev_token
from relearn_backend.config import get_settings
from relearn_backend.db import get_session
from relearn_backend.schemas import LoginRequest, SignupRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _check(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


async def _bootstrap_personal_space(session: AsyncSession, user: User) -> None:
    """Every user gets a personal space on first signup (spec/08 Phase 0)."""
    space = Space(owner_user_id=user.id, name="My Space", description="Personal workspace")
    session.add(space)
    await session.flush()
    session.add(SpaceMember(space_id=space.id, user_id=user.id, role="owner"))


@router.post("/signup", response_model=TokenResponse)
async def signup(body: SignupRequest, session: AsyncSession = Depends(get_session)):
    if get_settings().auth_mode != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "signup handled by the identity provider")
    existing = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered")
    user = User(
        id=f"dev_{uuid.uuid4().hex}",
        email=body.email,
        name=body.name,
        password_hash=_hash(body.password),
    )
    session.add(user)
    await session.flush()
    await _bootstrap_personal_space(session, user)
    await session.commit()
    return TokenResponse(
        access_token=issue_dev_token(user.id, user.email), user_id=user.id, email=user.email
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    if get_settings().auth_mode != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "login handled by the identity provider")
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or not user.password_hash or not _check(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return TokenResponse(
        access_token=issue_dev_token(user.id, user.email), user_id=user.id, email=user.email
    )


@router.get("/me", response_model=TokenResponse)
async def me(principal: Principal = Depends(current_principal)):
    # echoes identity; token omitted intentionally (client already holds it)
    return TokenResponse(access_token="", user_id=principal.user_id, email=principal.email)
