import json
import logging
import os
from uuid import UUID

import firebase_admin
from firebase_admin import credentials, messaging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.guardian import PetGuardian
from api.models.pet import Pet, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/guardians", tags=["guardians"])

_firebase_initialized = False


def _get_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return True
    # Reuse already-initialized default app (e.g. from notify.py)
    try:
        firebase_admin.get_app()
        _firebase_initialized = True
        return True
    except ValueError:
        pass  # not initialized yet
    creds_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    if not creds_json:
        return False
    try:
        cred = credentials.Certificate(json.loads(creds_json))
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        return True
    except Exception as e:
        logger.warning("Firebase init failed in guardians: %s", e)
        return False


async def _send_push(token: str | None, title: str, body: str) -> None:
    if not token or not _get_firebase():
        return
    try:
        messaging.send(
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                token=token,
            )
        )
    except Exception as e:
        logger.warning("FCM send failed (guardians): %s", e)


class InviteGuardianRequest(BaseModel):
    pet_id: str
    guardian_email: EmailStr


class RequestGuardianshipRequest(BaseModel):
    pet_id: str


# ── POST /invite ──────────────────────────────────────────────────────────────

@router.post("/invite", status_code=status.HTTP_201_CREATED, summary="Convidar guardião para um pet")
async def invite_guardian(
    body: InviteGuardianRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(
        select(Pet).where(Pet.id == UUID(body.pet_id), Pet.owner_id == UUID(user_id))
    )
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado ou não pertence a você")

    guardian_result = await db.execute(select(User).where(User.email == body.guardian_email))
    guardian = guardian_result.scalar_one_or_none()
    if guardian is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado. Confirme se o tutor já tem conta no Billy.")

    if str(guardian.id) == user_id:
        raise HTTPException(status_code=400, detail="Você não pode convidar a si mesmo")

    existing = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.pet_id == UUID(body.pet_id), PetGuardian.guardian_id == guardian.id)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Este tutor já foi convidado para este pet")

    invite = PetGuardian(
        pet_id=UUID(body.pet_id),
        guardian_id=guardian.id,
        invited_by_id=UUID(user_id),
        status="pending",
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    # Push notification to guardian (badge refresh na próxima troca de tab)
    await _send_push(
        guardian.fcm_token,
        "Convite de guarda recebido",
        f"Você recebeu um convite para cuidar de {pet.name}. Abra o Billy para responder.",
    )

    return {
        "id": str(invite.id),
        "pet_id": str(invite.pet_id),
        "pet_name": pet.name,
        "guardian_email": body.guardian_email,
        "status": invite.status,
    }


# ── POST /request ─────────────────────────────────────────────────────────────

@router.post("/request", status_code=status.HTTP_201_CREATED, summary="Solicitar ser guardião de um pet")
async def request_guardianship(
    body: RequestGuardianshipRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(select(Pet).where(Pet.id == UUID(body.pet_id)))
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")

    if str(pet.owner_id) == user_id:
        raise HTTPException(status_code=400, detail="Você já é o dono deste pet")

    existing = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.pet_id == UUID(body.pet_id), PetGuardian.guardian_id == UUID(user_id))
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Você já é guardião ou tem um pedido pendente para este pet")

    requester_result = await db.execute(select(User).where(User.id == UUID(user_id)))
    requester = requester_result.scalar_one_or_none()

    invite = PetGuardian(
        pet_id=UUID(body.pet_id),
        guardian_id=UUID(user_id),
        invited_by_id=UUID(user_id),
        status="pending",
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()
    requester_name = requester.name if requester else "Alguém"
    await _send_push(
        owner.fcm_token if owner else None,
        "Pedido de guarda recebido",
        f"{requester_name} quer ser guardião de {pet.name}. Abra o Billy para responder.",
    )

    return {"id": str(invite.id), "pet_id": str(invite.pet_id), "status": invite.status}


# ── GET /invites ──────────────────────────────────────────────────────────────

@router.get("/invites", summary="Meus convites pendentes de guarda")
async def my_invites(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.guardian_id == UUID(user_id), PetGuardian.status == "pending")
        )
    )
    invites = result.scalars().all()

    pet_ids = [i.pet_id for i in invites]
    owner_ids = [i.invited_by_id for i in invites]

    pets_map: dict = {}
    owners_map: dict = {}

    if pet_ids:
        pets_result = await db.execute(select(Pet).where(Pet.id.in_(pet_ids)))
        pets_map = {p.id: p for p in pets_result.scalars().all()}
    if owner_ids:
        owners_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
        owners_map = {u.id: u for u in owners_result.scalars().all()}

    return [
        {
            "id": str(i.id),
            "pet_id": str(i.pet_id),
            "pet_name": pets_map.get(i.pet_id, Pet()).name,
            "pet_species": pets_map.get(i.pet_id, Pet()).species,
            "owner_name": owners_map.get(i.invited_by_id, User()).name,
            "owner_email": owners_map.get(i.invited_by_id, User()).email,
            "created_at": i.created_at.isoformat(),
        }
        for i in invites
    ]


