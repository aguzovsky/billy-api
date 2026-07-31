import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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
    # BIL-45 — sem validação de dígito verificador (KYC de verdade é o BIL-46)
    cnpj = Column(String(20), nullable=True)
    cpf = Column(String(14), nullable=True)
    cep = Column(String(10), nullable=True)
    # BIL-46 — KYC via Didit. 'nao_iniciado'|'pendente'|'aprovado'|'reprovado'.
    # Fonte de verdade é o webhook (POST /pro/kyc/webhook), não polling.
    kyc_status = Column(String(20), nullable=False, default="nao_iniciado")
    # session_id do Didit — correlaciona o webhook (que só manda vendor_data,
    # que é o próprio establishment_id) e permite "tentar novamente" saber se
    # já existe sessão em aberto.
    kyc_session_id = Column(String(64), nullable=True)
    # BIL-46/parte-legal — prova de consentimento LGPD (data + versão do
    # texto aceito). Setado junto quando os dois checkboxes (termos+
    # privacidade e consentimento biométrico) são marcados e o usuário
    # avança pro KYC.
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    terms_version = Column(String(20), nullable=True)
    # BIL-44 — verificação de e-mail do Pro, código de 6 dígitos (não link
    # como o Billy App usa em User — roda dentro do fluxo de completar
    # perfil, sem sair pro e-mail). sent_at é só pro cooldown de reenvio.
    email_verification_code = Column(String(6), nullable=True)
    email_verification_code_expires = Column(DateTime(timezone=True), nullable=True)
    email_verification_sent_at = Column(DateTime(timezone=True), nullable=True)
    # BIL-112 — Asaas (cobrança). payment_status é varchar solto de propósito
    # (não enum de banco): o ciclo de vida ainda vai ganhar estados novos
    # (cancelamento, troca de plano) e não vale uma migration a cada um.
    # Estados atuais: 'trial'|'ativo'|'em_carencia'|'inadimplente'|'cancelado'.
    # payment_overdue_since é o âncora dos 7 dias de carência (ver
    # _apply_grace_period_expiry em routers/pro.py) — setado no primeiro
    # PAYMENT_OVERDUE, limpo assim que volta a confirmar pagamento.
    asaas_customer_id = Column(String(32), nullable=True)
    asaas_subscription_id = Column(String(32), nullable=True)
    payment_status = Column(String(20), nullable=False, default="trial")
    payment_overdue_since = Column(DateTime(timezone=True), nullable=True)
    description = Column(String(500), nullable=True)
    tags = Column(ARRAY(String), nullable=False, default=list)
    # JSON string: {"monday": {"open": "08:00", "close": "19:00", "closed": false}, ...}
    opening_hours = Column(Text, nullable=True)
    photo_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_email_verified = Column(Boolean, nullable=False, default=False)
    # BIL-101 — onboarding guiado (4 slides, só track autônomo por enquanto).
    # Dispara no Dashboard enquanto False; PATCH /pro/auth/me marca True.
    onboarding_completed = Column(Boolean, nullable=False, default=False)
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
    contact_phone = Column(String(20), nullable=True)
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
    species = Column(String(10), nullable=False)  # 'dog'|'cat' — igual ao Billy App
    breed = Column(String(100), nullable=True)  # validado contra api/data/pet_breeds.py no router
    approximate_age = Column(String(10), nullable=True)  # 'puppy'|'young'|'adult'|'senior'
    color = Column(String(100), nullable=True)
    gender = Column(String(10), nullable=True, default="unknown")  # 'male'|'female'|'unknown'
    special_characteristics = Column(Text, nullable=True)
    # weight não existe no Billy App ainda — fica órfão até a ponte real ganhar esse campo também
    weight = Column(String(20), nullable=True)
    billy_pet_id = Column(UUID(as_uuid=True), nullable=True)  # ponte futura com Pet do App
    biometry_status = Column(String(20), nullable=False, default="nao_registrada")  # 'registrada'|'nao_registrada'
    photo_url = Column(String(500), nullable=True)  # BIL-98
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True),
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    client = relationship("ProClient", back_populates="pets")
    appointments = relationship("ProAppointment", back_populates="pet", cascade="all, delete-orphan")
    guardians = relationship("ProPetGuardian", back_populates="pet", cascade="all, delete-orphan")


# BIL-95 — guarda compartilhada no Pro. pro_pets.client_id continua o dono
# principal (zero mudança nele); essa tabela só guarda guardiões ADICIONAIS.
# Diferente de pet_guardians (Billy App): sem fluxo de convite por email/
# pending/accepted — aqui o próprio profissional administra direto, faz
# sentido pra quem gerencia o cadastro, não pro guardião sendo convidado.
class ProPetGuardian(Base):
    __tablename__ = "pro_pet_guardians"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pet_id = Column(UUID(as_uuid=True), ForeignKey("pro_pets.id", ondelete="CASCADE"), nullable=False)
    client_id = Column(UUID(as_uuid=True), ForeignKey("pro_clients.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("pet_id", "client_id", name="uq_pro_pet_guardians_pet_client"),)

    pet = relationship("ProPet", back_populates="guardians")
    client = relationship("ProClient")


# BIL-39 — Billy Connect. Ponte real entre um pro_pet/pro_client já
# cadastrado no Pro e o usuário/pet correspondente no Billy App, via
# push nativo (sem QR code). app_user_id/app_pet_id ficam sem FK de
# propósito — cruzam pro Base do App (users/pets), mesmo padrão já
# usado em ProPet.billy_pet_id / ProClient.billy_user_id, que também
# não têm FK. app_pet_id só é preenchido no accept, quando o tutor
# escolhe qual pet é (pode ter mais de um cadastrado no App).
class ProConnectInvite(Base):
    __tablename__ = "pro_connect_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pro_pet_id = Column(UUID(as_uuid=True), ForeignKey("pro_pets.id", ondelete="CASCADE"), nullable=False)
    pro_client_id = Column(UUID(as_uuid=True), ForeignKey("pro_clients.id", ondelete="CASCADE"), nullable=False)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    app_user_id = Column(UUID(as_uuid=True), nullable=True)
    app_pet_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # 'pending'|'confirmed'|'declined'|'expired'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)

    pro_pet = relationship("ProPet")
    pro_client = relationship("ProClient")
    establishment = relationship("Establishment")


# BIL-103 — avaliação/feedback do Pro (MVP). Sem coluna de environment
# de propósito — staging e produção são bancos fisicamente separados,
# a coluna seria redundante.
class ProFeedback(Base):
    __tablename__ = "pro_feedback"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    establishment_id = Column(UUID(as_uuid=True), ForeignKey("establishments.id", ondelete="CASCADE"),
                               nullable=False)
    rating = Column(Integer, nullable=False)  # 1-5, validado no router
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    establishment = relationship("Establishment")


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
