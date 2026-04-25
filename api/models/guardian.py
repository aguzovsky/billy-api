import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.core.database import Base


class PetGuardian(Base):
    __tablename__ = "pet_guardians"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    guardian_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    invited_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), default="pending")  # 'pending' | 'accepted' | 'declined'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    pet = relationship("Pet", back_populates="guardians")
    guardian = relationship("User", foreign_keys=[guardian_id])
    invited_by = relationship("User", foreign_keys=[invited_by_id])
