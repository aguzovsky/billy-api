"""
Integration tests for BIL-106: dado real do pet (App) fluindo pro Pro em
conexões já confirmadas (pro_pets.billy_pet_id preenchido).

Run with: pytest tests/ -v

Requires: docker-compose up -d db redis
          alembic upgrade head

O fluxo de convite/aceite do Billy Connect (billy_connect.py) já tem seu
próprio contrato — aqui só interessa o estado pós-condição que BIL-106
consome (billy_pet_id preenchido), então a conexão é simulada direto no
banco em vez de percorrer o convite completo (que exige KYC aprovado,
e-mail verificado e fcm_token do tutor batendo com o telefone do cliente).
"""

import asyncio
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from api.core.config import settings
from api.main import app

@pytest.fixture(scope="module")
def client():
    # Como context manager: mantém um único event loop vivo pra todas as
    # requisições do módulo. Sem isso, o TestClient abre/fecha um loop novo
    # por request e o pool do engine assíncrono (pool_pre_ping=True em
    # api/core/database.py) quebra tentando reusar uma conexão presa a um
    # loop já fechado ("attached to a different loop") — fragilidade do
    # setup de testes, não deste código.
    with TestClient(app) as c:
        yield c


def _sync_dsn() -> str:
    # asyncpg.connect quer um DSN puro, sem o "+asyncpg" do SQLAlchemy.
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def _link_billy_pet(pro_pet_id: str, billy_pet_id: str) -> None:
    """Simula uma conexão Billy Connect já confirmada, setando
    pro_pets.billy_pet_id direto no banco — o mecanismo de convite/aceite
    (billy_connect.py) já tem sua própria cobertura; aqui só interessa o
    estado pós-condição que BIL-106 consome. Usa uma conexão asyncpg própria
    (fora do engine/pool do app, que já está preso ao loop do TestClient) —
    evita "attached to a different loop" ao chamar asyncio.run() aqui."""
    async def _do():
        conn = await asyncpg.connect(_sync_dsn())
        try:
            await conn.execute(
                "UPDATE pro_pets SET billy_pet_id = $1 WHERE id = $2",
                uuid.UUID(billy_pet_id), uuid.UUID(pro_pet_id),
            )
        finally:
            await conn.close()

    asyncio.run(_do())


def _set_special_characteristics(pet_id: str, value: str) -> None:
    """POST /api/v1/pets aceita special_characteristics no schema mas nunca
    persiste (não está no Pet(...) construído em pets.py) — e não há PATCH
    genérico de pet no App que alcance esse campo. Só dá pra popular direto
    no banco hoje; achado fora do escopo do BIL-106, registrado aqui."""
    async def _do():
        conn = await asyncpg.connect(_sync_dsn())
        try:
            await conn.execute(
                "UPDATE pets SET special_characteristics = $1 WHERE id = $2",
                value, uuid.UUID(pet_id),
            )
        finally:
            await conn.close()

    asyncio.run(_do())


def _add_biometric(pet_id: str) -> None:
    async def _do():
        conn = await asyncpg.connect(_sync_dsn())
        try:
            embedding_literal = "[" + ",".join(["0"] * 2048) + "]"
            await conn.execute(
                "INSERT INTO biometrics (id, pet_id, embedding, quality_score, registered_at) "
                "VALUES ($1, $2, $3::vector, $4, now())",
                uuid.uuid4(), uuid.UUID(pet_id), embedding_literal, 0.9,
            )
        finally:
            await conn.close()

    asyncio.run(_do())


def _unique_email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@billy.app"


