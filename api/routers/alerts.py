from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.alert import Alert
from api.models.pet import Pet
from api.services.geo_service import find_alerts_near

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertCreate(BaseModel):
    pet_id: str
    alert_type: str  # 'lost' | 'found'
    description: Optional[str] = None
    lat: float
    lng: float
    radius_km: int = 10
    photo_url: Optional[str] = None


@router.post("", status_code=status.HTTP_201_CREATED, summary="Emitir alerta de pet perdido/encontrado")
async def create_alert(
    body: AlertCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    if body.alert_type not in ("lost", "found"):
        raise HTTPException(status_code=400, detail="alert_type must be 'lost' or 'found'")

    # Verify ownership
    result = await db.execute(
        select(Pet).where(Pet.id == UUID(body.pet_id), Pet.owner_id == UUID(user_id))
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found or not owned by you")

    alert = Alert(
        pet_id=UUID(body.pet_id),
        alert_type=body.alert_type,
        description=body.description,
        lat=body.lat,
        lng=body.lng,
        radius_km=body.radius_km,
        photo_url=body.photo_url,
    )
    # Keep pet status in sync
    pet.status = body.alert_type  # 'lost' | 'found'

    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    return {
        "id": str(alert.id),
        "pet_id": str(alert.pet_id),
        "alert_type": alert.alert_type,
        "status": alert.status,
        "lat": alert.lat,
        "lng": alert.lng,
        "radius_km": alert.radius_km,
        "created_at": alert.created_at.isoformat(),
    }


@router.get("", summary="Buscar alertas próximos por geolocalização")
async def list_alerts(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: int = Query(10, ge=1, le=500),
    alert_type: Optional[str] = Query(None, description="lost | found"),
    db: AsyncSession = Depends(get_db),
):
    alerts = await find_alerts_near(
        db=db, lat=lat, lng=lng, radius_km=radius_km, alert_type=alert_type
    )
    return {"count": len(alerts), "alerts": alerts}
