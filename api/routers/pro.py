import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import (
    create_access_token,
    get_current_establishment_id,
    hash_password,
    verify_password,
)
from api.data.pet_breeds import BREEDS_BY_SPECIES
from api.models.pro import (
    Establishment,
    ProAppointment,
    ProClient,
    ProPet,
    ProReminder,
    ProService,
    ProSubscription,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pro", tags=["pro"])

ESTABLISHMENT_TYPES = ["clinica", "petshop", "hotel", "daycare", "autonomo", "misto"]
PET_SPECIES = ["dog", "cat"]  # igual ao Billy App
PET_APPROXIMATE_AGES = ["puppy", "young", "adult", "senior"]
PET_GENDERS = ["male", "female", "unknown"]


def _check_breed(species: str, breed: Optional[str]) -> None:
    """Valida breed contra a lista fixa por espécie. Não bloqueia o cadastro
    ainda — só loga um warning quando não bate, igual pedido no alinhamento inicial."""
    if not breed:
        return
    valid_breeds = BREEDS_BY_SPECIES.get(species, [])
    if breed not in valid_breeds:
        logger.warning("breed '%s' não está na lista conhecida para species '%s'", breed, species)


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
    city: Optional[str]
    is_email_verified: bool
    created_at: str


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
        if v not in PET_SPECIES:
            raise ValueError(f"species deve ser um de: {', '.join(PET_SPECIES)}")
        return v

    @field_validator("approximate_age")
    @classmethod
    def approximate_age_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PET_APPROXIMATE_AGES:
            raise ValueError(f"approximate_age deve ser um de: {', '.join(PET_APPROXIMATE_AGES)}")
        return v

    @field_validator("gender")
    @classmethod
    def gender_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PET_GENDERS:
            raise ValueError(f"gender deve ser um de: {', '.join(PET_GENDERS)}")
        return v


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
        "city": e.city,
        "is_email_verified": e.is_email_verified,
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

    subscription = ProSubscription(
        establishment_id=establishment.id,
        plan_id="coleira",
        status="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(subscription)
    await db.commit()

    token = create_access_token(str(establishment.id), extra_claims={"type": "establishment"})
    return TokenOut(access_token=token)


@router.post("/auth/login", summary="Login do estabelecimento")
async def login(body: EstablishmentLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Establishment).where(Establishment.email == body.email))
    establishment = result.scalar_one_or_none()

    if not establishment or not verify_password(body.password, establishment.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    token = create_access_token(str(establishment.id), extra_claims={"type": "establishment"})
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


@router.post("/clients", status_code=status.HTTP_201_CREATED, summary="Criar cliente")
async def create_client(
    body: ClientCreate,
    db: AsyncSession = Depends(get_db),
    establishment_id: str = Depends(get_current_establishment_id),
):
    client = ProClient(
        establishment_id=UUID(establishment_id),
        name=body.name,
        contact_phone=body.contact_phone,
        document=body.document,
        neighborhood=body.neighborhood,
        notes=body.notes,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return _client_out(client)


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

    pet = ProPet(
        client_id=UUID(body.client_id),
        establishment_id=UUID(establishment_id),
        name=body.name,
        species=body.species,
        breed=body.breed,
        approximate_age=body.approximate_age,
        color=body.color,
        gender=body.gender,
        special_characteristics=body.special_characteristics,
        weight=body.weight,
    )
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
    await db.delete(pet)
    await db.commit()


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