@pytest.fixture()
def real_pet(client):
    """Cria um tutor + pet reais no App (dado real que deve fluir pro Pro).
    Sem special_characteristics de propósito — cobre o caso 'conectado sem
    nada preenchido'. Retorna o id do Pet."""
    resp = client.post("/api/v1/auth/register", json={
        "name": "Tutor BIL-106",
        "email": _unique_email("tutor.bil106"),
        "password": "Testpass123",
    })
    assert resp.status_code in (200, 201)
    token = resp.json()["access_token"]

    resp = client.post(
        "/api/v1/pets",
        json={"name": "Rex Real", "species": "dog", "breed": "Labrador"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


SPECIAL_CHARACTERISTICS = "mancha branca na orelha esquerda, alérgico a frango"


@pytest.fixture()
def real_pet_with_characteristics(client):
    """Mesma coisa que real_pet, mas com special_characteristics preenchido
    no App — cobre o caso 'conectado com special_characteristics'. O create
    (POST /api/v1/pets) aceita esse campo no body mas não persiste (ver
    _set_special_characteristics) — populado direto no banco depois."""
    resp = client.post("/api/v1/auth/register", json={
        "name": "Tutor BIL-106 v2",
        "email": _unique_email("tutor2.bil106"),
        "password": "Testpass123",
    })
    assert resp.status_code in (200, 201)
    token = resp.json()["access_token"]

    resp = client.post(
        "/api/v1/pets",
        json={"name": "Bolt Real", "species": "dog", "breed": "Border Collie"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    pet_id = resp.json()["id"]
    _set_special_characteristics(pet_id, SPECIAL_CHARACTERISTICS)
    return pet_id


@pytest.fixture()
def pro_pet(client):
    """Cria estabelecimento + cliente + pet no Pro (etiqueta digitada pelo
    profissional, sem nenhuma conexão ainda). Retorna
    (headers autenticados, client_id, pet_id)."""
    resp = client.post("/api/v1/pro/auth/register", json={
        "name": "Estabelecimento BIL-106",
        "type": "autonomo",
        "email": _unique_email("est.bil106"),
        "password": "Testpass123",
        "accepted_terms": True,
        "terms_version": "v1",
    })
    assert resp.status_code == 201
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    resp = client.post("/api/v1/pro/clients", json={"name": "Cliente BIL-106"}, headers=headers)
    assert resp.status_code == 201
    client_id = resp.json()["id"]

    resp = client.post(
        "/api/v1/pro/pets",
        json={"client_id": client_id, "name": "Rexinho (apelido)", "species": "cat", "gender": "unknown"},
        headers=headers,
    )
    assert resp.status_code == 201
    pet_id = resp.json()["id"]

    return headers, client_id, pet_id


# ──────────────────────────────────────────────────────────────────────────────

class TestListPetsRealData:
    """GET /pro/pets/{client_id} — caminho em lote (_real_pet_data_map)."""

    def test_not_connected_real_fields_are_null(self, client, pro_pet):
        headers, client_id, pet_id = pro_pet

        resp = client.get(f"/api/v1/pro/pets/{client_id}", headers=headers)
        assert resp.status_code == 200
        pet = next(p for p in resp.json() if p["id"] == pet_id)

        # etiqueta do profissional intacta
        assert pet["name"] == "Rexinho (apelido)"
        assert pet["species"] == "cat"
        # nada real pra mostrar ainda
        assert pet["real_name"] is None
        assert pet["real_species"] is None
        assert pet["real_breed"] is None
        assert pet["real_special_characteristics"] is None
        assert pet["has_biometria"] is None
        assert pet["billy_pet_id"] is None

    def test_connected_without_biometria(self, client, pro_pet, real_pet):
        headers, client_id, pet_id = pro_pet
        _link_billy_pet(pet_id, real_pet)

        resp = client.get(f"/api/v1/pro/pets/{client_id}", headers=headers)
        assert resp.status_code == 200
        pet = next(p for p in resp.json() if p["id"] == pet_id)

        # apelido do profissional continua sem ser sobrescrito
        assert pet["name"] == "Rexinho (apelido)"
        assert pet["species"] == "cat"
        # dado real aparece à parte
        assert pet["real_name"] == "Rex Real"
        assert pet["real_species"] == "dog"
        assert pet["real_breed"] == "Labrador"
        # conectado, mas o Pet real não preencheu special_characteristics
        assert pet["real_special_characteristics"] is None
        assert pet["has_biometria"] is False
        assert pet["billy_pet_id"] == real_pet

    def test_connected_with_biometria(self, client, pro_pet, real_pet):
        headers, client_id, pet_id = pro_pet
        _link_billy_pet(pet_id, real_pet)
        _add_biometric(real_pet)

        resp = client.get(f"/api/v1/pro/pets/{client_id}", headers=headers)
        assert resp.status_code == 200
        pet = next(p for p in resp.json() if p["id"] == pet_id)

        assert pet["real_name"] == "Rex Real"
        assert pet["has_biometria"] is True


class TestGetClientRealData:
    """GET /pro/clients/{client_id} — mesmo caminho em lote, endpoint diferente."""

    def test_connected_with_biometria_in_client_detail(self, client, pro_pet, real_pet):
        headers, client_id, pet_id = pro_pet
        _link_billy_pet(pet_id, real_pet)
        _add_biometric(real_pet)

        resp = client.get(f"/api/v1/pro/clients/{client_id}", headers=headers)
        assert resp.status_code == 200
        pet = next(p for p in resp.json()["pets"] if p["id"] == pet_id)

        assert pet["real_name"] == "Rex Real"
        assert pet["real_species"] == "dog"
        assert pet["real_breed"] == "Labrador"
        assert pet["has_biometria"] is True


class TestSpecialCharacteristicsRealData:
    """real_special_characteristics — extensão do BIL-106. Coluna de texto
    simples em pets, sem relação com health_events (histórico clínico
    continua fora de escopo)."""

    def test_connected_with_special_characteristics(self, client, pro_pet, real_pet_with_characteristics):
        headers, client_id, pet_id = pro_pet
        _link_billy_pet(pet_id, real_pet_with_characteristics)

        resp = client.get(f"/api/v1/pro/pets/{client_id}", headers=headers)
        assert resp.status_code == 200
        pet = next(p for p in resp.json() if p["id"] == pet_id)

        assert pet["real_special_characteristics"] == SPECIAL_CHARACTERISTICS
        # pro_pets.special_characteristics (nunca setado neste teste) continua intocado
        assert pet["special_characteristics"] is None


class TestUpdatePetRealData:
    """PATCH /pro/pets/{pet_id} — caminho pontual (_real_pet_data)."""

    def test_update_of_connected_pet_returns_real_data(self, client, pro_pet, real_pet):
        headers, client_id, pet_id = pro_pet
        _link_billy_pet(pet_id, real_pet)

        resp = client.patch(
            f"/api/v1/pro/pets/{pet_id}",
            json={"color": "caramelo"},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()

        # o campo editado mudou, o apelido continua intacto
        assert body["color"] == "caramelo"
        assert body["name"] == "Rexinho (apelido)"
        # e o dado real acompanha a resposta
        assert body["real_name"] == "Rex Real"
        assert body["real_species"] == "dog"
        assert body["has_biometria"] is False
