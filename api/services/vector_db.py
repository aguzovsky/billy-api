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

    _select = """
            SELECT
                b.id            AS biometry_id,
                b.pet_id,
                p.name          AS pet_name,
                p.species,
                p.breed,
                p.rg_animal_id,
                p.status,
                p.photo_url,
                u.id            AS owner_id,
                u.name          AS owner_name,
                u.contact_phone,
                u.neighborhood,
                u.is_verified   AS owner_is_verified,
                1 - (b.embedding <=> :embedding ::vector)  AS confidence,
                NULL                                        AS distance_km
            FROM biometrics b
            JOIN pets p ON p.id = b.pet_id
            JOIN users u ON u.id = p.owner_id
            WHERE 1 - (b.embedding <=> :embedding ::vector) >= :min_confidence
            ORDER BY confidence DESC
            LIMIT :top_k
    """
    params = {
        "embedding": embedding_str,
        "min_confidence": min_confidence,
        "top_k": top_k,
    }

    if lat is not None and lng is not None:
        # TODO: suporte geográfico no identify depende de colunas/tabela de localização
        # Por ora, lat/lng recebidos são ignorados — busca global por similaridade coseno
        query = text(_select)
    else:
        query = text(_select)

    result = await db.execute(query, params)
    rows = result.mappings().all()

    matches: list[dict] = []
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
        if row["status"] == "lost":
            owner_info = {
                "name": row["owner_name"],
                "contact_phone": row["contact_phone"],
                "neighborhood": row["neighborhood"],
                "is_verified": bool(row["owner_is_verified"]),
            }
        else:
            owner_info = {
                "id": str(row["owner_id"]),
                "name": row["owner_name"],
                "is_verified": bool(row["owner_is_verified"]),
            }

        matches.append({
            "rank": rank,
            "confidence": round(float(row["confidence"]), 4),
            "pet": pet_info,
            "owner": owner_info,
            "distance_km": round(float(row["distance_km"]), 2) if row["distance_km"] is not None else None,
        })

    return matches


async def diagnostic_top1(db: AsyncSession, embedding: list[float]) -> dict:
    """
    Retorna o melhor score e pet_id independente de threshold — só para logging de diagnóstico.
    Não é usado na lógica de identify; chamado apenas quando result está vazio.
    """
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
    query = text("""
        SELECT
            b.pet_id,
            1 - (b.embedding <=> :embedding ::vector) AS score,
            (SELECT COUNT(*) FROM biometrics)          AS total_in_db
        FROM biometrics b
        ORDER BY score DESC
        LIMIT 1
    """)
    result = await db.execute(query, {"embedding": embedding_str})
    row = result.mappings().first()
    if row is None:
        return {"best_score": None, "best_pet_id": None, "total_in_db": 0}
    return {
        "best_score": round(float(row["score"]), 4),
        "best_pet_id": str(row["pet_id"]),
        "total_in_db": int(row["total_in_db"]),
    }
