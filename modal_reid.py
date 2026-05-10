"""
modal_reid.py — Billy App Pet-ReID endpoint on Modal.com

Deploy:
    modal deploy modal_reid.py

Test:
    modal run modal_reid.py::extract_embedding_test

After deploy, copy the public URL to your Railway env var:
    MODAL_ENDPOINT_URL=https://<your-workspace>--billy-reid-extract-embedding.modal.run
"""

import base64
import io

import modal

# ── Image: instala torch + torchvision + pillow ─────────────────────────────
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.2.2",
        "torchvision==0.17.2",
        "pillow==10.3.0",
        "numpy==1.26.4",
        "fastapi[standard]",
    )
)

app = modal.App("billy-reid", image=image)

# ── Modelo carregado uma vez por container (cold start ~5s) ─────────────────
@app.cls(gpu="T4", scaledown_window=300)
class PetReIDModel:
    @modal.enter()
    def load_model(self):
        import torch
        import torchvision.models as models
        import torchvision.transforms as T

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Billy-ReID] Device: {self.device}")

        # ResNet50 pretrained — remove FC layer → 2048-dim embedding
        # Produz embeddings reais (não seed=42).
        # Quando tivermos os pesos Pet-ReID-IMAG treinados, substituímos aqui.
        backbone = models.resnet50(weights=models.ResNet50_Weights.IMAGENET1K_V2)
        self.model = torch.nn.Sequential(*list(backbone.children())[:-1])  # → (B, 2048, 1, 1)
        self.model.eval().to(self.device)

        self.transform = T.Compose([
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225]),
        ])
        print("[Billy-ReID] Model ready.")

    @modal.method()
    def embed(self, image_b64: str) -> list[float]:
        """Recebe imagem base64, retorna embedding 2048-dim L2-normalizado."""
        import numpy as np
        import torch
        from PIL import Image

        # Decode
        img_bytes = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

        # Preprocess
        tensor = self.transform(img).unsqueeze(0).to(self.device)  # (1,3,224,224)

        # Forward
        with torch.no_grad():
            feat = self.model(tensor)              # (1, 2048, 1, 1)
        vec = feat.squeeze().cpu().numpy()          # (2048,)

        # L2-normalise (compatível com pgvector <=> cosine)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()


# ── Endpoint HTTP (FastAPI-style via modal.web_endpoint) ────────────────────
@app.function(gpu="T4", scaledown_window=300)
@modal.fastapi_endpoint(method="POST")
def extract_embedding(body: dict) -> dict:
    """
    POST body:  { "image_b64": "<base64 string>" }
    Response:   { "embedding": [2048 floats], "dims": 2048 }
    """
    image_b64 = body.get("image_b64", "")
    if not image_b64:
        return {"error": "image_b64 is required"}, 400

    model = PetReIDModel()
    embedding = model.embed.remote(image_b64)

    return {"embedding": embedding, "dims": len(embedding)}


# ── Teste local ─────────────────────────────────────────────────────────────
@app.local_entrypoint()
def extract_embedding_test():
    """
    Roda: modal run modal_reid.py
    Gera uma imagem sintética e imprime o shape do embedding.
    """
    from PIL import Image
    import numpy as np

    # Imagem sintética 256x256 (pixels aleatórios)
    arr = (np.random.rand(256, 256, 3) * 255).astype("uint8")
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    model = PetReIDModel()
    emb = model.embed.remote(b64)
    print(f"✅ Embedding shape: {len(emb)} dims")
    print(f"   First 5 values: {emb[:5]}")
    print(f"   L2 norm: {sum(x**2 for x in emb)**0.5:.6f}  (deve ser ≈1.0)")
