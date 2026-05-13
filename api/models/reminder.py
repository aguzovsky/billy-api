import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from api.core.database import Base

REMINDER_TYPES = ("vaccine", "medication", "bath", "vet", "deworming", "custom")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(20), nullable=False)  # vaccine | medication | bath | vet | deworming | custom
    title = Column(String(200), nullable=False)
    description = Column(Text)
    due_date = Column(DateTime(timezone=True), nullable=False)
    recurrence_days = Column(Integer)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HealthLog(Base):
    __tablename__ = "health_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