# ── PATCH /invites/{id}/respond ───────────────────────────────────────────────

@router.patch("/invites/{invite_id}/respond", summary="Aceitar ou recusar convite de guarda")
async def respond_invite(
    invite_id: str,
    accept: bool,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.id == UUID(invite_id), PetGuardian.guardian_id == UUID(user_id))
        )
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Convite já respondido")

    invite.status = "accepted" if accept else "declined"
    await db.commit()
    return {"status": invite.status}


# ── GET /my-pets ──────────────────────────────────────────────────────────────

@router.get("/my-pets", summary="Pets onde sou guardião (guarda compartilhada)")
async def guardian_pets(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.guardian_id == UUID(user_id), PetGuardian.status == "accepted")
        )
    )
    guardianships = result.scalars().all()

    if not guardianships:
        return []

    invite_by_pet: dict = {g.pet_id: str(g.id) for g in guardianships}
    pet_ids = [g.pet_id for g in guardianships]
    pets_result = await db.execute(select(Pet).where(Pet.id.in_(pet_ids)))
    pets = pets_result.scalars().all()

    owner_ids = [p.owner_id for p in pets]
    owners_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
    owners_map = {u.id: u for u in owners_result.scalars().all()}

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "species": p.species,
            "breed": p.breed,
            "status": p.status,
            "photo_url": p.photo_url,
            "has_biometry": False,
            "owner_name": owners_map.get(p.owner_id, User()).name,
            "role": "guardian",
            "invite_id": invite_by_pet.get(p.id),
        }
        for p in pets
    ]


# ── GET /{pet_id}/all ─────────────────────────────────────────────────────────

@router.get("/{pet_id}/all", summary="Todos os guardiões do pet (dono + aceitos)")
async def all_guardians(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(select(Pet).where(Pet.id == pet_id))
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")

    # Only owner or accepted guardian can access
    if str(pet.owner_id) != user_id:
        guardian_check = await db.execute(
            select(PetGuardian).where(
                and_(
                    PetGuardian.pet_id == pet_id,
                    PetGuardian.guardian_id == UUID(user_id),
                    PetGuardian.status == "accepted",
                )
            )
        )
        if guardian_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Acesso negado")

    # Owner
    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()

    people = []
    if owner:
        people.append({
            "id": str(owner.id),
            "name": owner.name or "",
            "photo_url": owner.photo_url,
            "role": "owner",
            "invite_id": None,
        })

    # Accepted guardians
    g_result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.pet_id == pet_id, PetGuardian.status == "accepted")
        )
    )
    guardianships = g_result.scalars().all()
    invite_map = {g.guardian_id: str(g.id) for g in guardianships}
    guardian_ids = list(invite_map.keys())
    if guardian_ids:
        users_result = await db.execute(select(User).where(User.id.in_(guardian_ids)))
        for u in users_result.scalars().all():
            people.append({
                "id": str(u.id),
                "name": u.name or "",
                "photo_url": u.photo_url,
                "role": "guardian",
                "invite_id": invite_map.get(u.id),
            })

    return people


# ── GET /{pet_id}/guardians ───────────────────────────────────────────────────

