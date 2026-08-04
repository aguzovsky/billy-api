#!/usr/bin/env python3
"""Seed idempotente de contas de teste (BIL-148) em staging.

Cria (ou reseta pro estado esperado, se já existirem) contas sintéticas
pra smoke test manual do Billy Connect:

  - 1 profissional autônomo (Billy Pro): smoketest.pro.bil148@example.com.
  - N pares tutor+cliente, cada um provando um fluxo diferente:
      par 1 — smoketest.tutor.bil148@example.com + pet "Rex" +
              "Cliente Teste BIL148" (telefone 11972793795).
              Prova o fluxo principal (convite -> aceite -> vínculo) —
              NÃO MEXER nos dados desse par depois de já confirmado,
              ele é a prova do fluxo principal.
      par 2 — smoketest.tutor2.bil148@example.com + pet "Bolt" +
              "Cliente Teste BIL148 v2" (telefone 11972793796).
              Par isolado pra testar recusa + reenvio sem tocar no par 1.

Nenhuma conta fica travada em gate de verificação (email/KYC) — os
campos são setados direto no banco, sem passar pelos fluxos reais de
e-mail/Didit, porque servem só pra destravar teste manual.

Como rodar (SEMPRE via `railway run`, nunca com DATABASE_URL na mão):

    railway run --service Postgres-_J0x --environment staging -- \\
        python scripts/seed_staging_test_accounts.py

Por que `--service Postgres-_J0x` e não `--service billy-api`: o
DATABASE_URL do billy-api usa o host interno (postgres-j0x.railway.internal),
que só resolve de dentro da rede do Railway — de uma máquina local dá
erro de DNS. O serviço Postgres-_J0x expõe DATABASE_PUBLIC_URL (proxy
público, alcançável daqui), apontando pro MESMO banco. O script usa
DATABASE_PUBLIC_URL quando disponível, com fallback pra DATABASE_URL.

Staging tem dois serviços Postgres no mesmo projeto Railway (achado da
sessão BIL-148: copiar a URL pública de um deles à mão levou a rodar
migration contra o serviço errado, "Postgres", que não é o que o
billy-api de fato usa). Rodar via `railway run --service Postgres-_J0x`
elimina essa ambiguidade — injeta a variável do serviço certo, sem URL
escolhida manualmente.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _assert_staging_and_resolve_db_url() -> str:
    """Aborta a menos que o processo tenha sido claramente lançado contra
    staging. RAILWAY_ENVIRONMENT_NAME só existe quando rodado via
    `railway run`/`railway up` — rodar o script "pelado" (sem railway run)
    já falha aqui, o que é o comportamento certo: não existe fallback
    silencioso pra nenhum banco.

    Resolve a URL de conexão preferindo DATABASE_PUBLIC_URL (proxy público,
    alcançável de fora do Railway) sobre DATABASE_URL (host interno, só
    resolve de dentro da rede do Railway) — ver docstring do módulo."""
    env_name = os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_ENVIRONMENT")
    if env_name != "staging":
        sys.exit(
            "ABORTADO: RAILWAY_ENVIRONMENT_NAME/RAILWAY_ENVIRONMENT = "
            f"{env_name!r} (esperado exatamente 'staging').\n"
            "Este script só roda via `railway run`, pra herdar a variável do "
            "serviço/ambiente linkado — nunca com DATABASE_URL setado "
            "manualmente. Rode:\n\n"
            "  railway run --service Postgres-_J0x --environment staging -- "
            "python scripts/seed_staging_test_accounts.py\n"
        )

    db_url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL", "")
    if not db_url:
        sys.exit(
            "ABORTADO: nem DATABASE_PUBLIC_URL nem DATABASE_URL estão setados "
            "no ambiente (railway run deveria ter injetado isso)."
        )
    if "prod" in db_url.lower():
        sys.exit("ABORTADO: a URL resolvida contém 'prod' — parece apontar pra produção. Cancelando por segurança.")

    if db_url.startswith("postgresql://") or db_url.startswith("postgres://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    host = db_url.split("@")[-1].split("/")[0] if "@" in db_url else "?"
    print(f"[seed] ambiente=staging confirmado, conectando em host={host}")
    return db_url


os.environ["DATABASE_URL"] = _assert_staging_and_resolve_db_url()

import asyncio  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

from sqlalchemy import select  # noqa: E402

import api.main  # noqa: E402,F401 — importa todos os routers/models pra registrar relationships no Base
from api.core.database import AsyncSessionLocal  # noqa: E402
from api.core.security import hash_password  # noqa: E402
from api.models.pet import Pet, User  # noqa: E402
from api.models.pro import Establishment, ProClient, ProPet, ProSubscription  # noqa: E402

PRO_EMAIL = "smoketest.pro.bil148@example.com"
PRO_PASSWORD = "Teste@123"
PRO_NAME = "Maria Teste BIL148"

TUTORS = [
    dict(
        name="Tutor Teste BIL148",
        email="smoketest.tutor.bil148@example.com",
        phone="11972793795",
        password="Teste@123",
        pet_name="Rex",
        client_name="Cliente Teste BIL148",
    ),
    dict(
        name="Tutor Teste BIL148 v2",
        email="smoketest.tutor2.bil148@example.com",
        phone="11972793796",
        password="Teste@123",
        pet_name="Bolt",
        client_name="Cliente Teste BIL148 v2",
    ),
]


async def seed_tutor(db, spec: dict) -> tuple[User, Pet]:
    result = await db.execute(select(User).where(User.email == spec["email"]))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            name=spec["name"],
            email=spec["email"],
            hashed_password=hash_password(spec["password"]),
            contact_phone=spec["phone"],
            email_verified=True,
            email_verified_at=datetime.now(timezone.utc),
        )
        db.add(user)
    else:
        user.hashed_password = hash_password(spec["password"])
        user.contact_phone = spec["phone"]
        user.email_verified = True
        user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)

    await db.flush()

    pet_result = await db.execute(
        select(Pet).where(Pet.owner_id == user.id, Pet.name == spec["pet_name"])
    )
    pet = pet_result.scalar_one_or_none()
    if pet is None:
        pet = Pet(
            name=spec["pet_name"],
            species="dog",
            breed="SRD",
            owner_id=user.id,
            status="home",
            source="owner_registered",
        )
        db.add(pet)
    else:
        pet.species = "dog"
        pet.breed = "SRD"

    await db.flush()
    return user, pet


async def seed_establishment(db) -> Establishment:
    result = await db.execute(select(Establishment).where(Establishment.email == PRO_EMAIL))
    establishment = result.scalar_one_or_none()

    if establishment is None:
        establishment = Establishment(
            name=PRO_NAME,
            type="autonomo",
            email=PRO_EMAIL,
            hashed_password=hash_password(PRO_PASSWORD),
            terms_accepted_at=datetime.now(timezone.utc),
            terms_version="1.0",
            is_email_verified=True,
            kyc_status="aprovado",
        )
        db.add(establishment)
    else:
        establishment.name = PRO_NAME
        establishment.type = "autonomo"
        establishment.hashed_password = hash_password(PRO_PASSWORD)
        establishment.is_email_verified = True
        establishment.email_verification_code = None
        establishment.email_verification_code_expires = None
        establishment.kyc_status = "aprovado"
        establishment.terms_accepted_at = establishment.terms_accepted_at or datetime.now(timezone.utc)
        establishment.terms_version = establishment.terms_version or "1.0"

    await db.flush()

    sub_result = await db.execute(
        select(ProSubscription).where(ProSubscription.establishment_id == establishment.id)
    )
    subscription = sub_result.scalar_one_or_none()
    if subscription is None:
        subscription = ProSubscription(
            establishment_id=establishment.id,
            plan_id="latido",
            status="trial",
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=14),
        )
        db.add(subscription)

    await db.flush()
    return establishment


async def seed_pro_client(db, establishment: Establishment, spec: dict) -> tuple[ProClient, ProPet]:
    client_result = await db.execute(
        select(ProClient).where(
            ProClient.establishment_id == establishment.id,
            ProClient.contact_phone == spec["phone"],
        )
    )
    client = client_result.scalar_one_or_none()
    if client is None:
        client = ProClient(
            establishment_id=establishment.id,
            name=spec["client_name"],
            contact_phone=spec["phone"],
        )
        db.add(client)
    else:
        client.name = spec["client_name"]

    await db.flush()

    pet_result = await db.execute(
        select(ProPet).where(ProPet.client_id == client.id, ProPet.name == spec["pet_name"])
    )
    pro_pet = pet_result.scalar_one_or_none()
    if pro_pet is None:
        pro_pet = ProPet(
            client_id=client.id,
            establishment_id=establishment.id,
            name=spec["pet_name"],
            species="dog",
            breed="SRD",
        )
        db.add(pro_pet)
    else:
        pro_pet.species = "dog"
        pro_pet.breed = "SRD"

    await db.flush()
    return client, pro_pet


async def main() -> None:
    async with AsyncSessionLocal() as db:
        tutors = [await seed_tutor(db, spec) for spec in TUTORS]
        establishment = await seed_establishment(db)
        pro_clients = [await seed_pro_client(db, establishment, spec) for spec in TUTORS]
        await db.commit()

        await db.refresh(establishment)
        for user, pet in tutors:
            await db.refresh(user)
            await db.refresh(pet)
        for client, pro_pet in pro_clients:
            await db.refresh(client)
            await db.refresh(pro_pet)

    print("=== Profissional (Billy Pro, autônomo) ===")
    print(f"  id: {establishment.id}")
    print(f"  email: {establishment.email}  (is_email_verified={establishment.is_email_verified})")
    print(f"  kyc_status: {establishment.kyc_status}")
    print()

    for spec, (user, pet), (client, pro_pet) in zip(TUTORS, tutors, pro_clients):
        print(f"=== Par: {spec['client_name']} ===")
        print(f"  tutor id: {user.id}")
        print(f"  tutor email: {user.email}  (email_verified={user.email_verified})")
        print(f"  tutor contact_phone: {user.contact_phone}")
        print(f"  pet do tutor: {pet.name} ({pet.species}/{pet.breed})  id={pet.id}")
        print(f"  cliente: {client.name}  contact_phone={client.contact_phone}  id={client.id}")
        print(f"  pet do cliente: {pro_pet.name} ({pro_pet.species}/{pro_pet.breed})  id={pro_pet.id}")
        print()

    print("Todos os logins prontos, sem gate pendente (email/KYC já marcados).")


if __name__ == "__main__":
    asyncio.run(main())
