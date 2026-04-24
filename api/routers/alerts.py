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


@router.get("/mine", summary="Meus alertas emitidos")
async def my_alerts(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    from sqlalchemy import select as sa_select
    q = (
        sa_select(Alert)
        .join(Pet, Alert.pet_id == Pet.id)
        .where(Pet.owner_id == UUID(user_id))
        .order_by(Alert.created_at.desc())
    )
    result = await db.execute(q)
    alerts = result.scalars().all()

    pet_ids = [a.pet_id for a in alerts]
    pets_result = await db.execute(sa_select(Pet).where(Pet.id.in_(pet_ids)))
    pets_map = {p.id: p for p in pets_result.scalars().all()}

    return [
        {
            "id": str(a.id),
            "pet_id": str(a.pet_id),
            "pet_name": pets_map.get(a.pet_id, Pet()).name,
            "pet_species": pets_map.get(a.pet_id, Pet()).species,
            "alert_type": a.alert_type,
            "status": a.status,
            "description": a.description,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]


@router.patch("/{alert_id}/resolve", summary="Marcar alerta como resolvido")
async def resolve_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(Alert)
        .join(Pet, Alert.pet_id == Pet.id)
        .where(Alert.id == UUID(alert_id), Pet.owner_id == UUID(user_id))
    )
    alert = result.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found or not owned by you")

    alert.status = "resolved"
    pet_result = await db.execute(sa_select(Pet).where(Pet.id == alert.pet_id))
    pet = pet_result.scalar_one_or_none()
    if pet:
        pet.status = "home"

    await db.commit()
    return {"status": "resolved"}


@router.get("", summary="Buscar alertas próximos por geolocalização")
async def list_alerts(
    lat: Optional[float] = Query(None, description="Latitude"),
    lng: Optional[float] = Query(None, description="Longitude"),
    radius_km: int = Query(10, ge=1, le=500),
    alert_type: Optional[str] = Query(None, description="lost | found"),
    db: AsyncSession = Depends(get_db),
):
    if lat is not None and lng is not None:
        alerts = await find_alerts_near(
            db=db, lat=lat, lng=lng, radius_km=radius_km, alert_type=alert_type
        )
    else:
        # Return all active alerts when no location provided
        from sqlalchemy import select as sa_select
        from api.models.alert import Alert
        q = sa_select(Alert).where(Alert.status == "active").order_by(Alert.created_at.desc()).limit(50)
        if alert_type:
            q = q.where(Alert.alert_type == alert_type)
        result = await db.execute(q)
        raw = result.scalars().all()
        # Load pet names in one query
        pet_ids = [a.pet_id for a in raw]
        pets_result = await db.execute(sa_select(Pet).where(Pet.id.in_(pet_ids)))
        pets_map = {p.id: p for p in pets_result.scalars().all()}

        alerts = [
            {
                "id": str(a.id),
                "pet_id": str(a.pet_id),
                "pet_name": pets_map.get(a.pet_id, Pet()).name,
                "pet_species": pets_map.get(a.pet_id, Pet()).species,
                "alert_type": a.alert_type,
                "description": a.description,
                "lat": a.lat,
                "lng": a.lng,
                "distance_km": None,
                "created_at": a.created_at.isoformat(),
            }
            for a in raw
        ]
    return {"count": len(alerts), "alerts": alerts}