@router.get("/{pet_id}/guardians", summary="Listar membros da guarda compartilhada (tutor + guardiões)")
async def list_pet_guardians(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(select(Pet).where(Pet.id == pet_id))
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")

    # Tutor ou guardião aceito podem acessar
    if str(pet.owner_id) != user_id:
        guardian_check = await db.execute(
            select(PetGuardian).where(
                and_(
                    PetGuardian.pet_id == pet_id,
                    PetGuardian.guardian_id == UUID(user_id),
                    PetGuardian.status == "accepted",
                )
            )
        )
        if guardian_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Acesso negado")

    # Tutor sempre primeiro
    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()

    members = []
    if owner:
        members.append({
            "id": f"owner-{str(pet_id)}",
            "pet_id": str(pet_id),
            "guardian_user_id": str(owner.id),
            "guardian_name": owner.name or "",
            "guardian_email": owner.email or "",
            "status": "accepted",
            "role": "owner",
        })

    # Guardiões aceitos
    g_result = await db.execute(
        select(PetGuardian).where(
            and_(PetGuardian.pet_id == pet_id, PetGuardian.status == "accepted")
        )
    )
    guardianships = g_result.scalars().all()
    if guardianships:
        guardian_ids = [g.guardian_id for g in guardianships]
        users_result = await db.execute(select(User).where(User.id.in_(guardian_ids)))
        users_map = {u.id: u for u in users_result.scalars().all()}
        for g in guardianships:
            u = users_map.get(g.guardian_id)
            members.append({
                "id": str(g.id),
                "pet_id": str(pet_id),
                "guardian_user_id": str(g.guardian_id),
                "guardian_name": u.name if u else "",
                "guardian_email": u.email if u else "",
                "status": g.status,
                "role": "guardian",
            })

    return members


# ── DELETE /{pet_id}/guardians/leave ─────────────────────────────────────────
# ATENÇÃO: deve ficar ANTES de /{pet_id}/guardians/{guardian_user_id}

@router.delete("/{pet_id}/guardians/leave", status_code=status.HTTP_204_NO_CONTENT, summary="Guardião sai por conta própria")
async def leave_guardianship(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(PetGuardian).where(
            and_(
                PetGuardian.pet_id == pet_id,
                PetGuardian.guardian_id == UUID(user_id),
                PetGuardian.status == "accepted",
            )
        )
    )
    guardianship = result.scalar_one_or_none()
    if guardianship is None:
        raise HTTPException(status_code=404, detail="Guarda não encontrada")
    await db.delete(guardianship)
    await db.commit()


# ── DELETE /{pet_id}/guardians/{guardian_user_id} ─────────────────────────────

@router.delete("/{pet_id}/guardians/{guardian_user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Tutor remove guardião")
async def remove_guardian_by_user(
    pet_id: UUID,
    guardian_user_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(
        select(Pet).where(Pet.id == pet_id, Pet.owner_id == UUID(user_id))
    )
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado ou não pertence a você")

    result = await db.execute(
        select(PetGuardian).where(
            and_(
                PetGuardian.pet_id == pet_id,
                PetGuardian.guardian_id == guardian_user_id,
                PetGuardian.status == "accepted",
            )
        )
    )
    guardianship = result.scalar_one_or_none()
    if guardianship is None:
        raise HTTPException(status_code=404, detail="Guardião não encontrado")
    await db.delete(guardianship)
    await db.commit()


# ── DELETE /invites/{id} ──────────────────────────────────────────────────────

@router.delete("/invites/{invite_id}", summary="Sair da guarda / remover guardião")
async def remove_guardian(
    invite_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    # Owner removing a guardian
    result = await db.execute(
        select(PetGuardian).join(Pet, PetGuardian.pet_id == Pet.id).where(
            and_(PetGuardian.id == UUID(invite_id), Pet.owner_id == UUID(user_id))
        )
    )
    invite = result.scalar_one_or_none()

    # Guardian leaving
    if invite is None:
        result = await db.execute(
            select(PetGuardian).where(
                and_(PetGuardian.id == UUID(invite_id), PetGuardian.guardian_id == UUID(user_id))
            )
        )
        invite = result.scalar_one_or_none()
        if invite is None:
            raise HTTPException(status_code=404, detail="Guardião não encontrado")

        # Guardian leaving → notify owner (never block the delete)
        try:
            pet_result = await db.execute(select(Pet).where(Pet.id == invite.pet_id))
            pet = pet_result.scalar_one_or_none()
            guardian_result = await db.execute(select(User).where(User.id == UUID(user_id)))
            guardian_user = guardian_result.scalar_one_or_none()
            owner = None
            if pet:
                owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
                owner = owner_result.scalar_one_or_none()
            guardian_name = guardian_user.name if guardian_user else "Guardião"
            pet_name = pet.name if pet else "seu pet"
            await _send_push(
                owner.fcm_token if owner else None,
                "Guardião saiu",
                f"{guardian_name} saiu da guarda de {pet_name}.",
            )
        except Exception as e:
            logger.warning("remove_guardian notify failed (non-fatal): %s", e)

    logger.info("remove_guardian: deleting invite %s for user %s", invite_id, user_id)
    await db.delete(invite)
    await db.commit()
    return {"status": "removed"}
