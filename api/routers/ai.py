from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.pet import Pet
from api.models.reminder import HealthLog, Reminder, REMINDER_TYPES
from api.services import assistant_service
from api.services import reminder_service

router = APIRouter(prefix="/ai", tags=["ai"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ReminderCreate(BaseModel):
    pet_id: str
    type: str
    title: str
    description: Optional[str] = None
    due_date: datetime
    recurrence_days: Optional[int] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    recurrence_days: Optional[int] = None
    completed: Optional[bool] = None


class HealthLogCreate(BaseModel):
    pet_id: str
    content: str


# ── Serializers ──────────────────────────────────────────────────────────────

def _serialize_reminder(r: Reminder) -> dict:
    return {
        "id": str(r.id),
        "pet_id": str(r.pet_id),
        "user_id": str(r.user_id),
        "type": r.type,
        "title": r.title,
        "description": r.description,
        "due_date": r.due_date.isoformat(),
        "recurrence_days": r.recurrence_days,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat(),
    }


def _serialize_log(log: HealthLog) -> dict:
    return {
        "id": str(log.id),
        "pet_id": str(log.pet_id),
        "user_id": str(log.user_id),
        "content": log.content,
        "created_at": log.created_at.isoformat(),
    }


# ── Chat ─────────────────────────────────────────────────────────────────────

@router.post("/chat", summary="Conversar com o assistente Billy AI")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    for msg in body.messages:
        if msg.role not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail="role deve ser 'user' ou 'assistant'")

    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    reply = await assistant_service.chat(user_id, messages, db)
    return {"reply": reply}


# ── Reminders ────────────────────────────────────────────────────────────────

@router.get("/reminders", summary="Listar lembretes do usuário")
async def list_reminders(
    filter: str = "all",  # all | due_soon | completed
    pet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    conditions = [Reminder.user_id == UUID(user_id)]

    if pet_id:
        conditions.append(Reminder.pet_id == UUID(pet_id))

    if filter == "completed":
        conditions.append(Reminder.completed_at.isnot(None))
    elif filter == "due_soon":
        from datetime import timedelta, timezone
        from datetime import datetime as _dt
        deadline = _dt.now(timezone.utc) + timedelta(days=7)
        conditions.append(Reminder.due_date <= deadline)
        conditions.append(Reminder.completed_at.is_(None))
    else:
        conditions.append(Reminder.completed_at.is_(None))

    result = await db.execute(
        select(Reminder).where(and_(*conditions)).order_by(Reminder.due_date)
    )
    return [_serialize_reminder(r) for r in result.scalars().all()]


@router.post("/reminders", status_code=status.HTTP_201_CREATED, summary="Criar lembrete")
async def create_reminder(
    body: ReminderCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    if body.type not in REMINDER_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"type deve ser um de: {', '.join(REMINDER_TYPES)}",
        )

    pet_result = await db.execute(
        select(Pet).where(Pet.id == UUID(body.pet_id), Pet.owner_id == UUID(user_id))
    )
    if pet_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado ou não pertence a você")

    reminder = Reminder(
        pet_id=UUID(body.pet_id),
        user_id=UUID(user_id),
        type=body.type,
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        recurrence_days=body.recurrence_days,
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return _serialize_reminder(reminder)


@router.patch("/reminders/{reminder_id}", summary="Atualizar lembrete ou marcar como feito")
async def update_reminder(
    reminder_id: str,
    body: ReminderUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    if body.completed:
        updated = await reminder_service.mark_complete(db, UUID(reminder_id), user_id)
        if updated is None:
            raise HTTPException(status_code=404, detail="Lembrete não encontrado")
        return _serialize_reminder(updated)

    result = await db.execute(
        select(Reminder).where(
            and_(Reminder.id == UUID(reminder_id), Reminder.user_id == UUID(user_id))
        )
    )
    reminder = result.scalar_one_or_none()
    if reminder is None:
        raise HTTPException(status_code=404, detail="Lembrete não encontrado")

    if body.title is not None:
        reminder.title = body.title
    if body.description is not None:
        reminder.description = body.description
    if body.due_date is not None:
        reminder.due_date = body.due_date
    if body.recurrence_days is not None:
        reminder.recurrence_days = body.recurrence_days

    await db.commit()
    await db.refresh(reminder)
    return _serialize_reminder(reminder)


@router.delete("/reminders/{reminder_id}", summary="Remover lembrete")
async def delete_reminder(
    reminder_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(Reminder).where(
            and_(Reminder.id == UUID(reminder_id), Reminder.user_id == UUID(user_id))
        )
    )
    reminder = result.scalar_one_or_none()
    if reminder is None:
        raise HTTPException(status_code=404, detail="Lembrete não encontrado")

    await db.delete(reminder)
    await db.commit()
    return {"status": "deleted"}


# ── Health Log ───────────────────────────────────────────────────────────────

@router.post("/health-log", status_code=status.HTTP_201_CREATED, summary="Salvar entrada no diário de saúde")
async def create_health_log(
    body: HealthLogCreate,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(
        select(Pet).where(Pet.id == UUID(body.pet_id), Pet.owner_id == UUID(user_id))
    )
    if pet_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado ou não pertence a você")

    log = HealthLog(
        pet_id=UUID(body.pet_id),
        user_id=UUID(user_id),
        content=body.content,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return _serialize_log(log)


@router.get("/health-log/{pet_id}", summary="Histórico do diário de saúde do pet")
async def get_health_log(
    pet_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    pet_result = await db.execute(
        select(Pet).where(Pet.id == UUID(pet_id), Pet.owner_id == UUID(user_id))
    )
    if pet_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Pet não encontrado ou não pertence a você")

    result = await db.execute(
        select(HealthLog)
        .where(and_(HealthLog.pet_id == UUID(pet_id), HealthLog.user_id == UUID(user_id)))
        .order_by(HealthLog.created_at.desc())
        .limit(20)
    )
    return [_serialize_log(log) for log in result.scalars().all()]
