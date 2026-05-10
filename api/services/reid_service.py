"""
reid_service.py — Billy App Pet-ReID wrapper.

Fluxo:
  1. Se MODAL_ENDPOINT_URL estiver configurado → chama Modal (GPU real).
  2. Caso contrário → stub determinístico seed=42 (desenvolvimento local).
"""

from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path
from typing import Optional

import httpx
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIMS = 2048


class PetReIDService:
    def __init__(self, modal_endpoint_url: str = ""):
        self.modal_url = modal_endpoint_url.rstrip("/") if modal_endpoint_url else ""
        if self.modal_url:
            logger.info("PetReIDService: Modal GPU mode → %s", self.modal_url)
        else:
            logger.warning("PetReIDService: stub mode (seed=42) — configure MODAL_ENDPOINT_URL")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_embedding(self, image_bytes: bytes) -> list[float]:
        """Retorna embedding 2048-dim L2-normalizado para uma imagem de focinho."""
        if self.modal_url:
            return self._call_modal(image_bytes)
        return self._stub_embedding()

    def quality_score(self, image_bytes: bytes) -> float:
        """
        Score de qualidade [0, 1] baseado em sharpness + brilho.
        Funciona sem GPU — roda no Railway direto.
        """
        try:
            import cv2
            nparr = np.frombuffer(image_bytes, np.uint8)
            img_gray = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            if img_gray is None:
                return 0.0
            lap = cv2.Laplacian(img_gray, cv2.CV_64F)
            sharpness = float(np.var(lap)) / 1000.0
            mean_brightness = float(img_gray.mean()) / 255.0
            brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2
            score = 0.6 * min(sharpness, 1.0) + 0.4 * max(brightness_score, 0.0)
            return round(min(max(score, 0.0), 1.0), 4)
        except Exception as exc:
            logger.error("quality_score error: %s", exc)
            return 0.5  # fallback neutro

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_modal(self, image_bytes: bytes) -> list[float]:
        """Chama o endpoint Modal com GPU e retorna o embedding."""
        try:
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            response = httpx.post(
                self.modal_url,
                json={"image_b64": image_b64},
                timeout=30.0,  # cold start pode levar ~10s
            )
            response.raise_for_status()
            data = response.json()
            embedding = data["embedding"]
            logger.info("Modal embedding OK — dims=%d", len(embedding))
            return embedding
        except Exception as exc:
            logger.error("Modal call failed: %s — falling back to stub", exc)
            return self._stub_embedding()

    def _stub_embedding(self) -> list[float]:
        """Embedding determinístico para dev sem Modal configurado."""
        rng = np.random.default_rng(seed=42)
        vec = rng.standard_normal(EMBEDDING_DIMS).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec.tolist()


# Singleton — carregado uma vez no startup
_service: Optional[PetReIDService] = None


def get_reid_service() -> PetReIDService:
    global _service
    if _service is None:
        from api.core.config import settings
        _service = PetReIDService(
            modal_endpoint_url=settings.modal_endpoint_url,
        )
    return _service
