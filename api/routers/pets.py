from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.pet import Pet

router = APIRouter(prefix="/pets", tags=["pets"])


class PetCreate(BaseModel):
    name: str
    species: str  # 'dog' | 'cat'
    breed: Optional[str] = None
    rg_animal_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


@router.post("", status_code=status.HTTP_201_CREATED, summary="Cadastrar pet")
async def create_pet(
    body: PetCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    if body.species not in ("dog", "cat"):
        raise HTTPException(status_code=400, detail="species must be 'dog' or 'cat'")

    pet = Pet(
        name=body.name,
        species=body.species,
        breed=body.breed,
        owner_id=UUID(user_id),
        rg_animal_id=body.rg_animal_id,
    )
    db.add(pet)
    await db.commit()
    await db.refresh(pet)
    return _serialize(pet)


@router.get("/{pet_id}", summary="Buscar pet por ID")
async def get_pet(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(Pet).where(Pet.id == pet_id))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    return _serialize(pet)


@router.patch("/{pet_id}/status", summary="Atualizar status do pet (home/lost/found)")
async def update_pet_status(
    pet_id: UUID,
    new_status: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    if new_status not in ("home", "lost", "found"):
        raise HTTPException(status_code=400, detail="status must be home | lost | found")

    result = await db.execute(select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id)))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")

    pet.status = new_status
    await db.commit()
    return {"pet_id": str(pet_id), "status": new_status}


def _serialize(pet: Pet) -> dict:
    return {
        "id": str(pet.id),
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "owner_id": str(pet.owner_id),
        "rg_animal_id": pet.rg_animal_id,
        "status": pet.status,
        "photo_url": pet.photo_url,
        "created_at": pet.created_at.isoformat(),
    }
