"""
Integration tests for biometry endpoints.
Run with: pytest tests/ -v

Requires: docker-compose up -d db redis
          alembic upgrade head
"""

import io
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.main import app

client = TestClient(app)


def _make_jpeg_bytes(width: int = 224, height: int = 224) -> bytes:
    """Create a minimal valid JPEG in memory."""
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


FAKE_EMBEDDING = [0.0] * 2048
FAKE_EMBEDDING[0] = 1.0  # unit vector


@pytest.fixture()
def auth_token():
    """Register a test user and return a JWT."""
    resp = client.post("/api/v1/auth/register", json={
        "name": "Test User",
        "email": "test@billy.app",
        "password": "testpass123",
    })
    if resp.status_code == 409:
        resp = client.post("/api/v1/auth/login", json={
            "email": "test@billy.app",
            "password": "testpass123",
        })
    assert resp.status_code in (200, 201)
    return resp.json()["access_token"]


@pytest.fixture()
def pet_id(auth_token):
    """Create a test pet and return its ID."""
    resp = client.post(
        "/api/v1/pets",
        json={"name": "Rex", "species": "dog", "breed": "Labrador"},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ──────────────────────────────────────────────────────────────────────────────

class TestRegister:
    @patch("api.routers.biometry.storage.upload_photo", return_value="http://minio/test.jpg")
    @patch("api.services.reid_service.PetReIDService.extract_embedding", return_value=FAKE_EMBEDDING)
    @patch("api.services.reid_service.PetReIDService.quality_score", return_value=0.85)
    def test_register_success(self, _qs, _emb, _upload, auth_token, pet_id):
        image_bytes = _make_jpeg_bytes()
        resp = client.post(
            "/api/v1/biometry/register",
            files={"image": ("nose.jpg", image_bytes, "image/jpeg")},
            data={"pet_id": pet_id},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["embedding_dims"] == 2048
        assert body["quality_score"] == 0.85
        assert body["rg_animal_synced"] is False

    @patch("api.services.reid_service.PetReIDService.quality_score", return_value=0.3)
    def test_register_low_quality(self, _qs, auth_token, pet_id):
        image_bytes = _make_jpeg_bytes()
        resp = client.post(
            "/api/v1/biometry/register",
            files={"image": ("nose.jpg", image_bytes, "image/jpeg")},
            data={"pet_id": pet_id},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "LOW_QUALITY"

    def test_register_image_too_large(self, auth_token, pet_id):
        large = b"x" * (11 * 1024 * 1024)  # 11 MB
        resp = client.post(
            "/api/v1/biometry/register",
            files={"image": ("big.jpg", large, "image/jpeg")},
            data={"pet_id": pet_id},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 413

    def test_register_unauthenticated(self, pet_id):
        resp = client.post(
            "/api/v1/biometry/register",
            files={"image": ("nose.jpg", _make_jpeg_bytes(), "image/jpeg")},
            data={"pet_id": pet_id},
        )
        assert resp.status_code == 403


class TestIdentify:
    @patch("api.services.vector_db.find_similar_pets", return_value=[])
    @patch("api.services.reid_service.PetReIDService.extract_embedding", return_value=FAKE_EMBEDDING)
    @patch("api.services.reid_service.PetReIDService.quality_score", return_value=0.80)
    def test_identify_no_match(self, _qs, _emb, _search):
        image_bytes = _make_jpeg_bytes()
        resp = client.post(
            "/api/v1/biometry/identify",
            files={"image": ("nose.jpg", image_bytes, "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["matched"] is False
        assert body["results"] == []
        assert "processing_ms" in body

    @patch("api.services.reid_service.PetReIDService.quality_score", return_value=0.2)
    def test_identify_low_quality(self, _qs):
        resp = client.post(
            "/api/v1/biometry/identify",
            files={"image": ("nose.jpg", _make_jpeg_bytes(), "image/jpeg")},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "LOW_QUALITY"
