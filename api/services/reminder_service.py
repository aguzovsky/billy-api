from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.reminder import Reminder


async def get_due_reminders(db: AsyncSession, hours_ahead: int = 24) -> list[Reminder]:
    deadline = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    result = await db.execute(
        select(Reminder).where(
            and_(
                Reminder.due_date <= deadline,
                Reminder.completed_at.is_(None),
            )
        ).order_by(Reminder.due_date)
    )
    return result.scalars().all()


async def mark_complete(
    db: AsyncSession, reminder_id: UUID, user_id: str
) -> Reminder | None:
    result = await db.execute(
        select(Reminder).where(
            and_(Reminder.id == reminder_id, Reminder.user_id == UUID(user_id))
        )
    )
    reminder = result.scalar_one_or_none()
    if reminder is None:
        return None

    reminder.completed_at = datetime.now(timezone.utc)

    if reminder.recurrence_days:
        next_due = reminder.due_date + timedelta(days=reminder.recurrence_days)
        next_reminder = Reminder(
            pet_id=reminder.pet_id,
            user_id=reminder.user_id,
            type=reminder.type,
            title=reminder.title,
            description=reminder.description,
            due_date=next_due,
            recurrence_days=reminder.recurrence_days,
        )
        db.add(next_reminder)

    await db.commit()
    await db.refresh(reminder)
    return reminder
