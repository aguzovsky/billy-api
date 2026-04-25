from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.guardian import PetGuardian
from api.models.pet import Pet, User

router = APIRouter(prefix="/guardians", tags=["guardians"])


class InviteGuardianRequest(BaseModel):
    pet_id: str
    guardian_email: EmailStr


def _pet_dict(pet: Pet, role: str) -> dict:
    return {
        "id": str(pet.id),
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "status": pet.status,
        "role": role,
    }


@router.post("/invite", status_code=status.HTTP_201_CREATED, summary="Convidar guardião para um pet")
async def invite_guardian(
    body: InviteGuardianRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    # Verify pet ownership
    pet_result = await db.execute(
        select(Pet).where(Pet.id == UUID(body.pet_id), Pet.owner_id == UUID(user_id))
    )
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado ou não pertence a você")

    # Find guardian by email
    guardian_result = await db.execute(select(User).where(User.email == body.guardian_email))
    guardian = guardian_result.scalar_one_or_none()
    if guardian is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado. Confirme se o tutor já tem conta no Billy.")

    if str(guardian.id) == user_id:
        raise HTTPException(status_code=400, detail="Você não pode convidar a si mesmo")

    # Check if already invited/accepted
    existing = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.pet_id == UUID(body.pet_id), PetGuardian.guardian_id == guardian.id)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Este tutor já foi convidado para este pet")

    invite = PetGuardian(
        pet_id=UUID(body.pet_id),
        guardian_id=guardian.id,
        invited_by_id=UUID(user_id),
        status="pending",
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    return {
        "id": str(invite.id),
        "pet_id": str(invite.pet_id),
        "pet_name": pet.name,
        "guardian_email": body.guardian_email,
        "status": invite.status,
    }


@router.get("/invites", summary="Meus convites pendentes de guarda")
async def my_invites(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.guardian_id == UUID(user_id), PetGuardian.status == "pending")
        )
    )
    invites = result.scalars().all()

    pet_ids = [i.pet_id for i in invites]
    owner_ids = [i.invited_by_id for i in invites]

    pets_map: dict = {}
    owners_map: dict = {}

    if pet_ids:
        pets_result = await db.execute(select(Pet).where(Pet.id.in_(pet_ids)))
        pets_map = {p.id: p for p in pets_result.scalars().all()}
    if owner_ids:
        owners_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
        owners_map = {u.id: u for u in owners_result.scalars().all()}

    return [
        {
            "id": str(i.id),
            "pet_id": str(i.pet_id),
            "pet_name": pets_map.get(i.pet_id, Pet()).name,
            "pet_species": pets_map.get(i.pet_id, Pet()).species,
            "owner_name": owners_map.get(i.invited_by_id, User()).name,
            "owner_email": owners_map.get(i.invited_by_id, User()).email,
            "created_at": i.created_at.isoformat(),
        }
        for i in invites
    ]


@router.patch("/invites/{invite_id}/respond", summary="Aceitar ou recusar convite de guarda")
async def respond_invite(
    invite_id: str,
    accept: bool,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.id == UUID(invite_id), PetGuardian.guardian_id == UUID(user_id))
        )
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Convite já respondido")

    invite.status = "accepted" if accept else "declined"
    await db.commit()
    return {"status": invite.status}


@router.get("/my-pets", summary="Pets onde sou guardião (guarda compartilhada)")
async def guardian_pets(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.guardian_id == UUID(user_id), PetGuardian.status == "accepted")
        )
    )
    guardianships = result.scalars().all()

    if not guardianships:
        return []

    pet_ids = [g.pet_id for g in guardianships]
    pets_result = await db.execute(select(Pet).where(Pet.id.in_(pet_ids)))
    pets = pets_result.scalars().all()

    owner_ids = [p.owner_id for p in pets]
    owners_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
    owners_map = {u.id: u for u in owners_result.scalars().all()}

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "species": p.species,
            "breed": p.breed,
            "status": p.status,
            "owner_name": owners_map.get(p.owner_id, User()).name,
            "role": "guardian",
        }
        for p in pets
    ]


@router.delete("/invites/{invite_id}", summary="Remover guardião")
async def remove_guardian(
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).join(Pet, PetGuardian.pet_id == Pet.id).where(
            and_(PetGuardian.id == UUID(invite_id), Pet.owner_id == UUID(user_id))
        )
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Guardião não encontrado")
    await db.delete(invite)
    await db.commit()
    return {"status": "removed"}
