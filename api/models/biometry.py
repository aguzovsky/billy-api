import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Float, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.core.database import Base

EMBEDDING_DIMS = 2048


class Biometric(Base):
    __tablename__ = "biometrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    embedding = Column(Vector(EMBEDDING_DIMS), nullable=False)
    quality_score = Column(Float, nullable=False)
    capture_metadata = Column(JSON)
    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    pet = relationship("Pet", back_populates="biometrics")
