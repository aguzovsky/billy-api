import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

import firebase_admin
import httpx
from firebase_admin import credentials, messaging
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, EmailStr, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import (
    create_access_token,
    get_current_establishment_id,
    hash_password,
    verify_password,
)
from api.data.pet_breeds import BREEDS_BY_SPECIES
from api.models.pet import User
from api.models.pro import (
    Establishment,
    ProAppointment,
    ProClient,
    ProConnectInvite,
    ProFeedback,
    ProPet,
    ProPetGuardian,
    ProReminder,
    ProService,
    ProSubscription,
)
from api.services import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pro", tags=["pro"])

ESTABLISHMENT_TYPES = ["clinica", "petshop", "hotel", "daycare", "autonomo", "misto"]
PET_SPECIES = ["dog", "cat"]  # igual ao Billy App
PET_APPROXIMATE_AGES = ["puppy", "young", "adult", "senior"]
PET_GENDERS = ["male", "female", "unknown"]


def _validate_species(v: str) -> str:
    if v not in PET_SPECIES:
        raise ValueError(f"species deve ser um de: {', '.join(PET_SPECIES)}")
    return v


def _validate_approximate_age(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in PET_APPROXIMATE_AGES:
        raise ValueError(f"approximate_age deve ser um de: {', '.join(PET_APPROXIMATE_AGES)}")
    return v


def _validate_gender(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in PET_GENDERS:
        raise ValueError(f"gender deve ser um de: {', '.join(PET_GENDERS)}")
    return v


def _check_breed(species: str, breed: Optional[str]) -> None:
    """Valida breed contra a lista fixa por espécie. Não bloqueia o cadastro
    ainda — só loga um warning quando não bate, igual pedido no alinhamento inicial."""
    if not breed:
        return
    valid_breeds = BREEDS_BY_SPECIES.get(species, [])
    if breed not in valid_breeds:
        logger.warning("breed '%s' não está na lista conhecida para species '%s'", breed, species)


SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")


def _check_not_past(date_str: str, time_str: str) -> None:
    """Garante que date+time não está no passado, usando horário de
    Brasília — nunca o horário UTC do servidor (mesmo bug de timezone
    corrigido no frontend)."""
    try:
        candidate = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=SAO_PAULO_TZ)
    except ValueError:
        raise HTTPException(status_code=422, detail="date/time em formato inválido (esperado YYYY-MM-DD / HH:MM).")
    if candidate <= datetime.now(SAO_PAULO_TZ):
        raise HTTPException(status_code=422, detail="Não é possível agendar para uma data/hora que já passou.")


# BIL-91 (revisado) — espelha PLANS[].limits.servicesPerDay em
# billy-pro/src/data/plans.ts. Sem fonte única compartilhada entre os dois
# repos (TS front / Python back) — mudar o limite de um plano precisa
# atualizar os dois lados. Plano ausente daqui = sem limite de serviços/dia
# (Matilha, todo Track B).
PLAN_SERVICES_PER_DAY: dict[str, int] = {
    "latido": 2,
    "corrida": 3,
}


async def _check_services_per_day_limit(establishment_id: str, date_str: str, db: AsyncSession) -> None:
    """Bloqueia criar um agendamento se o plano atual tem servicesPerDay
    definido e a conta já atingiu o limite NAQUELE dia (campo `date`, que já
    é a data local do estabelecimento — mesma convenção de _check_not_past,
    nunca UTC do servidor). Cancelado não conta pro limite: quem cancelou
    liberou a vaga daquele dia."""
    sub_result = await db.execute(
        select(ProSubscription).where(ProSubscription.establishment_id == UUID(establishment_id))
    )
    subscription = sub_result.scalar_one_or_none()
    limit = PLAN_SERVICES_PER_DAY.get(subscription.plan_id) if subscription else None
    if limit is None:
        return

    count_result = await db.execute(
        select(func.count()).select_from(ProAppointment).where(
            ProAppointment.establishment_id == UUID(establishment_id),
            ProAppointment.date == date_str,
            ProAppointment.status != "cancelado",
        )
    )
    if count_result.scalar_one() >= limit:
        raise HTTPException(
            status_code=403,
            detail=f"Limite de {limit} serviços por dia do plano {subscription.plan_id.capitalize()} atingido. Faça upgrade para continuar.",
        )


def _validate_password_strength(password: str) -> str:
    """Valida força da senha: mín. 8 chars, 1 maiúscula, 1 número."""
    if len(password) < 8:
        raise ValueError("A senha deve ter pelo menos 8 caracteres.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("A senha deve conter pelo menos uma letra maiúscula.")
    if not re.search(r"[0-9]", password):
        raise ValueError("A senha deve conter pelo menos um número.")
    return password


# ── Schemas ──────────────────────────────────────────────────────────────


class EstablishmentRegister(BaseModel):
    name: str
    type: str
    email: EmailStr
    password: str
    whatsapp: Optional[str] = None
    city: Optional[str] = None

    @field_validator("type")
    @classmethod
    def type_valid(cls, v: str) -> str:
        if v not in ESTABLISHMENT_TYPES:
            raise ValueError(f"type deve ser um de: {', '.join(ESTABLISHMENT_TYPES)}")
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class EstablishmentLogin(BaseModel):
    email: EmailStr
    password: str


class EstablishmentOut(BaseModel):
    id: str
    name: str
    type: str
    email: str
    whatsapp: Optional[str]
    address: Optional[str]
    neighborhood: Optional[str]
    city: Optional[str]
    description: Optional[str]
    tags: list[str]
    opening_hours: Optional[str]
    is_email_verified: bool
    onboarding_completed: bool
    created_at: str


class EstablishmentUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    city: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    opening_hours: Optional[str] = None
    onboarding_completed: Optional[bool] = None

    @field_validator("type")
    @classmethod
    def type_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ESTABLISHMENT_TYPES:
            raise ValueError(f"type deve ser um de: {', '.join(ESTABLISHMENT_TYPES)}")
        return v


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ClientCreate(BaseModel):
    name: str
    contact_phone: Optional[str] = None
    document: Optional[str] = None
    neighborhood: Optional[str] = None
    notes: Optional[str] = None


class ClientOut(BaseModel):
    id: str
    establishment_id: str
    name: str
    contact_phone: Optional[str]
    document: Optional[str]
    neighborhood: Optional[str]
    notes: Optional[str]
    billy_profile_status: str
    created_at: str


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    contact_phone: Optional[str] = None
    document: Optional[str] = None
    neighborhood: Optional[str] = None
    notes: Optional[str] = None


class PetCreate(BaseModel):
    client_id: str
    name: str
    species: str
    breed: Optional[str] = None
    approximate_age: Optional[str] = None
    color: Optional[str] = None
    gender: Optional[str] = "unknown"
    special_characteristics: Optional[str] = None
    weight: Optional[str] = None  # exclusivo do Pro — não existe no Billy App ainda

    @field_validator("species")
    @classmethod
    def species_valid(cls, v: str) -> str:
        return _validate_species(v)

    @field_validator("approximate_age")
    @classmethod
    def approximate_age_valid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_approximate_age(v)

    @field_validator("gender")
    @classmethod
    def gender_valid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_gender(v)


# BIL-40: mesmo shape de PetCreate/ClientCreate, sem client_id (o cliente
# ainda não existe no momento em que a linha da planilha é parseada) e sem
# pets aninhados dentro de BulkPetInput (fica em BulkClientInput.pets).
# Validators reaproveitados via as mesmas funções soltas de cima — não
# duplica a regra, só a declaração do campo (exigência do pydantic).
class BulkPetInput(BaseModel):
    name: str
    species: str
    breed: Optional[str] = None
    approximate_age: Optional[str] = None
    color: Optional[str] = None
    gender: Optional[str] = "unknown"
    special_characteristics: Optional[str] = None
    weight: Optional[str] = None

    @field_validator("species")
    @classmethod
    def species_valid(cls, v: str) -> str:
        return _validate_species(v)

    @field_validator("approximate_age")
    @classmethod
    def approximate_age_valid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_approximate_age(v)

    @field_validator("gender")
    @classmethod
    def gender_valid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_gender(v)


class BulkClientInput(BaseModel):
    name: str
    contact_phone: Optional[str] = None
    document: Optional[str] = None
    neighborhood: Optional[str] = None
    notes: Optional[str] = None
    # Não valida aqui dentro — ver bulk_import_clients: cada pet é
    # construído/validado individualmente dentro do loop, pra um pet
    # inválido não derrubar a importação inteira.


# Corpo frouxo de propósito (list[dict], não list[BulkClientInput]) — se
# fosse tipado direto, o FastAPI validaria o payload inteiro antes de
# chamar o endpoint, e qualquer item inválido em qualquer lugar do array
# devolveria 422 pro corpo inteiro, sem nunca rodar o loop item a item que
# permite "importa o que deu certo, reporta o resto".
class BulkImportRequest(BaseModel):
    clients: list[dict]


class PetOut(BaseModel):
    id: str
    client_id: str
    name: str
    species: str
    breed: Optional[str]
    approximate_age: Optional[str]
    color: Optional[str]
    gender: Optional[str]
    special_characteristics: Optional[str]
    weight: Optional[str]
    biometry_status: str
    billy_pet_id: Optional[str]
    created_at: str


class PetUpdate(BaseModel):
    name: Optional[str] = None
    species: Optional[str] = None
    breed: Optional[str] = None
    approximate_age: Optional[str] = None
    color: Optional[str] = None
    gender: Optional[str] = None
    special_characteristics: Optional[str] = None
    weight: Optional[str] = None


# BIL-95 — guarda compartilhada no Pro.
class AddGuardianInput(BaseModel):
    client_id: str


class PromoteOwnerInput(BaseModel):
    client_id: str


class AppointmentCreate(BaseModel):
    client_id: str
    pet_id: str
    service_name: str
    service_price: Optional[float] = None
    date: str
    time: str
    status: str = "agendado"
    payment_status: str = "pendente"
    payment_method: Optional[str] = None
    amount: Optional[float] = None
    source: str = "pro"
    notes: Optional[str] = None


class AppointmentOut(BaseModel):
    id: str
    establishment_id: str
    client_id: str
    pet_id: str
    service_name: str
    service_price: Optional[float]
    date: str
    time: str
    status: str
    payment_status: str
    payment_method: Optional[str]
    amount: Optional[float]
    source: str
    notes: Optional[str]
    created_at: str


class AppointmentUpdate(BaseModel):
    status: Optional[str] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    amount: Optional[float] = None
    notes: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None


class ServiceCreate(BaseModel):
    name: str
    duration: Optional[int] = None
    price: Optional[float] = None


class ServiceOut(BaseModel):
    id: str
    establishment_id: str
    name: str
    duration: Optional[int]
    price: Optional[float]
    active: bool
    created_at: str


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    duration: Optional[int] = None
    price: Optional[float] = None
    active: Optional[bool] = None


class ReminderCreate(BaseModel):
    client_id: Optional[str] = None
    pet_id: Optional[str] = None
    type: str
    scheduled_date: str
    message: Optional[str] = None


class ReminderOut(BaseModel):
    id: str
    establishment_id: str
    client_id: Optional[str]
    pet_id: Optional[str]
    type: str
    scheduled_date: str
    message: Optional[str]
    status: str
    created_at: str


class ReminderUpdate(BaseModel):
    status: Optional[str] = None
    message: Optional[str] = None
    scheduled_date: Optional[str] = None


class SubscriptionOut(BaseModel):
    id: str
    plan_id: str
    status: str
    billing_cycle: Optional[str]
    trial_ends_at: Optional[str]
    is_founder: bool
    created_at: str


# ── Serialização ─────────────────────────────────────────────────────────


def _establishment_out(e: Establishment) -> dict:
    return {
        "id": str(e.id),
        "name": e.name,
        "type": e.type,
        "email": e.email,
        "whatsapp": e.whatsapp,
        "address": e.address,
        "neighborhood": e.neighborhood,
        "city": e.city,
        "description": e.description,
        "tags": e.tags or [],
        "opening_hours": e.opening_hours,
        "photo_url": e.photo_url,
        "is_email_verified": e.is_email_verified,
        "onboarding_completed": e.onboarding_completed,
        "created_at": e.created_at.isoformat(),
    }


def _client_out(c: ProClient) -> dict:
    return {
        "id": str(c.id),
        "establishment_id": str(c.establishment_id),
        "name": c.name,
        "contact_phone": c.contact_phone,
        "document": c.document,
        "neighborhood": c.neighborhood,
        "notes": c.notes,
        "billy_profile_status": c.billy_profile_status,
        "created_at": c.created_at.isoformat(),
    }


def _pet_out(p: ProPet) -> dict:
    return {
        "id": str(p.id),
        "client_id": str(p.client_id),
        "name": p.name,
        "species": p.species,
        "breed": p.breed,
        "approximate_age": p.approximate_age,
        "color": p.color,
        "gender": p.gender,
        "special_characteristics": p.special_characteristics,
        "weight": p.weight,
        "biometry_status": p.biometry_status,
        "billy_pet_id": str(p.billy_pet_id) if p.billy_pet_id else None,
        "created_at": p.created_at.isoformat(),
    }


def _guardian_out(g: ProPetGuardian, client: ProClient) -> dict:
    return {
        "id": str(g.id),
        "pet_id": str(g.pet_id),
        "client_id": str(g.client_id),
        "client_name": client.name,
        "client_phone": client.contact_phone,
        "created_at": g.created_at.isoformat(),
    }


def _appointment_out(a: ProAppointment) -> dict:
    return {
        "id": str(a.id),
        "establishment_id": str(a.establishment_id),
        "client_id": str(a.client_id),
        "pet_id": str(a.pet_id),
        "service_name": a.service_name,
        "service_price": a.service_price,
        "date": a.date,
        "time": a.time,
        "status": a.status,
        "payment_status": a.payment_status,
        "payment_method": a.payment_method,
        "amount": a.amount,
        "source": a.source,
        "notes": a.notes,
        "created_at": a.created_at.isoformat(),
    }


def _service_out(s: ProService) -> dict:
    return {
        "id": str(s.id),
        "establishment_id": str(s.establishment_id),
        "name": s.name,
        "duration": s.duration,
        "price": s.price,
        "active": s.active,
        "created_at": s.created_at.isoformat(),
    }


def _reminder_out(r: ProReminder) -> dict:
    return {
        "id": str(r.id),
        "establishment_id": str(r.establishment_id),
        "client_id": str(r.client_id) if r.client_id else None,
        "pet_id": str(r.pet_id) if r.pet_id else None,
        "type": r.type,
        "scheduled_date": r.scheduled_date,
        "message": r.message,
        "status": r.status,
        "created_at": r.created_at.isoformat(),
    }


def _subscription_out(s: ProSubscription) -> dict:
    return {
        "id": str(s.id),
        "plan_id": s.plan_id,
        "status": s.status,
        "billing_cycle": s.billing_cycle,
        "trial_ends_at": s.trial_ends_at.isoformat() if s.trial_ends_at else None,
        "is_founder": s.is_founder,
        "created_at": s.created_at.isoformat(),
    }


# ── Acesso escopado por estabelecimento ─────────────────────────────────


async def _get_client(client_id: UUID, establishment_id: str, db: AsyncSession) -> ProClient:
    result = await db.execute(
        select(ProClient).where(
            ProClient.id == client_id,
            ProClient.establishment_id == UUID(establishment_id),
        )
    )
    client = result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    return client


async def _get_pet(pet_id: UUID, establishment_id: str, db: AsyncSession) -> ProPet:
    result = await db.execute(
        select(ProPet).where(
            ProPet.id == pet_id,
            ProPet.establishment_id == UUID(establishment_id),
        )
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")
    return pet


async def _get_pet_guardian(pet_id: UUID, client_id: UUID, db: AsyncSession) -> ProPetGuardian:
    result = await db.execute(
        select(ProPetGuardian).where(
            ProPetGuardian.pet_id == pet_id,
            ProPetGuardian.client_id == client_id,
        )
    )
    guardian = result.scalar_one_or_none()
    if guardian is None:
        raise HTTPException(status_code=404, detail="Guardião não encontrado para este pet")
    return guardian


async def _get_appointment(appointment_id: UUID, establishment_id: str, db: AsyncSession) -> ProAppointment:
    result = await db.execute(
        select(ProAppointment).where(
            ProAppointment.id == appointment_id,
            ProAppointment.establishment_id == UUID(establishment_id),
        )
    )
    appointment = result.scalar_one_or_none()
    if appointment is None:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    return appointment


async def _get_service(service_id: UUID, establishment_id: str, db: AsyncSession) -> ProService:
    result = await db.execute(
        select(ProService).where(
            ProService.id == service_id,
            ProService.establishment_id == UUID(establishment_id),
        )
    )
    service = result.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    return service


async def _get_reminder(reminder_id: UUID, establishment_id: str, db: AsyncSession) -> ProReminder:
    result = await db.execute(
        select(ProReminder).where(
            ProReminder.id == reminder_id,
            ProReminder.establishment_id == UUID(establishment_id),
        )
    )
    reminder = result.scalar_one_or_none()
    if reminder is None:
        raise HTTPException(status_code=404, detail="Lembrete não encontrado")
    return reminder


# ── Auth ─────────────────────────────────────────────────────────────────


@router.post("/auth/register", status_code=status.HTTP_201_CREATED, summary="Cadastrar estabelecimento")
async def register(body: EstablishmentRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Establishment).where(Establishment.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    establishment = Establishment(
        name=body.name,
        type=body.type,
        email=body.email,
        hashed_password=hash_password(body.password),
        whatsapp=body.whatsapp,
        city=body.city,
    )
    db.add(establishment)
    await db.commit()
    await db.refresh(establishment)

    # Plano free de entrada por track: 'latido' (autônomo) vs 'coleira' (estabelecimento).
    default_plan_id = "latido" if body.type == "autonomo" else "coleira"
    subscription = ProSubscription(
        establishment_id=establishment.id,
        plan_id=default_plan_id,
        status="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(subscription)
    await db.commit()

    token = create_access_token(
        str(establishment.id),
        extra_claims={"type": "establishment"},
        expires_minutes=settings.pro_access_token_expire_minutes,
    )
    return TokenOut(access_token=token)


@router.post("/auth/login", summary="Login do estabelecimento")
async def login(body: EstablishmentLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Establishment).where(Establishment.email == body.email))
    establishment = result.scalar_one_or_none()

    if not establishment or not verify_password(body.password, establishment.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    token = create_access_token(
        str(establishment.id),
        extra_claims={"type": "establishment"},
        expires_minutes=settings.pro_access_token_expire_minutes,
    )
    return TokenOut(access_token=token)


@router.get("/auth/me", summary="Meu estabelecimento")
async def get_me(
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(select(Establishment).where(Establishment.id == UUID(establishment_id)))
    establishment = result.scalar_one_or_none()
    if not establishment:
        raise HTTPException(status_code=404, detail="Estabelecimento não encontrado")
    return _establishment_out(establishment)


@router.patch("/auth/me", summary="Atualizar dados do estabelecimento")
async def update_me(
    body: EstablishmentUpdate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(select(Establishment).where(Establishment.id == UUID(establishment_id)))
    establishment = result.scalar_one_or_none()
    if not establishment:
        raise HTTPException(status_code=404, detail="Estabelecimento não encontrado")

    if body.name is not None:
        establishment.name = body.name
    if body.type is not None:
        establishment.type = body.type
    if body.whatsapp is not None:
        establishment.whatsapp = body.whatsapp
    if body.address is not None:
        establishment.address = body.address
    if body.neighborhood is not None:
        establishment.neighborhood = body.neighborhood
    if body.city is not None:
        establishment.city = body.city
    if body.description is not None:
        establishment.description = body.description
    if body.tags is not None:
        establishment.tags = body.tags
    if body.opening_hours is not None:
        establishment.opening_hours = body.opening_hours
    if body.onboarding_completed is not None:
        establishment.onboarding_completed = body.onboarding_completed

    await db.commit()
    await db.refresh(establishment)
    return _establishment_out(establishment)


@router.patch("/auth/me/photo", summary="Upload foto do profissional/estabelecimento")
async def update_me_photo(
    photo: UploadFile = File(..., description="Foto do profissional (JPG/PNG)"),
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(select(Establishment).where(Establishment.id == UUID(establishment_id)))
    establishment = result.scalar_one_or_none()
    if not establishment:
        raise HTTPException(status_code=404, detail="Estabelecimento não encontrado")

    image_bytes = await photo.read()
    max_bytes = settings.max_image_size_mb * 1024 * 1024
    if len(image_bytes) > max_bytes:
        raise HTTPException(
            status_code=422,
            detail={"error": "IMAGE_TOO_LARGE", "message": f"Imagem maior que {settings.max_image_size_mb}MB"},
        )

    photo_url = await storage.upload_establishment_photo(image_bytes, photo.content_type or "image/jpeg")

    if photo_url:
        establishment.photo_url = photo_url
        await db.commit()
        await db.refresh(establishment)

    return {"photo_url": establishment.photo_url}


# ── Público (sem autenticação) ───────────────────────────────────────────
# BIL-66/Lote B: página pública de perfil (billy-pro). Só campos seguros pra
# exposição sem login — nunca email, endereço completo, CPF/CNPJ. O whatsapp
# volta no JSON (o frontend usa só pra montar o link wa.me, nunca renderiza
# o número como texto solto na página).


def _public_establishment_out(e: Establishment, services: list[ProService], completed_count: int) -> dict:
    return {
        "id": str(e.id),
        "name": e.name,
        "type": e.type,
        "photo_url": e.photo_url,
        "neighborhood": e.neighborhood,
        "opening_hours": e.opening_hours,
        "description": e.description,
        "tags": e.tags or [],
        "whatsapp": e.whatsapp,
        "services": [
            {"id": str(s.id), "name": s.name, "price": s.price, "duration": s.duration}
            for s in services
        ],
        "completed_services_count": completed_count,
    }


@router.get("/public/establishments/{establishment_id}", summary="Perfil público (sem autenticação)")
async def get_public_establishment(establishment_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Establishment).where(
            Establishment.id == establishment_id,
            Establishment.is_active == True,  # noqa: E712
        )
    )
    establishment = result.scalar_one_or_none()
    if establishment is None:
        raise HTTPException(status_code=404, detail="Perfil não encontrado")

    services_result = await db.execute(
        select(ProService).where(
            ProService.establishment_id == establishment_id,
            ProService.active == True,  # noqa: E712
        )
    )
    services = list(services_result.scalars().all())

    completed_count_result = await db.execute(
        select(func.count()).select_from(ProAppointment).where(
            ProAppointment.establishment_id == establishment_id,
            ProAppointment.status == "concluido",
        )
    )
    completed_count = completed_count_result.scalar_one()

    return _public_establishment_out(establishment, services, completed_count)


# ── Clients ──────────────────────────────────────────────────────────────


@router.get("/clients", summary="Listar clientes")
async def list_clients(
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(
        select(ProClient).where(
            ProClient.establishment_id == UUID(establishment_id),
            ProClient.is_active == True,  # noqa: E712
        ).order_by(ProClient.created_at.desc())
    )
    return [_client_out(c) for c in result.scalars().all()]


def _build_client(establishment_id: str, data) -> ProClient:
    """Constrói (sem persistir) um ProClient a partir de qualquer objeto com
    os campos name/contact_phone/document/neighborhood/notes — usado tanto
    pelo create_client quanto pelo loop do bulk-import, mesmo shape de
    campos (ClientCreate e BulkClientInput)."""
    return ProClient(
        establishment_id=UUID(establishment_id),
        name=data.name,
        contact_phone=data.contact_phone,
        document=data.document,
        neighborhood=data.neighborhood,
        notes=data.notes,
    )


def _build_pet(client_id: str, establishment_id: str, data) -> ProPet:
    """Mesma ideia de _build_client, pro pet — client_id vem à parte porque
    PetCreate tem esse campo mas BulkPetInput não (o cliente ainda não
    existe no momento em que a linha da planilha é parseada)."""
    return ProPet(
        client_id=UUID(client_id),
        establishment_id=UUID(establishment_id),
        name=data.name,
        species=data.species,
        breed=data.breed,
        approximate_age=data.approximate_age,
        color=data.color,
        gender=data.gender,
        special_characteristics=data.special_characteristics,
        weight=data.weight,
    )


@router.post("/clients", status_code=status.HTTP_201_CREATED, summary="Criar cliente")
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    client = _build_client(establishment_id, body)
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return _client_out(client)


MAX_BULK_IMPORT_CLIENTS = 500


@router.post("/clients/bulk-import", summary="Importar clientes em lote (BIL-40)")
async def bulk_import_clients(
    body: BulkImportRequest,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    if len(body.clients) > MAX_BULK_IMPORT_CLIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"Máximo de {MAX_BULK_IMPORT_CLIENTS} clientes por importação. Divida o arquivo em partes menores.",
        )

    results = []
    for index, raw_client in enumerate(body.clients):
        # Captura qualquer formato inesperado de linha (não só erro de
        # validação de campo) — uma linha malformada não pode derrubar a
        # importação inteira, é exatamente o problema que esse desenho evita.
        if not isinstance(raw_client, dict):
            results.append({"index": index, "ok": False, "name": "(formato inválido)", "error": "cada cliente deve ser um objeto"})
            continue

        raw_pets = raw_client.get("pets", []) or []
        name_for_error = raw_client.get("name", "(sem nome)")

        try:
            client_input = BulkClientInput(**{k: v for k, v in raw_client.items() if k != "pets"})
        except Exception as e:
            results.append({"index": index, "ok": False, "name": name_for_error, "error": str(e)})
            continue

        client = _build_client(establishment_id, client_input)
        db.add(client)
        await db.flush()  # popula client.id sem commitar ainda — commit só no fim, depois dos pets

        pet_results = []
        for raw_pet in raw_pets:
            pet_name_for_error = raw_pet.get("name", "(sem nome)") if isinstance(raw_pet, dict) else "(sem nome)"
            try:
                if not isinstance(raw_pet, dict):
                    raise ValueError("cada pet deve ser um objeto")
                pet_input = BulkPetInput(**raw_pet)
            except Exception as e:
                pet_results.append({"ok": False, "name": pet_name_for_error, "error": str(e)})
                continue

            _check_breed(pet_input.species, pet_input.breed)
            pet = _build_pet(str(client.id), establishment_id, pet_input)
            db.add(pet)
            await db.flush()  # popula pet.id pro relatório, sem commitar ainda
            pet_results.append({"ok": True, "pet_id": str(pet.id), "name": pet.name})

        await db.commit()
        await db.refresh(client)
        results.append({"index": index, "ok": True, "client_id": str(client.id), "name": client.name, "pets": pet_results})

    return {"results": results}


@router.get("/clients/{client_id}", summary="Detalhe do cliente com pets")
async def get_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    client = await _get_client(client_id, establishment_id, db)
    pets_result = await db.execute(select(ProPet).where(ProPet.client_id == client.id))
    return {
        **_client_out(client),
        "pets": [_pet_out(p) for p in pets_result.scalars().all()],
    }


@router.patch("/clients/{client_id}", summary="Atualizar cliente")
async def update_client(
    client_id: UUID,
    body: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    client = await _get_client(client_id, establishment_id, db)

    if body.name is not None:
        client.name = body.name
    if body.contact_phone is not None:
        client.contact_phone = body.contact_phone
    if body.document is not None:
        client.document = body.document
    if body.neighborhood is not None:
        client.neighborhood = body.neighborhood
    if body.notes is not None:
        client.notes = body.notes

    await db.commit()
    await db.refresh(client)
    return _client_out(client)


@router.delete("/clients/{client_id}", summary="Remover cliente (soft delete)")
async def delete_client(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    client = await _get_client(client_id, establishment_id, db)
    client.is_active = False
    await db.commit()
    return {"message": "Cliente removido"}


# ── Pets ─────────────────────────────────────────────────────────────────


@router.get("/pets/{client_id}", summary="Listar pets de um cliente")
async def list_pets(
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    await _get_client(client_id, establishment_id, db)
    result = await db.execute(select(ProPet).where(ProPet.client_id == client_id))
    return [_pet_out(p) for p in result.scalars().all()]


@router.post("/pets", status_code=status.HTTP_201_CREATED, summary="Criar pet")
async def create_pet(
    body: PetCreate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    await _get_client(UUID(body.client_id), establishment_id, db)
    _check_breed(body.species, body.breed)

    pet = _build_pet(body.client_id, establishment_id, body)
    db.add(pet)
    await db.commit()
    await db.refresh(pet)
    return _pet_out(pet)


@router.patch("/pets/{pet_id}", summary="Atualizar pet")
async def update_pet(
    pet_id: UUID,
    body: PetUpdate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    pet = await _get_pet(pet_id, establishment_id, db)

    if body.name is not None:
        pet.name = body.name
    if body.species is not None:
        if body.species not in PET_SPECIES:
            raise HTTPException(status_code=400, detail=f"species deve ser um de: {', '.join(PET_SPECIES)}")
        pet.species = body.species
    if body.breed is not None:
        _check_breed(body.species or pet.species, body.breed)
        pet.breed = body.breed
    if body.approximate_age is not None:
        if body.approximate_age not in PET_APPROXIMATE_AGES:
            raise HTTPException(
                status_code=400,
                detail=f"approximate_age deve ser um de: {', '.join(PET_APPROXIMATE_AGES)}",
            )
        pet.approximate_age = body.approximate_age
    if body.color is not None:
        pet.color = body.color
    if body.gender is not None:
        if body.gender not in PET_GENDERS:
            raise HTTPException(status_code=400, detail=f"gender deve ser um de: {', '.join(PET_GENDERS)}")
        pet.gender = body.gender
    if body.special_characteristics is not None:
        pet.special_characteristics = body.special_characteristics
    if body.weight is not None:
        pet.weight = body.weight

    await db.commit()
    await db.refresh(pet)
    return _pet_out(pet)


@router.delete("/pets/{pet_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover pet")
async def delete_pet(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    pet = await _get_pet(pet_id, establishment_id, db)

    # BIL-95: pet com guardiões ativos não pode ser apagado direto — precisa
    # remover os guardiões primeiro, ou promover um deles a dono (endpoint
    # promote-owner) antes de tentar de novo.
    guardians_result = await db.execute(
        select(ProPetGuardian).where(ProPetGuardian.pet_id == pet_id)
    )
    if guardians_result.scalars().first() is not None:
        raise HTTPException(
            status_code=409,
            detail="Pet tem guardiões ativos. Remova os guardiões ou promova um deles a dono antes de apagar.",
        )

    await db.delete(pet)
    await db.commit()


# ── Guarda compartilhada (BIL-95) ──────────────────────────────────────────


@router.get("/pet-guardians", summary="Listar todos os vínculos de guarda do estabelecimento")
async def list_all_pet_guardians(
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    # Usado pelo frontend pra montar a lista de Clientes (um cliente precisa
    # aparecer com os pets onde é dono OU guardião) — uma chamada só pro
    # estabelecimento inteiro, não N+1 por pet. Payload mínimo de propósito
    # (só os IDs) — o frontend já tem nome/telefone/etc. via GET /clients e
    # GET /pets/{client_id}, não precisa duplicar aqui.
    result = await db.execute(
        select(ProPetGuardian)
        .join(ProPet, ProPetGuardian.pet_id == ProPet.id)
        .where(ProPet.establishment_id == UUID(establishment_id))
    )
    return [{"pet_id": str(g.pet_id), "client_id": str(g.client_id)} for g in result.scalars().all()]


@router.get("/pets/{pet_id}/guardians", summary="Listar guardiões de um pet")
async def list_pet_guardians(
    pet_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    await _get_pet(pet_id, establishment_id, db)
    result = await db.execute(
        select(ProPetGuardian, ProClient)
        .join(ProClient, ProPetGuardian.client_id == ProClient.id)
        .where(ProPetGuardian.pet_id == pet_id)
    )
    return [_guardian_out(g, c) for g, c in result.all()]


@router.post("/pets/{pet_id}/guardians", status_code=status.HTTP_201_CREATED, summary="Adicionar guardião extra a um pet")
async def add_pet_guardian(
    pet_id: UUID,
    body: AddGuardianInput,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    pet = await _get_pet(pet_id, establishment_id, db)
    client = await _get_client(UUID(body.client_id), establishment_id, db)

    if client.id == pet.client_id:
        raise HTTPException(status_code=400, detail="Este cliente já é o dono principal do pet")

    existing = await db.execute(
        select(ProPetGuardian).where(
            ProPetGuardian.pet_id == pet_id,
            ProPetGuardian.client_id == client.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Este cliente já é guardião deste pet")

    guardian = ProPetGuardian(pet_id=pet_id, client_id=client.id)
    db.add(guardian)
    await db.commit()
    await db.refresh(guardian)
    return _guardian_out(guardian, client)


@router.delete("/pets/{pet_id}/guardians/{client_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover guardião de um pet")
async def remove_pet_guardian(
    pet_id: UUID,
    client_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    await _get_pet(pet_id, establishment_id, db)
    guardian = await _get_pet_guardian(pet_id, client_id, db)
    await db.delete(guardian)
    await db.commit()


@router.patch("/pets/{pet_id}/promote-owner", summary="Trocar o dono principal de um pet")
async def promote_pet_owner(
    pet_id: UUID,
    body: PromoteOwnerInput,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    pet = await _get_pet(pet_id, establishment_id, db)
    new_owner_id = UUID(body.client_id)

    if new_owner_id == pet.client_id:
        raise HTTPException(status_code=400, detail="Este cliente já é o dono principal do pet")

    # Novo dono precisa já ser guardião — este endpoint troca papel entre
    # quem já está ligado ao pet, não adiciona gente nova (isso é o POST
    # /guardians, chamado antes se for o caso).
    guardian = await _get_pet_guardian(pet_id, new_owner_id, db)

    old_owner_id = pet.client_id
    pet.client_id = new_owner_id
    await db.delete(guardian)  # quem virou dono não é mais "guardião" à parte

    # Dono antigo SEMPRE vira guardião — comportamento único e previsível,
    # sem branch condicional aqui dentro. Quem chama este endpoint no fluxo
    # de deletar cliente (ResolveGuardiansModal, no frontend) é responsável
    # por remover esse vínculo logo em seguida, via DELETE
    # /pets/{id}/guardians/{client_id}, já que aquele cliente está prestes a
    # ser removido de verdade — a decisão de limpar ou não fica em quem
    # chama, não escondida aqui.
    db.add(ProPetGuardian(pet_id=pet_id, client_id=old_owner_id))

    await db.commit()
    await db.refresh(pet)
    return _pet_out(pet)


# ── Appointments ─────────────────────────────────────────────────────────


@router.get("/appointments", summary="Listar agendamentos")
async def list_appointments(
    date: Optional[str] = Query(None, description="Filtrar por data YYYY-MM-DD"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrar por status"),
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    query = select(ProAppointment).where(ProAppointment.establishment_id == UUID(establishment_id))
    if date is not None:
        query = query.where(ProAppointment.date == date)
    if status_filter is not None:
        query = query.where(ProAppointment.status == status_filter)

    result = await db.execute(query.order_by(ProAppointment.date, ProAppointment.time))
    return [_appointment_out(a) for a in result.scalars().all()]


@router.post("/appointments", status_code=status.HTTP_201_CREATED, summary="Criar agendamento")
async def create_appointment(
    body: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    await _get_client(UUID(body.client_id), establishment_id, db)
    await _get_pet(UUID(body.pet_id), establishment_id, db)
    _check_not_past(body.date, body.time)
    await _check_services_per_day_limit(establishment_id, body.date, db)

    appointment = ProAppointment(
        establishment_id=UUID(establishment_id),
        client_id=UUID(body.client_id),
        pet_id=UUID(body.pet_id),
        service_name=body.service_name,
        service_price=body.service_price,
        date=body.date,
        time=body.time,
        status=body.status,
        payment_status=body.payment_status,
        payment_method=body.payment_method,
        amount=body.amount,
        source=body.source,
        notes=body.notes,
    )
    db.add(appointment)
    await db.commit()
    await db.refresh(appointment)
    return _appointment_out(appointment)


@router.patch("/appointments/{appointment_id}", summary="Atualizar status/pagamento do agendamento")
async def update_appointment(
    appointment_id: UUID,
    body: AppointmentUpdate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    appointment = await _get_appointment(appointment_id, establishment_id, db)

    if body.date is not None or body.time is not None:
        new_date = body.date if body.date is not None else appointment.date
        new_time = body.time if body.time is not None else appointment.time
        _check_not_past(new_date, new_time)

    if body.status is not None:
        appointment.status = body.status
    if body.payment_status is not None:
        appointment.payment_status = body.payment_status
    if body.payment_method is not None:
        appointment.payment_method = body.payment_method
    if body.amount is not None:
        appointment.amount = body.amount
    if body.notes is not None:
        appointment.notes = body.notes
    if body.date is not None:
        appointment.date = body.date
    if body.time is not None:
        appointment.time = body.time

    await db.commit()
    await db.refresh(appointment)
    return _appointment_out(appointment)


@router.delete("/appointments/{appointment_id}", summary="Cancelar agendamento")
async def cancel_appointment(
    appointment_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    appointment = await _get_appointment(appointment_id, establishment_id, db)
    appointment.status = "cancelado"
    await db.commit()
    await db.refresh(appointment)
    return _appointment_out(appointment)


# ── Services ─────────────────────────────────────────────────────────────


@router.get("/services", summary="Listar serviços ativos")
async def list_services(
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(
        select(ProService).where(
            ProService.establishment_id == UUID(establishment_id),
            ProService.active == True,  # noqa: E712
        )
    )
    return [_service_out(s) for s in result.scalars().all()]


@router.post("/services", status_code=status.HTTP_201_CREATED, summary="Criar serviço")
async def create_service(
    body: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    service = ProService(
        establishment_id=UUID(establishment_id),
        name=body.name,
        duration=body.duration,
        price=body.price,
    )
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return _service_out(service)


@router.patch("/services/{service_id}", summary="Atualizar serviço")
async def update_service(
    service_id: UUID,
    body: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    service = await _get_service(service_id, establishment_id, db)

    if body.name is not None:
        service.name = body.name
    if body.duration is not None:
        service.duration = body.duration
    if body.price is not None:
        service.price = body.price
    if body.active is not None:
        service.active = body.active

    await db.commit()
    await db.refresh(service)
    return _service_out(service)


@router.delete("/services/{service_id}", summary="Remover serviço (soft delete)")
async def delete_service(
    service_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    service = await _get_service(service_id, establishment_id, db)
    service.active = False
    await db.commit()
    return {"message": "Serviço removido"}


# ── Reminders ────────────────────────────────────────────────────────────


@router.get("/reminders", summary="Listar lembretes")
async def list_reminders(
    status_filter: Optional[str] = Query(None, alias="status", description="Filtrar por status"),
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    query = select(ProReminder).where(ProReminder.establishment_id == UUID(establishment_id))
    if status_filter is not None:
        query = query.where(ProReminder.status == status_filter)

    result = await db.execute(query.order_by(ProReminder.scheduled_date))
    return [_reminder_out(r) for r in result.scalars().all()]


@router.post("/reminders", status_code=status.HTTP_201_CREATED, summary="Criar lembrete")
async def create_reminder(
    body: ReminderCreate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    if body.client_id is not None:
        await _get_client(UUID(body.client_id), establishment_id, db)
    if body.pet_id is not None:
        await _get_pet(UUID(body.pet_id), establishment_id, db)

    reminder = ProReminder(
        establishment_id=UUID(establishment_id),
        client_id=UUID(body.client_id) if body.client_id else None,
        pet_id=UUID(body.pet_id) if body.pet_id else None,
        type=body.type,
        scheduled_date=body.scheduled_date,
        message=body.message,
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return _reminder_out(reminder)


@router.patch("/reminders/{reminder_id}", summary="Atualizar lembrete")
async def update_reminder(
    reminder_id: UUID,
    body: ReminderUpdate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    reminder = await _get_reminder(reminder_id, establishment_id, db)

    if body.status is not None:
        reminder.status = body.status
    if body.message is not None:
        reminder.message = body.message
    if body.scheduled_date is not None:
        reminder.scheduled_date = body.scheduled_date

    await db.commit()
    await db.refresh(reminder)
    return _reminder_out(reminder)


@router.delete("/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remover lembrete")
async def delete_reminder(
    reminder_id: UUID,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    reminder = await _get_reminder(reminder_id, establishment_id, db)
    await db.delete(reminder)
    await db.commit()


# ── Subscription ─────────────────────────────────────────────────────────


@router.get("/subscription", summary="Plano atual do estabelecimento")
async def get_subscription(
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(
        select(ProSubscription).where(ProSubscription.establishment_id == UUID(establishment_id))
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise HTTPException(status_code=404, detail="Assinatura não encontrada")
    return _subscription_out(subscription)


# ── Billy Connect ────────────────────────────────────────────────────────


@router.get("/billy-connect/pet", summary="Buscar pet via billy_pet_id (ponte com o Billy App)")
async def billy_connect_pet(
    billy_pet_id: UUID = Query(..., description="ID do pet no Billy App"),
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(
        select(ProPet).where(
            ProPet.billy_pet_id == billy_pet_id,
            ProPet.establishment_id == UUID(establishment_id),
        )
    )
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")

    client_result = await db.execute(select(ProClient).where(ProClient.id == pet.client_id))
    client = client_result.scalar_one_or_none()

    return {
        "pet": _pet_out(pet),
        "client": {
            "name": client.name if client else None,
            "contact_phone": client.contact_phone if client else None,
        },
    }


_firebase_initialized = False


def _get_firebase():
    global _firebase_initialized
    if _firebase_initialized:
        return True
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
        logger.warning("Firebase init failed in pro: %s", e)
        return False


def _normalize_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    # remove DDI 55 quando presente, pra tolerar formatos com/sem código
    # de país batendo entre o cadastro do Pro e o cadastro do App
    if digits.startswith("55") and len(digits) > 11:
        digits = digits[2:]
    return digits


class BillyConnectRequestBody(BaseModel):
    pro_pet_id: str


@router.post(
    "/billy-connect/request",
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar conexão Billy Connect (push nativo pro tutor confirmar)",
)
async def billy_connect_request(
    body: BillyConnectRequestBody,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    try:
        pro_pet_uuid = UUID(body.pro_pet_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="pro_pet_id inválido")

    pet_result = await db.execute(
        select(ProPet).where(ProPet.id == pro_pet_uuid, ProPet.establishment_id == UUID(establishment_id))
    )
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado")

    if pet.billy_pet_id is not None:
        raise HTTPException(status_code=409, detail="Este pet já está conectado ao Billy App")

    client_result = await db.execute(select(ProClient).where(ProClient.id == pet.client_id))
    client = client_result.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")

    client_phone = _normalize_phone(client.contact_phone)
    if not client_phone:
        raise HTTPException(status_code=404, detail="Cliente ainda não tem o Billy App")

    # Reaproveita convite pendente e não-expirado já existente, em vez de
    # empilhar convites/push duplicados a cada clique no botão.
    existing_result = await db.execute(
        select(ProConnectInvite).where(
            ProConnectInvite.pro_pet_id == pro_pet_uuid,
            ProConnectInvite.status == "pending",
            ProConnectInvite.expires_at > datetime.now(timezone.utc),
        )
    )
    existing_invite = existing_result.scalar_one_or_none()
    if existing_invite is not None:
        return {"id": str(existing_invite.id), "status": existing_invite.status,
                "expires_at": existing_invite.expires_at.isoformat()}

    users_result = await db.execute(select(User).where(User.fcm_token.isnot(None)))
    app_user = next(
        (u for u in users_result.scalars().all() if _normalize_phone(u.contact_phone) == client_phone),
        None,
    )
    if app_user is None:
        raise HTTPException(status_code=404, detail="Cliente ainda não tem o Billy App")

    establishment_result = await db.execute(
        select(Establishment).where(Establishment.id == UUID(establishment_id))
    )
    establishment = establishment_result.scalar_one_or_none()

    invite = ProConnectInvite(
        pro_pet_id=pro_pet_uuid,
        pro_client_id=client.id,
        establishment_id=UUID(establishment_id),
        app_user_id=app_user.id,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
    )
    db.add(invite)
    client.billy_profile_status = "convite_pendente"
    await db.commit()
    await db.refresh(invite)

    if _get_firebase():
        try:
            messaging.send(
                messaging.Message(
                    notification=messaging.Notification(
                        title=establishment.name if establishment else "Billy",
                        body=f"quer conectar {pet.name} ao Billy. Toque para confirmar.",
                    ),
                    data={"type": "billy_connect_request", "invite_id": str(invite.id)},
                    token=app_user.fcm_token,
                )
            )
        except Exception as e:
            logger.warning("FCM send failed (billy-connect): %s", e)

    return {"id": str(invite.id), "status": invite.status, "expires_at": invite.expires_at.isoformat()}


# ── Central de ajuda — BIL-102 ───────────────────────────────────────────


class SupportContactBody(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Mensagem não pode ser vazia")
        return v


async def _send_support_email(establishment_name: str, establishment_email: str, message: str) -> None:
    html_body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:0 auto;color:#3D2314;">
      <div style="background:#C98A4B;padding:16px 20px;border-radius:12px 12px 0 0;">
        <span style="color:white;font-size:18px;font-weight:800;">🐾 billy pro — central de ajuda</span>
      </div>
      <div style="background:#FAF8F5;padding:24px 20px;border-radius:0 0 12px 12px;border:1px solid #EDE5DB;border-top:none;">
        <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
          <tr><td style="padding:6px 0;color:#8B6F5E;font-size:13px;width:90px;">Estabelecimento</td><td style="font-weight:700;">{establishment_name}</td></tr>
          <tr><td style="padding:6px 0;color:#8B6F5E;font-size:13px;">E-mail</td><td style="font-weight:700;">{establishment_email}</td></tr>
        </table>
        <p style="color:#8B6F5E;font-size:13px;margin:0 0 6px;">Mensagem:</p>
        <p style="white-space:pre-wrap;margin:0;">{message}</p>
      </div>
    </div>
    """
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from_email,
                "to": ["suporte@appbilly.com.br"],
                "reply_to": establishment_email,
                "subject": f"Dúvida — Central de Ajuda ({establishment_name})",
                "html": html_body,
            },
            timeout=10,
        )


@router.post("/support/contact", summary="Enviar dúvida pra Central de Ajuda")
async def support_contact(
    body: SupportContactBody,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    result = await db.execute(select(Establishment).where(Establishment.id == UUID(establishment_id)))
    establishment = result.scalar_one_or_none()
    if establishment is None:
        raise HTTPException(status_code=404, detail="Estabelecimento não encontrado")

    if settings.resend_api_key:
        try:
            await _send_support_email(establishment.name, establishment.email, body.message)
        except Exception as e:
            logger.warning("support contact email failed: %s", e)
            raise HTTPException(status_code=502, detail="Não foi possível enviar sua mensagem. Tente novamente.")

    return {"ok": True}


# ── Avaliação / feedback — BIL-103 ───────────────────────────────────────
# TODO(BIL-103): trigger de reforço — pedir avaliação depois do 5º
# agendamento concluído. Só a ideia registrada, não implementado ainda
# (fora de escopo do MVP).


class FeedbackBody(BaseModel):
    rating: int
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_in_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("rating deve ser entre 1 e 5")
        return v


@router.post("/feedback", status_code=status.HTTP_201_CREATED, summary="Enviar avaliação do Billy Pro")
async def create_feedback(
    body: FeedbackBody,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    feedback = ProFeedback(
        establishment_id=UUID(establishment_id),
        rating=body.rating,
        comment=body.comment.strip() if body.comment else None,
    )
    db.add(feedback)
    await db.commit()

    return {"ok": True}
