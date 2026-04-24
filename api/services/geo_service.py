"""Haversine-based geo helpers for alert queries (no PostGIS required)."""

from __future__ import annotations

from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_HAVERSINE_KM = """
    6371.0 * 2 * ASIN(SQRT(
        POWER(SIN(RADIANS(({lat_col}) - :lat) / 2), 2) +
        COS(RADIANS(:lat)) * COS(RADIANS({lat_col})) *
        POWER(SIN(RADIANS(({lng_col}) - :lng) / 2), 2)
    ))
"""


async def find_alerts_near(
    db: AsyncSession,
    lat: float,
    lng: float,
    radius_km: int,
    alert_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    dist_expr = _HAVERSINE_KM.format(lat_col="a.lat", lng_col="a.lng")
    type_filter = "AND a.alert_type = :alert_type" if alert_type else ""

    query = text(f"""
        SELECT
            a.id,
            a.pet_id,
            a.alert_type,
            a.description,
            a.lat,
            a.lng,
            a.radius_km,
            a.photo_url,
            a.status,
            a.created_at,
            p.name      AS pet_name,
            p.species,
            p.breed,
            p.photo_url AS pet_photo_url,
            {dist_expr} AS distance_km
        FROM alerts a
        JOIN pets p ON p.id = a.pet_id
        WHERE
            a.status = 'active'
            AND {dist_expr} <= :radius_km
            {type_filter}
        ORDER BY distance_km ASC
        LIMIT :limit
    """)

    params: dict = {"lat": lat, "lng": lng, "radius_km": radius_km, "limit": limit}
    if alert_type:
        params["alert_type"] = alert_type

    result = await db.execute(query, params)
    rows = result.mappings().all()

    return [
        {
            "id": str(row["id"]),
            "pet_id": str(row["pet_id"]),
            "alert_type": row["alert_type"],
            "description": row["description"],
            "lat": row["lat"],
            "lng": row["lng"],
            "radius_km": row["radius_km"],
            "photo_url": row["photo_url"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat(),
            "distance_km": round(float(row["distance_km"]), 2),
            "pet": {
                "name": row["pet_name"],
                "species": row["species"],
                "breed": row["breed"],
                "photo_url": row["pet_photo_url"],
            },
        }
        for row in rows
    ]
