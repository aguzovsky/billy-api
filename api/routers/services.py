from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api.core.config import settings
from api.services.places_service import get_place_details, search_nearby

router = APIRouter(prefix="/services", tags=["services"])

_PHOTO_BASE = "https://places.googleapis.com/v1"


def _get_redis():
    try:
        import redis.asyncio as aioredis
        return aioredis.from_url(settings.redis_url, decode_responses=True)
    except Exception:
        return None


@router.get("/nearby", summary="Serviços pet próximos (vet, pet shop, parques)")
async def nearby_services(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: float = Query(None, ge=0.5, le=50),
    type_filter: str = Query("all", description="all | vet | pet_store | park"),
):
    if not settings.google_places_api_key:
        raise HTTPException(status_code=503, detail="Google Places não configurado")

    radius = radius_km if radius_km is not None else settings.places_default_radius_km
    redis = _get_redis()
    try:
        places = await search_nearby(
            lat=lat,
            lng=lng,
            radius_km=radius,
            type_filter=type_filter,
            api_key=settings.google_places_api_key,
            redis=redis,
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Google Places error: {e.response.status_code}")
    finally:
        if redis:
            await redis.aclose()

    return {"count": len(places), "places": places}


@router.get("/photos/{photo_name:path}", summary="Proxy de foto do Google Places")
async def place_photo(
    photo_name: str,
    max_width_px: int = Query(400, ge=100, le=1600),
):
    if not settings.google_places_api_key:
        raise HTTPException(status_code=503, detail="Google Places não configurado")

    url = f"{_PHOTO_BASE}/{photo_name}/media"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            resp = await client.get(
                url,
                params={"maxWidthPx": max_width_px, "key": settings.google_places_api_key},
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Photo fetch error: {e.response.status_code}")

    content_type = resp.headers.get("content-type", "image/jpeg")
    return StreamingResponse(iter([resp.content]), media_type=content_type)


@router.get("/{place_id}", summary="Detalhes de um serviço pet")
async def service_detail(place_id: str):
    if not settings.google_places_api_key:
        raise HTTPException(status_code=503, detail="Google Places não configurado")

    redis = _get_redis()
    try:
        place = await get_place_details(
            place_id=place_id,
            api_key=settings.google_places_api_key,
            redis=redis,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Local não encontrado")
        raise HTTPException(status_code=502, detail=f"Google Places error: {e.response.status_code}")
    finally:
        if redis:
            await redis.aclose()

    return place
