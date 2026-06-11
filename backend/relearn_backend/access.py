"""Per-space access checks — enforced in SQL on every request (spec/07 security)."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import SpaceMember


async def require_member(
    session: AsyncSession, space_id: uuid.UUID, user_id: str
) -> SpaceMember:
    member = (
        await session.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id, SpaceMember.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if member is None:
        # 404 (not 403) so non-members can't probe which space ids exist
        raise HTTPException(status.HTTP_404_NOT_FOUND, "space not found")
    return member
