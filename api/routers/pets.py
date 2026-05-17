from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.biometry import Biometric
from api.models.pet import Pet
from api.services.storage import upload_photo

router = APIRouter(prefix="/pets", tags=["pets"])


class PetCreate(BaseModel):
    name: str
    species: str  # 'dog' | 'cat'
    breed: Optional[str] = None
    color: Optional[str] = None
    gender: Optional[str] = None
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
        color=body.color,    # NOVO
        gender=body.gender,  # NOVO
        owner_id=UUID(user_id),
        rg_animal_id=body.rg_animal_id,
    )
    db.add(pet)
    await db.commit()
    await db.refresh(pet)
    return _serialize(pet, has_biometry=False)


@router.patch("/{pet_id}/photo", summary="Upload de foto do pet")
async def upload_pet_photo(
    pet_id: UUID,
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id)))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")

    image_bytes = await photo.read()
    filename = f"pets/{pet_id}/{photo.filename or 'photo.jpg'}"

    try:
        photo_url = await upload_photo(image_bytes, photo.content_type or "image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao fazer upload: {str(e)}")

    pet.photo_url = photo_url
    await db.commit()
    await db.refresh(pet)
    has_bio = await db.scalar(select(func.count()).where(Biometric.pet_id == pet.id)) > 0
    return _serialize(pet, has_biometry=has_bio)


@router.get("", summary="Listar meus pets")
async def list_my_pets(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(Pet).where(Pet.owner_id == UUID(user_id), Pet.source == "owner_registered")
    )
    pets = result.scalars().all()

    # Batch check: quais pets têm pelo menos 1 biométrico registrado
    pet_ids = [p.id for p in pets]
    bio_result = await db.execute(select(Biometric.pet_id).where(Biometric.pet_id.in_(pet_ids)))
    pets_with_bio = {row[0] for row in bio_result.all()}

    return [_serialize(p, has_biometry=p.id in pets_with_bio) for p in pets]


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
    has_bio = await db.scalar(select(func.count()).where(Biometric.pet_id == pet.id)) > 0
    return _serialize(pet, has_biometry=has_bio)


@router.delete("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Deletar pet")
async def delete_pet(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id)))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")
    await db.delete(pet)
    await db.commit()


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


def _serialize(pet: Pet, has_biometry: bool = False) -> dict:
    return {
        "id": str(pet.id),
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "color": pet.color,
        "gender": pet.gender,
        "owner_id": str(pet.owner_id),
        "rg_animal_id": pet.rg_animal_id,
        "status": pet.status,
        "photo_url": pet.photo_url,
        "source": pet.source,
        "has_biometry": has_biometry,
        "created_at": pet.created_at.isoformat(),
    }
