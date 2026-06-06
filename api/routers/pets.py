import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.core.config import settings
from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.biometry import Biometric
from api.models.guardian import PetGuardian
from api.models.pet import Pet, PetFoundContact
from api.models.pet import User
from api.services.storage import upload_photo

logger = logging.getLogger(__name__)

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
    approximate_age: Optional[str] = None
    special_characteristics: Optional[str] = None


class PetIdsUpdate(BaseModel):
    rg_animal_id: Optional[str] = None
    sinpatinhas_id: Optional[str] = None
    microchip_id: Optional[str] = None


class FoundContactBody(BaseModel):
    finder_name: str
    finder_phone: str
    location_text: str


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
    logger.info("[delete_pet] pet_id=%s user_id=%s", pet_id, user_id)
    result = await db.execute(select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id)))
    pet = result.scalar_one_or_none()
    if pet is None:
        logger.warning("[delete_pet] not found — pet_id=%s user_id=%s", pet_id, user_id)
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")
    await db.delete(pet)
    await db.commit()
    logger.info("[delete_pet] ok — pet_id=%s", pet_id)


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


@router.get("/{pet_id}/public", summary="Carteirinha pública do pet (sem auth)")
async def get_pet_public(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pet).where(Pet.id == pet_id))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")
    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()
    return {
        "id": str(pet.id),
        "name": pet.name,
        "species": pet.species,
        "breed": pet.breed,
        "photo_url": pet.photo_url,
        "status": pet.status,
        "rg_animal_id": pet.rg_animal_id,
        "sinpatinhas_id": pet.sinpatinhas_id,
        "microchip_id": pet.microchip_id,
        "owner": {
            "name": owner.name,
            "is_verified": owner.is_verified,
        } if owner else None,
    }


@router.post("/{pet_id}/found-contact", summary="Reportar encontro do pet (sem auth)")
async def report_found_contact(
    pet_id: UUID,
    body: FoundContactBody,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pet).where(Pet.id == pet_id))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")

    contact = PetFoundContact(
        pet_id=pet_id,
        finder_name=body.finder_name,
        finder_phone=body.finder_phone,
        location_text=body.location_text,
    )
    db.add(contact)
    await db.commit()

    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()

    # Collect all recipients: owner + accepted guardians
    recipients: list[User] = []
    if owner:
        recipients.append(owner)

    g_result = await db.execute(
        select(PetGuardian).where(
            PetGuardian.pet_id == pet_id, PetGuardian.status == "accepted"
        )
    )
    guardian_ids = [g.guardian_id for g in g_result.scalars().all()]
    if guardian_ids:
        users_result = await db.execute(select(User).where(User.id.in_(guardian_ids)))
        recipients.extend(users_result.scalars().all())

    if settings.resend_api_key:
        for recipient in recipients:
            try:
                await _send_found_contact_email(
                    owner_email=recipient.email,
                    owner_name=recipient.name or "",
                    pet_name=pet.name,
                    finder_name=body.finder_name,
                    finder_phone=body.finder_phone,
                    location_text=body.location_text,
                )
            except Exception as e:
                logger.warning("found-contact email failed for %s: %s", recipient.email, e)

    return {"ok": True}


@router.patch("/{pet_id}", summary="Atualizar IDs de identidade do pet")
async def update_pet_ids(
    pet_id: UUID,
    body: PetIdsUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id))
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")

    if body.rg_animal_id is not None:
        pet.rg_animal_id = body.rg_animal_id or None
    if body.sinpatinhas_id is not None:
        pet.sinpatinhas_id = body.sinpatinhas_id or None
    if body.microchip_id is not None:
        pet.microchip_id = body.microchip_id or None

    await db.commit()
    await db.refresh(pet)
    has_bio = await db.scalar(select(func.count()).where(Biometric.pet_id == pet.id)) > 0
    return _serialize(pet, has_biometry=has_bio)


async def _send_found_contact_email(
    owner_email: str,
    owner_name: str,
    pet_name: str,
    finder_name: str,
    finder_phone: str,
    location_text: str,
) -> None:
    html_body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;color:#3D2314;">
      <div style="background:#C98A4B;padding:16px 20px;border-radius:12px 12px 0 0;">
        <span style="color:white;font-size:18px;font-weight:800;">🐾 billy</span>
      </div>
      <div style="background:#FAF8F5;padding:24px 20px;border-radius:0 0 12px 12px;border:1px solid #EDE5DB;border-top:none;">
        <p style="font-size:16px;font-weight:700;margin:0 0 12px;">Alguém encontrou {pet_name}!</p>
        <p style="color:#8B6F5E;margin:0 0 20px;">Olá {owner_name}, <strong>{finder_name}</strong> encontrou seu pet e entrou em contato pelo Billy.</p>
        <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
          <tr><td style="padding:8px 0;color:#8B6F5E;font-size:13px;width:100px;">Finder</td><td style="font-weight:700;">{finder_name}</td></tr>
          <tr><td style="padding:8px 0;color:#8B6F5E;font-size:13px;">Telefone</td><td style="font-weight:700;">{finder_phone}</td></tr>
          <tr><td style="padding:8px 0;color:#8B6F5E;font-size:13px;">Local</td><td style="font-weight:700;">{location_text}</td></tr>
        </table>
        <p style="color:#8B6F5E;font-size:13px;margin:0;">Entre em contato o quanto antes. — Equipe Billy 🐾</p>
      </div>
    </div>
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from_email,
                "to": [owner_email],
                "subject": f"🐾 Alguém encontrou {pet_name}!",
                "html": html_body,
            },
            timeout=10,
        )


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
        "sinpatinhas_id": pet.sinpatinhas_id,
        "microchip_id": pet.microchip_id,
        "status": pet.status,
        "photo_url": pet.photo_url,
        "source": pet.source,
        "has_biometry": has_biometry,
        "created_at": pet.created_at.isoformat(),
    }
