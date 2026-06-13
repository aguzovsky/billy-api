import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, String, Text
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
    reset_token = Column(String(6))
    reset_token_expires = Column(DateTime(timezone=True))
    email_verified = Column(Boolean, nullable=False, default=False)
    email_verified_at = Column(DateTime(timezone=True))
    email_verification_token = Column(String(64))
    email_verification_token_expires = Column(DateTime(timezone=True))
    cpf = Column(String(14), unique=True, nullable=True)
    photo_url = Column(Text, nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    gender = Column(String(20), nullable=True)
    birth_date = Column(Date, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(2), nullable=True)
    whatsapp = Column(String(20), nullable=True)
    fcm_token = Column(String(255), nullable=True)
    deletion_requested = Column(Boolean, nullable=False, default=False)
    deletion_requested_at = Column(DateTime(timezone=True), nullable=True)

    pets = relationship("Pet", back_populates="owner")


class Pet(Base):
    __tablename__ = "pets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    species = Column(String(10), nullable=False)  # 'dog' | 'cat'
    breed = Column(String(100))
    color = Column(String(100))   # NOVO — cor do pelo
    gender = Column(String(10))   # NOVO — 'male' | 'female'
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(String(20), default="home")  # 'home' | 'lost' | 'found'
    source = Column(String(30), nullable=False, default="owner_registered")  # 'owner_registered' | 'found_report'
    photo_url = Column(Text)
    approximate_age = Column(String, nullable=True)
    special_characteristics = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="pets")
    biometrics = relationship("Biometric", back_populates="pet", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="pet", cascade="all, delete-orphan")
    guardians = relationship("PetGuardian", back_populates="pet", cascade="all, delete-orphan")
    photos = relationship("PetPhoto", back_populates="pet", cascade="all, delete-orphan")
    found_contacts = relationship("PetFoundContact", back_populates="pet", cascade="all, delete-orphan")
    health_events = relationship("HealthEvent", back_populates="pet", cascade="all, delete-orphan")
    registrations = relationship("PetRegistration", back_populates="pet", cascade="all, delete-orphan")


class PetFoundContact(Base):
    __tablename__ = "pet_found_contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pets.id", ondelete="CASCADE"), nullable=False)
    finder_name = Column(String(100), nullable=False)
    finder_phone = Column(String(20), nullable=False)
    location_text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    pet = relationship("Pet", back_populates="found_contacts")
