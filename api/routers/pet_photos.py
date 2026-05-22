from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.pet import Pet
from api.models.pet_photo import PetPhoto
from api.services.storage import upload_photo

router = APIRouter(prefix="/pet-photos", tags=["pet-photos"])

_MAX_PHOTOS = 5


def _serialize(photo: PetPhoto) -> dict:
    return {
        "id": str(photo.id),
        "pet_id": str(photo.pet_id),
        "photo_url": photo.photo_url,
        "is_primary": photo.is_primary,
        "created_at": photo.created_at.isoformat(),
    }


async def _owned_pet(pet_id: UUID, user_id: str, db: AsyncSession) -> Pet:
    result = await db.execute(
        select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id))
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")
    return pet


@router.get("/{pet_id}", summary="Listar fotos do pet")
async def list_photos(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)
    result = await db.execute(
        select(PetPhoto)
        .where(PetPhoto.pet_id == pet_id)
        .order_by(PetPhoto.is_primary.desc(), PetPhoto.created_at.asc())
    )
    return [_serialize(p) for p in result.scalars().all()]


@router.post("/{pet_id}", status_code=status.HTTP_201_CREATED, summary="Adicionar foto ao pet")
async def add_photo(
    pet_id: UUID,
    photo: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    count = await db.scalar(
        select(func.count()).where(PetPhoto.pet_id == pet_id)
    )
    if count >= _MAX_PHOTOS:
        raise HTTPException(
            status_code=400, detail=f"Máximo de {_MAX_PHOTOS} fotos por pet"
        )

    image_bytes = await photo.read()
    photo_url = await upload_photo(image_bytes, photo.content_type or "image/jpeg")
    if photo_url is None:
        raise HTTPException(status_code=500, detail="Erro ao fazer upload da foto")

    is_primary = count == 0
    new_photo = PetPhoto(pet_id=pet_id, photo_url=photo_url, is_primary=is_primary)
    db.add(new_photo)

    if is_primary:
        await db.execute(update(Pet).where(Pet.id == pet_id).values(photo_url=photo_url))

    await db.commit()
    await db.refresh(new_photo)
    return _serialize(new_photo)


@router.patch("/{pet_id}/{photo_id}/set-primary", summary="Definir foto principal")
async def set_primary(
    pet_id: UUID,
    photo_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    result = await db.execute(
        select(PetPhoto).where(PetPhoto.id == photo_id, PetPhoto.pet_id == pet_id)
    )
    photo = result.scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    await db.execute(
        update(PetPhoto)
        .where(PetPhoto.pet_id == pet_id, PetPhoto.is_primary == True)  # noqa: E712
        .values(is_primary=False)
    )
    photo.is_primary = True
    await db.execute(update(Pet).where(Pet.id == pet_id).values(photo_url=photo.photo_url))
    await db.commit()
    return _serialize(photo)


@router.delete(
    "/{pet_id}/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remover foto do pet",
)
async def delete_photo(
    pet_id: UUID,
    photo_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    result = await db.execute(
        select(PetPhoto).where(PetPhoto.id == photo_id, PetPhoto.pet_id == pet_id)
    )
    photo = result.scalar_one_or_none()
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    was_primary = photo.is_primary
    await db.delete(photo)
    await db.flush()

    if was_primary:
        remaining = await db.execute(
            select(PetPhoto)
            .where(PetPhoto.pet_id == pet_id)
            .order_by(PetPhoto.created_at.asc())
            .limit(1)
        )
        next_photo = remaining.scalar_one_or_none()
        if next_photo:
            next_photo.is_primary = True
            await db.execute(
                update(Pet).where(Pet.id == pet_id).values(photo_url=next_photo.photo_url)
            )
        else:
            await db.execute(update(Pet).where(Pet.id == pet_id).values(photo_url=None))

    await db.commit()
