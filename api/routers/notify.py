import json
import logging
import os
from uuid import UUID

import firebase_admin
from firebase_admin import credentials, messaging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.guardian import PetGuardian
from api.models.pet import Pet, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notify", tags=["notify"])

_firebase_initialized = False


def _get_firebase_app():
    global _firebase_initialized
    if _firebase_initialized:
        return True
    creds_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    if not creds_json:
        return False
    try:
        creds_dict = json.loads(creds_json)
        cred = credentials.Certificate(creds_dict)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        return True
    except Exception as e:
        logger.warning("Firebase init failed: %s", e)
        return False


class NotifyOwnerRequest(BaseModel):
    pet_id: str


@router.post("/owner", summary="Notificar tutor e guardiões sobre pet localizado")
async def notify_owner(
    body: NotifyOwnerRequest,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user_id),
):
    try:
        pet_uuid = UUID(body.pet_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="pet_id inválido")

    result = await db.execute(select(Pet).where(Pet.id == pet_uuid))
    pet = result.scalar_one_or_none()
    if not pet:
        raise HTTPException(status_code=404, detail="Pet não encontrado")

    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()

    guardian_result = await db.execute(
        select(PetGuardian).where(
            PetGuardian.pet_id == pet_uuid,
            PetGuardian.status == "accepted",
        )
    )
    guardians = guardian_result.scalars().all()

    guardian_ids = [g.guardian_id for g in guardians]
    recipients: list[User] = []
    if owner:
        recipients.append(owner)
    if guardian_ids:
        g_result = await db.execute(select(User).where(User.id.in_(guardian_ids)))
        recipients.extend(g_result.scalars().all())

    tokens = [u.fcm_token for u in recipients if u.fcm_token]
    if not tokens:
        return {"sent": 0}

    if not _get_firebase_app():
        logger.warning("Firebase not configured — skipping push for pet %s", body.pet_id)
        return {"sent": 0}

    sent = 0
    for token in tokens:
        try:
            messaging.send(
                messaging.Message(
                    notification=messaging.Notification(
                        title="Pet localizado 🐾",
                        body="Alguém encontrou um pet parecido com o seu. Abra o Billy para ver.",
                    ),
                    token=token,
                )
            )
            sent += 1
        except Exception as e:
            logger.warning("FCM send failed for token %s: %s", token[:10], e)

    return {"sent": sent}
