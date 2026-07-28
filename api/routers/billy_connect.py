import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.pet import Pet, User
from api.models.pro import Establishment, ProClient, ProConnectInvite, ProPet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billy-connect", tags=["billy-connect"])


async def _get_invite_for_user(invite_id: UUID, user_id: str, db: AsyncSession) -> ProConnectInvite:
    result = await db.execute(select(ProConnectInvite).where(ProConnectInvite.id == invite_id))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if invite.app_user_id is None or str(invite.app_user_id) != user_id:
        raise HTTPException(status_code=403, detail="Este convite não pertence a este usuário")

    if invite.status == "pending" and invite.expires_at <= datetime.now(timezone.utc):
        invite.status = "expired"
        await db.commit()
        await db.refresh(invite)

    return invite


def _invite_out(invite: ProConnectInvite) -> dict:
    return {
        "id": str(invite.id),
        "status": invite.status,
        "created_at": invite.created_at.isoformat(),
        "expires_at": invite.expires_at.isoformat(),
        "app_pet_id": str(invite.app_pet_id) if invite.app_pet_id else None,
    }


@router.get("/invite/{invite_id}", summary="Detalhes de um convite Billy Connect")
async def get_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    invite = await _get_invite_for_user(invite_id, user_id, db)

    pro_pet_result = await db.execute(select(ProPet).where(ProPet.id == invite.pro_pet_id))
    pro_pet = pro_pet_result.scalar_one_or_none()

    establishment_result = await db.execute(
        select(Establishment).where(Establishment.id == invite.establishment_id)
    )
    establishment = establishment_result.scalar_one_or_none()

    pets_result = await db.execute(select(Pet).where(Pet.owner_id == UUID(user_id)))
    pets = pets_result.scalars().all()

    return {
        "invite": _invite_out(invite),
        "establishment_name": establishment.name if establishment else None,
        "pro_pet_name": pro_pet.name if pro_pet else None,
        "pro_pet_species": pro_pet.species if pro_pet else None,
        "pets": [
            {
                "id": str(p.id),
                "name": p.name,
                "species": p.species,
                "photo_url": p.photo_url,
            }
            for p in pets
        ],
    }


class AcceptInviteRequest(BaseModel):
    app_pet_id: str


@router.post("/invite/{invite_id}/accept", summary="Aceitar convite Billy Connect")
async def accept_invite(
    invite_id: UUID,
    body: AcceptInviteRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    invite = await _get_invite_for_user(invite_id, user_id, db)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"Convite não está mais pendente (status: {invite.status})")

    try:
        app_pet_uuid = UUID(body.app_pet_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="app_pet_id inválido")

    pet_result = await db.execute(
        select(Pet).where(Pet.id == app_pet_uuid, Pet.owner_id == UUID(user_id))
    )
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado para este usuário")

    pro_pet_result = await db.execute(select(ProPet).where(ProPet.id == invite.pro_pet_id))
    pro_pet = pro_pet_result.scalar_one_or_none()
    if pro_pet is None:
        raise HTTPException(status_code=404, detail="Pet do Pro não encontrado")

    client_result = await db.execute(select(ProClient).where(ProClient.id == invite.pro_client_id))
    client = client_result.scalar_one_or_none()

    invite.app_pet_id = app_pet_uuid
    invite.status = "confirmed"
    pro_pet.billy_pet_id = app_pet_uuid
    if client is not None:
        client.billy_user_id = UUID(user_id)
        client.billy_profile_status = "conectado"

    await db.commit()
    await db.refresh(invite)

    return _invite_out(invite)


@router.post("/invite/{invite_id}/decline", summary="Recusar convite Billy Connect")
async def decline_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    invite = await _get_invite_for_user(invite_id, user_id, db)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"Convite não está mais pendente (status: {invite.status})")

    invite.status = "declined"

    client_result = await db.execute(select(ProClient).where(ProClient.id == invite.pro_client_id))
    client = client_result.scalar_one_or_none()
    if client is not None and client.billy_profile_status == "convite_pendente":
        client.billy_profile_status = "nao_conectado"

    await db.commit()
    await db.refresh(invite)

    return _invite_out(invite)
