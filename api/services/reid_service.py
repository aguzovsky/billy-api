"""
Wrapper for Pet-ReID-IMAG (CVPR 2022).
Extracts 2048-dim embeddings from pet nose/snout images.

Setup: git submodule add https://github.com/muzishen/Pet-ReID-IMAG
       then download weights to ./weights/
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import torch
    import torchvision.transforms as T
    from PIL import Image, ImageFilter

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.warning("torch/torchvision not available — Reid service running in stub mode")

EMBEDDING_DIMS = 2048
_MEAN = [0.485, 0.456, 0.406]
_STD = [0.229, 0.224, 0.225]


def _build_transform():
    return T.Compose([
        T.Resize((256, 256)),
        T.CenterCrop(224),
        T.ToTensor(),
        T.Normalize(mean=_MEAN, std=_STD),
    ])


class PetReIDService:
    def __init__(self, weights_dir: str):
        self.weights_dir = Path(weights_dir)
        self.predictors: list = []
        self._transform = _build_transform() if _TORCH_AVAILABLE else None
        self._device = self._resolve_device()
        self._load_ensemble()

    def _resolve_device(self) -> str:
        if not _TORCH_AVAILABLE:
            return "cpu"
        from api.core.config import settings
        if settings.model_device == "cuda" and torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _load_ensemble(self) -> None:
        if not _TORCH_AVAILABLE:
            logger.warning("Running in stub mode (no torch). Returning random embeddings.")
            return

        # Attempt to import fastreid from submodule
        fastreid_path = Path(__file__).parent.parent.parent / "Pet-ReID-IMAG"
        if fastreid_path.exists():
            import sys
            sys.path.insert(0, str(fastreid_path))
            try:
                from fastreid.config import get_cfg
                from fastreid.engine import DefaultPredictor

                weight_files = sorted(self.weights_dir.glob("*.pth"))[:4]
                for wf in weight_files:
                    cfg = get_cfg()
                    cfg.MODEL.WEIGHTS = str(wf)
                    cfg.MODEL.DEVICE = self._device
                    self.predictors.append(DefaultPredictor(cfg))
                logger.info("Loaded %d Pet-ReID-IMAG model(s)", len(self.predictors))
            except Exception as exc:
                logger.error("Failed to load fastreid models: %s — stub mode active", exc)
        else:
            logger.warning(
                "Pet-ReID-IMAG submodule not found at %s — stub mode active", fastreid_path
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_embedding(self, image_bytes: bytes) -> list[float]:
        """Returns a 2048-dim float vector for a single nose image."""
        if not self.predictors:
            return self._stub_embedding()

        img_tensor = self._preprocess(image_bytes)
        raw_embeddings = []
        for predictor in self.predictors:
            with torch.no_grad():
                feat = predictor(img_tensor.to(self._device))
            raw_embeddings.append(feat.cpu().numpy())

        avg = np.mean(raw_embeddings, axis=0).squeeze()
        # L2-normalise for cosine similarity via pgvector <=>
        norm = np.linalg.norm(avg)
        if norm > 0:
            avg = avg / norm
        return avg.tolist()

    def quality_score(self, image_bytes: bytes) -> float:
        """
        Heuristic quality score in [0, 1].
        Combines sharpness (Laplacian variance) + brightness check.
        Real implementation should also run nose detection confidence.
        """
        try:
            # Sharpness: variance of Laplacian
            import cv2
            nparr = np.frombuffer(image_bytes, np.uint8)
            img_gray = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
            if img_gray is None:
                return 0.0
            lap = cv2.Laplacian(img_gray, cv2.CV_64F)
            sharpness = float(np.var(lap)) / 1000.0

            # Brightness: penalise very dark or very bright
            mean_brightness = float(img_gray.mean()) / 255.0
            brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2

            score = 0.6 * min(sharpness, 1.0) + 0.4 * max(brightness_score, 0.0)
            return round(min(max(score, 0.0), 1.0), 4)
        except Exception as exc:
            logger.error("quality_score error: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _preprocess(self, image_bytes: bytes):
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = self._transform(img).unsqueeze(0)  # (1, C, H, W)
        return tensor

    def _stub_embedding(self) -> list[float]:
        """Deterministic random embedding for development without weights."""
        rng = np.random.default_rng(seed=42)
        vec = rng.standard_normal(EMBEDDING_DIMS).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec.tolist()


# Singleton — loaded once at startup
_service: Optional[PetReIDService] = None


def get_reid_service() -> PetReIDService:
    global _service
    if _service is None:
        from api.core.config import settings
        _service = PetReIDService(settings.model_weights_dir)
    return _service
