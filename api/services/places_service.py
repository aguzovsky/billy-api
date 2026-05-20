"""Google Places API v1 wrapper with Redis caching (TTL 1h)."""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PLACES_BASE = "https://places.googleapis.com/v1/places"

# Maps filter chip names → Google Places includedTypes
_TYPE_MAP: dict[str, list[str]] = {
    "all": ["veterinary_care", "pet_store", "dog_park"],
    "vet": ["veterinary_care"],
    "pet_store": ["pet_store"],
    "park": ["dog_park"],
    "groomer": ["pet_grooming"],
    "veterinary_care": ["veterinary_care"],
}

_LISTING_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.rating",
    "places.userRatingCount",
    "places.regularOpeningHours.openNow",
    "places.location",
    "places.types",
    "places.photos",
])

_DETAIL_MASK = ",".join([
    "id",
    "displayName",
    "rating",
    "userRatingCount",
    "regularOpeningHours",
    "location",
    "types",
    "photos",
    "nationalPhoneNumber",
    "websiteUri",
])


async def search_nearby(
    lat: float,
    lng: float,
    radius_km: float,
    type_filter: str = "all",
    api_key: str = "",
    redis=None,
) -> list[dict]:
    cache_key = f"places:nearby:{lat:.4f}:{lng:.4f}:{radius_km}:{type_filter}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    if type_filter == "groomer":
        places = await _search_text(
            text_query="banho e tosa pet",
            lat=lat,
            lng=lng,
            radius_km=radius_km,
            api_key=api_key,
        )
    else:
        included_types = _TYPE_MAP.get(type_filter, _TYPE_MAP["all"])
        body = {
            "includedTypes": included_types,
            "maxResultCount": 20,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": radius_km * 1000,
                }
            },
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_PLACES_BASE}:searchNearby",
                json=body,
                headers={
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": _LISTING_MASK,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        places = [_serialize_listing(p) for p in data.get("places", [])]

    if redis:
        await redis.setex(cache_key, 3600, json.dumps(places))

    return places


async def _search_text(
    text_query: str,
    lat: float,
    lng: float,
    radius_km: float,
    api_key: str = "",
) -> list[dict]:
    body = {
        "textQuery": text_query,
        "maxResultCount": 20,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_km * 1000,
            }
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_PLACES_BASE}:searchText",
            json=body,
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": _LISTING_MASK,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return [_serialize_listing(p) for p in data.get("places", [])]


async def get_place_details(
    place_id: str,
    api_key: str = "",
    redis=None,
) -> dict:
    cache_key = f"places:detail:{place_id}"

    if redis:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_PLACES_BASE}/{place_id}",
            headers={
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": _DETAIL_MASK,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    place = _serialize_detail(data)

    if redis:
        await redis.setex(cache_key, 3600, json.dumps(place))

    return place


def _serialize_listing(p: dict) -> dict:
    return {
        "id": p.get("id", ""),
        "name": p.get("displayName", {}).get("text", ""),
        "rating": p.get("rating"),
        "user_rating_count": p.get("userRatingCount"),
        "open_now": p.get("regularOpeningHours", {}).get("openNow"),
        "location": {
            "lat": p.get("location", {}).get("latitude"),
            "lng": p.get("location", {}).get("longitude"),
        },
        "types": p.get("types", []),
        "photo_name": _first_photo_name(p),
    }


def _serialize_detail(p: dict) -> dict:
    return {
        "id": p.get("id", ""),
        "name": p.get("displayName", {}).get("text", ""),
        "rating": p.get("rating"),
        "user_rating_count": p.get("userRatingCount"),
        "open_now": p.get("regularOpeningHours", {}).get("openNow"),
        "weekday_descriptions": p.get("regularOpeningHours", {}).get("weekdayDescriptions", []),
        "location": {
            "lat": p.get("location", {}).get("latitude"),
            "lng": p.get("location", {}).get("longitude"),
        },
        "types": p.get("types", []),
        "photo_names": [ph.get("name", "") for ph in p.get("photos", [])[:5]],
        "phone": p.get("nationalPhoneNumber"),
        "website": p.get("websiteUri"),
    }


def _first_photo_name(p: dict) -> Optional[str]:
    photos = p.get("photos", [])
    return photos[0].get("name") if photos else None
