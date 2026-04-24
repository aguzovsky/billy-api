"""
Biometry endpoints:
  POST /api/v1/biometry/register   — enroll a pet's nose embedding
  POST /api/v1/biometry/identify   — identify a pet from a photo
"""

from __future__ import annotations

import json
import time
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.biometry import Biometric
from api.services import reid_service as reid_module
from api.services import vector_db, storage

router = APIRouter(prefix="/biometry", tags=["biometry"])

MAX_BYTES = settings.max_image_size_mb * 1024 * 1024


def _error(code: str, message: str, **extra):
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": code, "message": message, **extra},
    )


async def _read_and_validate_image(file: UploadFile) -> bytes:
    image_bytes = await file.read()
    if len(image_bytes) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": "IMAGE_TOO_LARGE", "message": f"Imagem maior que {settings.max_image_size_mb}MB"},
        )
    return image_bytes


# ──────────────────────────────────────────────────────────────────────────────
# POST /register
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/register", summary="Registrar biometria nasal de um pet")
async def register_biometry(
    image: UploadFile = File(..., description="Foto do focinho (JPG/PNG, max 10 MB)"),
    pet_id: str = Form(..., description="UUID do pet"),
    capture_metadata: Optional[str] = Form(None, description="JSON opcional: {lat, lng, device, timestamp}"),
    db: AsyncSession = Depends(get_db),
    _user_id: str = Depends(get_current_user_id),
):
    t0 = time.monotonic()
    image_bytes = await _read_and_validate_image(image)

    reid = reid_module.get_reid_service()

    quality = reid.quality_score(image_bytes)
    if quality < settings.min_quality_score:
        _error(
            "LOW_QUALITY",
            "Imagem com qualidade insuficiente para extração biométrica",
            quality_score=quality,
            suggestion="retry_with_better_image",
        )

    embedding = reid.extract_embedding(image_bytes)

    # Upload original photo to S3/MinIO (never store in DB)
    photo_url = await storage.upload_photo(image_bytes, image.content_type or "image/jpeg")

    # Parse optional metadata
    metadata = None
    if capture_metadata:
        try:
            metadata = json.loads(capture_metadata)
        except json.JSONDecodeError:
            pass

    # Persist biometric record
    bio = Biometric(
        pet_id=UUID(pet_id),
        embedding=embedding,
        quality_score=quality,
        capture_metadata=metadata,
    )
    db.add(bio)
    await db.commit()
    await db.refresh(bio)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    return {
        "success": True,
        "biometry_id": f"bm_{str(bio.id).replace('-', '')[:12]}",
        "pet_id": pet_id,
        "embedding_dims": len(embedding),
        "quality_score": quality,
        "registered_at": bio.registered_at.isoformat(),
        "rg_animal_synced": False,
        "processing_ms": elapsed_ms,
    }


# ──────────────────────────────────────────────────────────────────────────────
# POST /identify
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/identify", summary="Identificar pet por biometria nasal")
async def identify_pet(
    image: UploadFile = File(..., description="Foto do focinho (JPG/PNG, max 10 MB)"),
    lat: Optional[float] = Form(None, description="Latitude para busca geográfica"),
    lng: Optional[float] = Form(None, description="Longitude para busca geográfica"),
    search_radius_km: int = Form(settings.default_search_radius_km, ge=1, le=500),
    top_k: int = Form(settings.default_top_k, ge=1, le=10),
    min_confidence: float = Form(settings.default_min_confidence, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    t0 = time.monotonic()
    image_bytes = await _read_and_validate_image(image)

    reid = reid_module.get_reid_service()

    quality = reid.quality_score(image_bytes)
    if quality < settings.min_quality_score:
        _error(
            "LOW_QUALITY",
            "Imagem com qualidade insuficiente para identificação",
            quality_score=quality,
            suggestion="retry_with_better_image",
        )

    embedding = reid.extract_embedding(image_bytes)

    results = await vector_db.find_similar_pets(
        db=db,
        embedding=embedding,
        lat=lat,
        lng=lng,
        search_radius_km=search_radius_km,
        top_k=top_k,
        min_confidence=min_confidence,
    )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    return {
        "matched": len(results) > 0,
        "quality_score": quality,
        "results": results,
        "processing_ms": elapsed_ms,
    }
