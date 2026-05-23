import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.core.database import Base

VALID_CATEGORIES = (
    "vaccine",
    "deworming",
    "flea",
    "consultation",
    "hygiene",
    "exam",
    "other",
)


class HealthEvent(Base):
    __tablename__ = "health_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(
        UUID(as_uuid=True),
        ForeignKey("pets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = Column(String(30), nullable=False)  # VALID_CATEGORIES
    title = Column(String(200), nullable=False)
    date = Column(Date, nullable=False)
    next_date = Column(Date, nullable=True)
    vet_name = Column(String(200), nullable=True)
    clinic = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    proof_url = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    pet = relationship("Pet", back_populates="health_events")
