"""
pgvector similarity search for pet identification.
Uses Haversine for geo filtering (no PostGIS required).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_HAVERSINE_KM = """
    6371.0 * 2 * ASIN(SQRT(
        POWER(SIN(RADIANS(p.lat - :lat) / 2), 2) +
        COS(RADIANS(:lat)) * COS(RADIANS(p.lat)) *
        POWER(SIN(RADIANS(p.lng - :lng) / 2), 2)
    ))
"""


async def find_similar_pets(
    db: AsyncSession,
    embedding: list[float],
    lat: Optional[float],
    lng: Optional[float],
    search_radius_km: int,
    top_k: int,
    min_confidence: float,
) -> list[dict]:
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    if lat is not None and lng is not None:
        query = text(f"""
            SELECT
                b.id            AS biometry_id,
                b.pet_id,
                p.name          AS pet_name,
                p.species,
                p.breed,
                p.rg_animal_id,
                p.status,
                p.photo_url,
                u.name          AS owner_name,
                u.contact_phone,
                u.neighborhood,
                1 - (b.embedding <=> :embedding ::vector)  AS confidence,
                {_HAVERSINE_KM}                             AS distance_km
            FROM biometrics b
            JOIN pets p ON p.id = b.pet_id
            JOIN users u ON u.id = p.owner_id
            WHERE
                1 - (b.embedding <=> :embedding ::vector) >= :min_confidence
                AND p.lat IS NOT NULL AND p.lng IS NOT NULL
                AND {_HAVERSINE_KM} <= :radius_km
            ORDER BY confidence DESC
            LIMIT :top_k
        """)
        params = {
            "embedding": embedding_str,
            "lat": lat,
            "lng": lng,
            "radius_km": search_radius_km,
            "min_confidence": min_confidence,
            "top_k": top_k,
        }
    else:
        query = text("""
            SELECT
                b.id            AS biometry_id,
                b.pet_id,
                p.name          AS pet_name,
                p.species,
                p.breed,
                p.rg_animal_id,
                p.status,
                p.photo_url,
                u.name          AS owner_name,
                u.contact_phone,
                u.neighborhood,
                1 - (b.embedding <=> :embedding ::vector)  AS confidence,
                NULL                                        AS distance_km
            FROM biometrics b
            JOIN pets p ON p.id = b.pet_id
            JOIN users u ON u.id = p.owner_id
            WHERE 1 - (b.embedding <=> :embedding ::vector) >= :min_confidence
            ORDER BY confidence DESC
            LIMIT :top_k
        """)
        params = {
            "embedding": embedding_str,
            "min_confidence": min_confidence,
            "top_k": top_k,
        }

    result = await db.execute(query, params)
    rows = result.mappings().all()

    matches = []
    for rank, row in enumerate(rows, start=1):
        pet_info = {
            "id": str(row["pet_id"]),
            "name": row["pet_name"],
            "species": row["species"],
            "breed": row["breed"],
            "rg_animal_id": row["rg_animal_id"],
            "status": row["status"],
            "photo_url": row["photo_url"],
        }
        owner_info = None
        if row["status"] == "lost":
            owner_info = {
                "name": row["owner_name"],
                "contact_phone": row["contact_phone"],
                "neighborhood": row["neighborhood"],
            }

        matches.append({
            "rank": rank,
            "confidence": round(float(row["confidence"]), 4),
            "pet": pet_info,
            "owner": owner_info,
            "distance_km": round(float(row["distance_km"]), 2) if row["distance_km"] is not None else None,
        })

    return matches
