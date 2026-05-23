import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.health import HealthEvent, VALID_CATEGORIES
from api.models.pet import Pet
from api.services.storage import upload_health_proof

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class HealthEventCreate(BaseModel):
    category: str
    title: str
    date: date
    next_date: Optional[date] = None
    vet_name: Optional[str] = None
    clinic: Optional[str] = None
    notes: Optional[str] = None


class HealthEventUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    date: Optional[date] = None
    next_date: Optional[date] = None
    vet_name: Optional[str] = None
    clinic: Optional[str] = None
    notes: Optional[str] = None


def _serialize(e: HealthEvent) -> dict:
    return {
        "id": str(e.id),
        "pet_id": str(e.pet_id),
        "category": e.category,
        "title": e.title,
        "date": e.date.isoformat(),
        "next_date": e.next_date.isoformat() if e.next_date else None,
        "vet_name": e.vet_name,
        "clinic": e.clinic,
        "notes": e.notes,
        "proof_url": e.proof_url,
        "created_at": e.created_at.isoformat(),
    }


async def _owned_pet(pet_id: UUID, user_id: str, db: AsyncSession) -> Pet:
    result = await db.execute(
        select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id))
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")
    return pet


@router.get("/{pet_id}", summary="Listar eventos de saúde do pet")
async def list_events(
    pet_id: UUID,
    upcoming: bool = False,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    query = select(HealthEvent).where(HealthEvent.pet_id == pet_id)
    if upcoming:
        query = query.where(
            HealthEvent.next_date >= date.today()
        ).order_by(HealthEvent.next_date.asc())
    else:
        query = query.order_by(HealthEvent.date.desc())

    result = await db.execute(query)
    return [_serialize(e) for e in result.scalars().all()]


@router.post("/{pet_id}", status_code=status.HTTP_201_CREATED, summary="Criar evento de saúde")
async def create_event(
    pet_id: UUID,
    body: HealthEventCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    if body.category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"category must be one of: {', '.join(VALID_CATEGORIES)}",
        )

    event = HealthEvent(
        pet_id=pet_id,
        category=body.category,
        title=body.title,
        date=body.date,
        next_date=body.next_date,
        vet_name=body.vet_name,
        clinic=body.clinic,
        notes=body.notes,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return _serialize(event)


@router.patch("/{pet_id}/{event_id}", summary="Editar evento de saúde")
async def update_event(
    pet_id: UUID,
    event_id: UUID,
    body: HealthEventUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    result = await db.execute(
        select(HealthEvent).where(
            HealthEvent.id == event_id, HealthEvent.pet_id == pet_id
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Health event not found")

    if body.category is not None:
        if body.category not in VALID_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"category must be one of: {', '.join(VALID_CATEGORIES)}",
            )
        event.category = body.category
    if body.title is not None:
        event.title = body.title
    if body.date is not None:
        event.date = body.date
    if body.next_date is not None:
        event.next_date = body.next_date
    if body.vet_name is not None:
        event.vet_name = body.vet_name
    if body.clinic is not None:
        event.clinic = body.clinic
    if body.notes is not None:
        event.notes = body.notes

    await db.commit()
    await db.refresh(event)
    return _serialize(event)


@router.delete(
    "/{pet_id}/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deletar evento de saúde",
)
async def delete_event(
    pet_id: UUID,
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    result = await db.execute(
        select(HealthEvent).where(
            HealthEvent.id == event_id, HealthEvent.pet_id == pet_id
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Health event not found")

    await db.delete(event)
    await db.commit()


@router.post(
    "/{pet_id}/{event_id}/proof",
    summary="Upload de comprovante do evento de saúde",
)
async def upload_proof(
    pet_id: UUID,
    event_id: UUID,
    proof: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    await _owned_pet(pet_id, user_id, db)

    result = await db.execute(
        select(HealthEvent).where(
            HealthEvent.id == event_id, HealthEvent.pet_id == pet_id
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Health event not found")

    image_bytes = await proof.read()
    proof_url = await upload_health_proof(image_bytes, proof.content_type or "image/jpeg")
    if proof_url is None:
        raise HTTPException(status_code=500, detail="Erro ao fazer upload do comprovante")

    event.proof_url = proof_url
    await db.commit()
    await db.refresh(event)
    return _serialize(event)
