import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    contact_phone = Column(String(20))
    neighborhood = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    pets = relationship("Pet", back_populates="owner")


class Pet(Base):
    __tablename__ = "pets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    species = Column(String(10), nullable=False)  # 'dog' | 'cat'
    breed = Column(String(100))
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rg_animal_id = Column(String(50))
    status = Column(String(20), default="home")  # 'home' | 'lost' | 'found'
    photo_url = Column(Text)
    # location stored as WKT via raw SQL / PostGIS; see geo_service.py
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="pets")
    biometrics = relationship("Biometric", back_populates="pet", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="pet", cascade="all, delete-orphan")
    guardians = relationship("PetGuardian", back_populates="pet", cascade="all, delete-orphan")
