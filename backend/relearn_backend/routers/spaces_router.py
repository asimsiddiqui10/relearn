from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from relearn_db.models import Space, SpaceMember

from relearn_backend.access import require_member
from relearn_backend.auth import Principal, current_principal
from relearn_backend.db import get_session
from relearn_backend.schemas import SpaceCreate, SpaceOut

router = APIRouter(prefix="/spaces", tags=["spaces"])


@router.get("", response_model=list[SpaceOut])
async def list_spaces(
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(Space, SpaceMember.role)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == principal.user_id)
            .order_by(Space.created_at)
        )
    ).all()
    return [
        SpaceOut(
            id=space.id,
            name=space.name,
            description=space.description,
            role=role,
            created_at=space.created_at,
        )
        for space, role in rows
    ]


@router.post("", response_model=SpaceOut, status_code=201)
async def create_space(
    body: SpaceCreate,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    space = Space(owner_user_id=principal.user_id, name=body.name, description=body.description)
    session.add(space)
    await session.flush()
    session.add(SpaceMember(space_id=space.id, user_id=principal.user_id, role="owner"))
    await session.commit()
    return SpaceOut(
        id=space.id,
        name=space.name,
        description=space.description,
        role="owner",
        created_at=space.created_at,
    )


@router.get("/{space_id}", response_model=SpaceOut)
async def get_space(
    space_id: uuid.UUID,
    principal: Principal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
):
    member = await require_member(session, space_id, principal.user_id)
    space = (await session.execute(select(Space).where(Space.id == space_id))).scalar_one()
    return SpaceOut(
        id=space.id,
        name=space.name,
        description=space.description,
        role=member.role,
        created_at=space.created_at,
    )
