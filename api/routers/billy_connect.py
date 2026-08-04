import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.guardian import PetGuardian
from api.models.pet import Pet, User
from api.models.pro import Establishment, ProClient, ProConnectInvite, ProPet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billy-connect", tags=["billy-connect"])


async def _get_invite_for_user(invite_id: UUID, user_id: str, db: AsyncSession) -> ProConnectInvite:
    result = await db.execute(select(ProConnectInvite).where(ProConnectInvite.id == invite_id))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="Convite não encontrado")
    if invite.app_user_id is None or str(invite.app_user_id) != user_id:
        raise HTTPException(status_code=403, detail="Este convite não pertence a este usuário")
    return invite


def _invite_out(invite: ProConnectInvite, establishment_name: str | None = None) -> dict:
    # BIL-148 — sem app_pet_id/expires_at: convite não é mais por pet nem
    # expira. establishment_name é o único dado de exibição que o card
    # precisa (nunca mostra pet nenhum, de propósito — ver contrato da API).
    return {
        "id": str(invite.id),
        "status": invite.status,
        "created_at": invite.created_at.isoformat(),
        "establishment_name": establishment_name,
    }


@router.get("/invites", summary="Meus convites Billy Connect pendentes")
async def my_invites(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(ProConnectInvite).where(
            ProConnectInvite.app_user_id == UUID(user_id),
            ProConnectInvite.status == "pending",
        )
    )
    invites = result.scalars().all()

    est_ids = [i.establishment_id for i in invites]
    est_map: dict = {}
    if est_ids:
        est_result = await db.execute(select(Establishment).where(Establishment.id.in_(est_ids)))
        est_map = {e.id: e for e in est_result.scalars().all()}

    return [
        {
            "id": str(i.id),
            "establishment_name": est_map[i.establishment_id].name if i.establishment_id in est_map else None,
            "created_at": i.created_at.isoformat(),
        }
        for i in invites
    ]


@router.get("/invite/{invite_id}", summary="Detalhes de um convite Billy Connect")
async def get_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    invite = await _get_invite_for_user(invite_id, user_id, db)
    establishment_result = await db.execute(
        select(Establishment).where(Establishment.id == invite.establishment_id)
    )
    establishment = establishment_result.scalar_one_or_none()
    return _invite_out(invite, establishment.name if establishment else None)


# BIL-148 — pets do tutor pra fins de match no accept: owner OU guardião já
# aceito. Antes (BIL-39) só considerava owner_id — um guardião que recebesse
# o convite nunca via os pets que guarda como opção (nem tinha como, dado
# que a tela antiga exigia escolher um pet pra confirmar).
async def _get_tutor_pets(user_id: str, db: AsyncSession) -> list[Pet]:
    owned_result = await db.execute(
        select(Pet).where(Pet.owner_id == UUID(user_id)).order_by(Pet.created_at)
    )
    owned = list(owned_result.scalars().all())

    guardian_result = await db.execute(
        select(Pet)
        .join(PetGuardian, PetGuardian.pet_id == Pet.id)
        .where(PetGuardian.guardian_id == UUID(user_id), PetGuardian.status == "accepted")
        .order_by(Pet.created_at)
    )
    guarded = list(guardian_result.scalars().all())

    seen = {p.id for p in owned}
    return owned + [p for p in guarded if p.id not in seen]


@router.post("/invite/{invite_id}/accept", summary="Aceitar convite Billy Connect")
async def accept_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    invite = await _get_invite_for_user(invite_id, user_id, db)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"Convite não está mais pendente (status: {invite.status})")

    client_result = await db.execute(select(ProClient).where(ProClient.id == invite.pro_client_id))
    client = client_result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    establishment_result = await db.execute(
        select(Establishment).where(Establishment.id == invite.establishment_id)
    )
    establishment = establishment_result.scalar_one_or_none()

    invite.status = "confirmed"
    client.billy_user_id = UUID(user_id)
    client.billy_profile_status = "conectado"

    # BIL-148 — "todos os pets atuais do tutor entram automaticamente" não
    # tem exceção: nome só decide QUAL pro_pet linka com QUAL pet do tutor
    # quando há ambiguidade real (múltiplos candidatos dos dois lados). Sem
    # ambiguidade — 1 pet do tutor pra 1 pro_pet do cliente — vincula direto,
    # nome nem entra na jogada (grafias podem divergir entre Pro e App sem
    # significar nada). Com múltiplos candidatos, tenta nome primeiro; todo
    # pro_pet que sobrar sem match claro AINDA é vinculado, ao pet do tutor
    # mais "disponível" (sem nenhum pro_pet linkado ainda) — só fica sem
    # link se realmente faltar pet do tutor disponível (ambiguidade genuína,
    # deve ser raro, não o caminho comum).
    tutor_pets = await _get_tutor_pets(user_id, db)
    pro_pets_result = await db.execute(
        select(ProPet).where(ProPet.client_id == client.id).order_by(ProPet.created_at)
    )
    pro_pets = list(pro_pets_result.scalars().all())

    linked_count = 0
    unmatched_count = 0

    if len(tutor_pets) == 1 and len(pro_pets) == 1:
        pro_pets[0].billy_pet_id = tutor_pets[0].id
        linked_count = 1
    else:
        tutor_pets_by_name: dict[str, Pet] = {}
        for p in sorted(tutor_pets, key=lambda p: p.created_at):
            tutor_pets_by_name.setdefault(p.name.strip().lower(), p)

        used_tutor_pet_ids: set = set()
        unmatched_pro_pets: list[ProPet] = []

        for pro_pet in pro_pets:
            match = tutor_pets_by_name.get(pro_pet.name.strip().lower())
            if match is not None and match.id not in used_tutor_pet_ids:
                pro_pet.billy_pet_id = match.id
                used_tutor_pet_ids.add(match.id)
                linked_count += 1
            else:
                unmatched_pro_pets.append(pro_pet)

        available_tutor_pets = [p for p in tutor_pets if p.id not in used_tutor_pet_ids]
        for pro_pet in unmatched_pro_pets:
            if available_tutor_pets:
                fallback_pet = available_tutor_pets.pop(0)
                pro_pet.billy_pet_id = fallback_pet.id
                used_tutor_pet_ids.add(fallback_pet.id)
                linked_count += 1
            else:
                unmatched_count += 1

    await db.commit()
    await db.refresh(invite)

    return {
        **_invite_out(invite, establishment.name if establishment else None),
        "linked_pets_count": linked_count,
        "unmatched_pets_count": unmatched_count,
    }


@router.post("/invite/{invite_id}/decline", summary="Recusar convite Billy Connect")
async def decline_invite(
    invite_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    invite = await _get_invite_for_user(invite_id, user_id, db)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail=f"Convite não está mais pendente (status: {invite.status})")

    invite.status = "declined"

    # BIL-148 — 'recusado' é distinto de 'nao_conectado' (nunca convidado):
    # antes (BIL-39) o decline revertia isso silenciosamente pra
    # 'nao_conectado', apagando o histórico de recusa do lado do Pro.
    # Reenviar (POST /billy-connect/request de novo) reabre esse mesmo
    # convite pra 'convite_pendente' — ver billy_connect_request em pro.py.
    client_result = await db.execute(select(ProClient).where(ProClient.id == invite.pro_client_id))
    client = client_result.scalar_one_or_none()
    if client is not None:
        client.billy_profile_status = "recusado"

    await db.commit()
    await db.refresh(invite)

    return _invite_out(invite)
