import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.core.database import Base

VALID_REGISTRATION_TYPES = ["MICROCHIP", "SINPATINHAS", "RGA-SP", "SIA-CWB", "OTHER"]


class PetRegistration(Base):
    __tablename__ = "pet_registrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)
    type_label = Column(String(100), nullable=True)
    number = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    pet = relationship("Pet", back_populates="registrations")
