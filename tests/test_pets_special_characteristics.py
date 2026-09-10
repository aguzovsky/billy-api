"""
Integration tests: special_characteristics no fluxo de criação/edição de pet
do App (billy-api). PetCreate já aceitava o campo, mas POST /api/v1/pets
nunca persistia (achado durante o BIL-106) — cobre a persistência na criação
e o PATCH /api/v1/pets/{pet_id} novo, criado só pra esse campo.

Run with: pytest tests/ -v

Requires: docker-compose up -d db redis
          alembic upgrade head
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="module")
def client():
    # Context manager: mantém um único event loop vivo pra todas as
    # requisições do módulo — ver tests/test_pro_pets_real_data.py pro
    # motivo (pool_pre_ping + TestClient sem isso quebra entre requests).
    with TestClient(app) as c:
        yield c


def _unique_email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@billy.app"


@pytest.fixture()
def auth_token(client):
    resp = client.post("/api/v1/auth/register", json={
        "name": "Tutor Special Characteristics",
        "email": _unique_email("tutor.specialchar"),
        "password": "Testpass123",
    })
    assert resp.status_code in (200, 201)
    return resp.json()["access_token"]


class TestCreatePersistsSpecialCharacteristics:
    def test_create_with_special_characteristics_persists(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}
        text = "mancha branca na orelha esquerda, alérgico a frango"

        resp = client.post(
            "/api/v1/pets",
            json={"name": "Rex", "species": "dog", "breed": "Labrador", "special_characteristics": text},
            headers=headers,
        )
        assert resp.status_code == 201
        pet_id = resp.json()["id"]
        assert resp.json()["special_characteristics"] == text

        # Confirma persistência de verdade — busca de novo, não só o objeto
        # devolvido pelo commit/refresh do create.
        resp = client.get(f"/api/v1/pets/{pet_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["special_characteristics"] == text

    def test_create_without_special_characteristics_is_null(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}

        resp = client.post(
            "/api/v1/pets",
            json={"name": "Mel", "species": "cat"},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["special_characteristics"] is None


class TestUpdateSpecialCharacteristics:
    def test_patch_updates_special_characteristics(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}

        resp = client.post(
            "/api/v1/pets",
            json={"name": "Bolt", "species": "dog"},
            headers=headers,
        )
        assert resp.status_code == 201
        pet_id = resp.json()["id"]
        assert resp.json()["special_characteristics"] is None

        new_text = "reativo com outros cães, usa coleira anti-fuga"
        resp = client.patch(
            f"/api/v1/pets/{pet_id}",
            json={"special_characteristics": new_text},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["special_characteristics"] == new_text

        # Confirma persistência de verdade — GET separado do PATCH.
        resp = client.get(f"/api/v1/pets/{pet_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["special_characteristics"] == new_text

    def test_patch_without_field_preserves_existing_value(self, client, auth_token):
        headers = {"Authorization": f"Bearer {auth_token}"}
        text = "medo de trovão"

        resp = client.post(
            "/api/v1/pets",
            json={"name": "Amora", "species": "cat", "special_characteristics": text},
            headers=headers,
        )
        assert resp.status_code == 201
        pet_id = resp.json()["id"]

        # PATCH sem o campo (só valida que o endpoint aceita body vazio e
        # não apaga o que já estava lá) — mesma convenção do resto do app:
        # None = "não mandou", não "limpar".
        resp = client.patch(f"/api/v1/pets/{pet_id}", json={}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["special_characteristics"] == text
