import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.guardian import PetGuardian
from api.models.pet import Pet
from api.models.registration import PetRegistration, VALID_REGISTRATION_TYPES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pets", tags=["pet-registrations"])


class RegistrationCreate(BaseModel):
    type: str
    type_label: Optional[str] = None
    number: str


class RegistrationUpdate(BaseModel):
    type_label: Optional[str] = None
    number: Optional[str] = None


def _serialize(r: PetRegistration) -> dict:
    return {
        "id": str(r.id),
        "pet_id": str(r.pet_id),
        "type": r.type,
        "type_label": r.type_label,
        "number": r.number,
        "created_at": r.created_at.isoformat(),
    }


async def _pet_access(pet_id: UUID, user_id: str, db: AsyncSession) -> Pet:
    result = await db.execute(select(Pet).where(Pet.id == pet_id))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")
    if str(pet.owner_id) == user_id:
        return pet
    guardian_check = await db.execute(
        select(PetGuardian).where(
            PetGuardian.pet_id == pet_id,
            PetGuardian.guardian_id == UUID(user_id),
            PetGuardian.status == "accepted",
        )
    )
    if guardian_check.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Acesso negado")
    return pet


@router.get("/{pet_id}/registrations", summary="Listar registros do pet")
async def list_registrations(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _pet_access(pet_id, user_id, db)
    result = await db.execute(
        select(PetRegistration).where(PetRegistration.pet_id == pet_id)
    )
    return [_serialize(r) for r in result.scalars().all()]


@router.post("/{pet_id}/registrations", status_code=status.HTTP_201_CREATED, summary="Criar registro do pet")
async def create_registration(
    pet_id: UUID,
    body: RegistrationCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _pet_access(pet_id, user_id, db)

    if body.type not in VALID_REGISTRATION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"type deve ser um de: {', '.join(VALID_REGISTRATION_TYPES)}",
        )
    if body.type == "OTHER" and not body.type_label:
        raise HTTPException(status_code=400, detail="type_label é obrigatório quando type é 'OTHER'")
    if not body.number.strip():
        raise HTTPException(status_code=400, detail="number não pode ser vazio")

    reg = PetRegistration(
        pet_id=pet_id,
        type=body.type,
        type_label=body.type_label,
        number=body.number.strip(),
    )
    db.add(reg)
    await db.commit()
    await db.refresh(reg)
    return _serialize(reg)


@router.patch("/{pet_id}/registrations/{reg_id}", summary="Editar registro do pet")
async def update_registration(
    pet_id: UUID,
    reg_id: UUID,
    body: RegistrationUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _pet_access(pet_id, user_id, db)

    result = await db.execute(
        select(PetRegistration).where(
            PetRegistration.id == reg_id,
            PetRegistration.pet_id == pet_id,
        )
    )
    reg = result.scalar_one_or_none()
    if reg is None:
        raise HTTPException(status_code=404, detail="Registro não encontrado")

    if body.number is not None:
        if not body.number.strip():
            raise HTTPException(status_code=400, detail="number não pode ser vazio")
        reg.number = body.number.strip()
    if body.type_label is not None:
        reg.type_label = body.type_label

    await db.commit()
    await db.refresh(reg)
    return _serialize(reg)


@router.delete("/{pet_id}/registrations/{reg_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover registro do pet")
async def delete_registration(
    pet_id: UUID,
    reg_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _pet_access(pet_id, user_id, db)

    result = await db.execute(
        select(PetRegistration).where(
            PetRegistration.id == reg_id,
            PetRegistration.pet_id == pet_id,
        )
    )
    reg = result.scalar_one_or_none()
    if reg is None:
        raise HTTPException(status_code=404, detail="Registro não encontrado")

    await db.delete(reg)
    await db.commit()
