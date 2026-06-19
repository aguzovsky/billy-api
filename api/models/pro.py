import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api.core.database import Base


class Establishment(Base):
    __tablename__ = "establishments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    type = Column(String(20), nullable=False)  # 'clinica'|'petshop'|'hotel'|'daycare'|'autonomo'|'misto'
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    whatsapp = Column(String(20), nullable=True)
    address = Column(String(255), nullable=True)
    neighborhood = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    description = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_email_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    appointments = relationship("ProAppointment", back_populates="establishment", cascade="all, delete-orphan")
    clients = relationship("ProClient", back_populates="establishment", cascade="all, delete-orphan")
    services = relationship("ProService", back_populates="establishment", cascade="all, delete-orphan")
    reminders = relationship("ProReminder", back_populates="establishment", cascade="all, delete-orphan")
    subscription = relationship("ProSubscription", back_populates="establishment", uselist=False,
                                 cascade="all, delete-orphan")


class ProSubscription(Base):
    __tablename__ = "pro_subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               unique=True, nullable=False)
    # 'latido'|'corrida'|'matilha'|'coleira'|'guia'|'alcateia'|'territorio'
    plan_id = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)  # 'trial'|'active'|'cancelled'|'past_due'
    billing_cycle = Column(String(10), nullable=True)  # 'monthly'|'yearly'
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    is_founder = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    establishment = relationship("Establishment", back_populates="subscription")


class ProClient(Base):
    __tablename__ = "pro_clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=True)
    document = Column(String(20), nullable=True)
    neighborhood = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    billy_user_id = Column(UUID(as_uuid=True), nullable=True)  # ponte futura com User do App
    # 'conectado'|'convite_pendente'|'nao_conectado'
    billy_profile_status = Column(String(20), nullable=False, default="nao_conectado")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    establishment = relationship("Establishment", back_populates="clients")
    pets = relationship("ProPet", back_populates="client", cascade="all, delete-orphan")
    appointments = relationship("ProAppointment", back_populates="client", cascade="all, delete-orphan")


class ProPet(Base):
    __tablename__ = "pro_pets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(UUID(as_uuid=True), ForeignKey("pro_clients.id", ondelete="CASCADE"), nullable=False)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    name = Column(String(100), nullable=False)
    species = Column(String(10), nullable=False)  # 'cachorro'|'gato'|'outro'
    breed = Column(String(100), nullable=True)
    age = Column(String(50), nullable=True)
    weight = Column(String(20), nullable=True)
    temperament = Column(String(255), nullable=True)  # JSON string separado por vírgula
    alerts = Column(String(255), nullable=True)  # JSON string
    billy_pet_id = Column(UUID(as_uuid=True), nullable=True)  # ponte futura com Pet do App
    biometry_status = Column(String(20), nullable=False, default="nao_registrada")  # 'registrada'|'nao_registrada'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    client = relationship("ProClient", back_populates="pets")
    appointments = relationship("ProAppointment", back_populates="pet", cascade="all, delete-orphan")


class ProAppointment(Base):
    __tablename__ = "pro_appointments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("pro_clients.id", ondelete="CASCADE"), nullable=False)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pro_pets.id", ondelete="CASCADE"), nullable=False)
    service_name = Column(String(100), nullable=False)
    service_price = Column(Float, nullable=True)
    date = Column(String(10), nullable=False)  # 'YYYY-MM-DD'
    time = Column(String(5), nullable=False)  # 'HH:MM'
    # 'agendado'|'confirmado'|'em_andamento'|'concluido'|'cancelado'
    status = Column(String(20), nullable=False)
    payment_status = Column(String(20), nullable=False)  # 'pago'|'pendente'|'parcial'|'cancelado'
    payment_method = Column(String(20), nullable=True)  # 'pix'|'credito'|'debito'|'dinheiro'|'indefinido'
    amount = Column(Float, nullable=True)
    source = Column(String(20), nullable=False, default="pro")  # 'billy_app'|'pro'|'whatsapp'|'telefone'
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    establishment = relationship("Establishment", back_populates="appointments")
    client = relationship("ProClient", back_populates="appointments")
    pet = relationship("ProPet", back_populates="appointments")


class ProService(Base):
    __tablename__ = "pro_services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    name = Column(String(100), nullable=False)
    duration = Column(Integer, nullable=True)  # minutos
    price = Column(Float, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    establishment = relationship("Establishment", back_populates="services")


class ProReminder(Base):
    __tablename__ = "pro_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("pro_clients.id", ondelete="CASCADE"), nullable=True)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pro_pets.id", ondelete="CASCADE"), nullable=True)
    type = Column(String(20), nullable=False)  # 'vacina'|'retorno'|'banho'|'medicamento'|'checkin'
    scheduled_date = Column(String(10), nullable=False)  # 'YYYY-MM-DD'
    message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="pendente")  # 'pendente'|'enviado'|'concluido'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    establishment = relationship("Establishment", back_populates="reminders")
