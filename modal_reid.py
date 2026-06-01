"""
modal_reid.py — Billy App Pet-ReID endpoint com pesos reais Pet-ReID-IMAG

Deploy:
    modal deploy modal_reid.py

Test:
    modal run modal_reid.py
"""

import base64
import io
import os

import modal

# Imagem com todas as dependências necessárias
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.2.2",
        "torchvision==0.17.2",
        "pillow==10.3.0",
        "numpy==1.26.4",
        "boto3==1.34.0",
        "resnest @ git+https://github.com/zhanghang1989/ResNeSt.git",
        "fastapi[standard]",
    )
)

app = modal.App("billy-reid", image=image)

# Segredos AWS para baixar os pesos do S3
aws_secret = modal.Secret.from_name("billy-aws")

@app.cls(gpu="T4", scaledown_window=300, secrets=[aws_secret])
class PetReIDModel:
    @modal.enter()
    def load_model(self):
        import torch
        import torch.nn as nn
        import numpy as np
        import boto3
        from resnest.torch import resnest101
        from PIL import Image
        import torchvision.transforms as T

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print("[Billy-ReID] Modelo: ResNeSt-101 Pet-ReID-IMAG")
        print(f"[Billy-ReID] Device: {self.device}")

        # Baixar pesos do S3 se não existirem localmente
        weights_path = "/tmp/model_final.pth"
        if not os.path.exists(weights_path):
            print("[Billy-ReID] Baixando pesos do S3...")
            s3 = boto3.client(
                "s3",
                aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                region_name=os.environ.get("AWS_S3_REGION", "us-east-2"),
            )
            s3.download_file("appbilly-photos", "models/model_final.pth", weights_path)
            print("[Billy-ReID] Pesos baixados.")

        # Carregar ResNeSt-101 como backbone
        backbone = resnest101(pretrained=False)
        # Remover camada FC final → embedding 2048-dim
        self.model = nn.Sequential(*list(backbone.children())[:-1])

        # Carregar pesos treinados
        ckpt = torch.load(weights_path, map_location=self.device)
        state_dict = ckpt["model"]

        # Filtrar só as chaves do backbone (remove heads.*)
        backbone_state = {
            k.replace("backbone.", ""): v
            for k, v in state_dict.items()
            if k.startswith("backbone.")
        }
        self.model.load_state_dict(backbone_state, strict=False)
        self.model.eval().to(self.device)

        # Transform igual ao treinamento (224x224, normalize ImageNet)
        self.transform = T.Compose([
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225]),
        ])
        print("[Billy-ReID] Modelo ResNeSt-101 com pesos Pet-ReID-IMAG pronto.")

    @modal.method()
    def embed(self, image_b64: str) -> list[float]:
        import numpy as np
        import torch
        from PIL import Image

        img_bytes = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        tensor = self.transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            feat = self.model(tensor)
        vec = feat.squeeze().cpu().numpy()

        # L2-normalizar para cosine similarity com pgvector
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()


@app.function(gpu="T4", scaledown_window=300, secrets=[aws_secret])
@modal.fastapi_endpoint(method="POST")
def extract_embedding(body: dict) -> dict:
    image_b64 = body.get("image_b64", "")
    if not image_b64:
        return {"error": "image_b64 is required"}, 400

    model = PetReIDModel()
    embedding = model.embed.remote(image_b64)
    return {"embedding": embedding, "dims": len(embedding)}


# ─────────────────────────────────────────────────────────────────────────────
# ResNeSt-50 — endpoint "fast" (cold start ~2x mais rápido que resnest101)
# Mesmos pesos Pet-ReID-IMAG, mesma saída 2048-dim, mesmo preprocessing.
# ─────────────────────────────────────────────────────────────────────────────

@app.cls(gpu="T4", scaledown_window=300, secrets=[aws_secret])
class PetReIDModelFast:
    @modal.enter()
    def load_model(self):
        import torch
        import torch.nn as nn
        import boto3
        from resnest.torch import resnest50
        import torchvision.transforms as T

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print("[Billy-ReID-Fast] Modelo: ResNeSt-50 Pet-ReID-IMAG")
        print(f"[Billy-ReID-Fast] Device: {self.device}")

        weights_path = "/tmp/model_final.pth"
        if not os.path.exists(weights_path):
            print("[Billy-ReID-Fast] Baixando pesos do S3...")
            s3 = boto3.client(
                "s3",
                aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
                region_name=os.environ.get("AWS_S3_REGION", "us-east-2"),
            )
            s3.download_file("appbilly-photos", "models/model_final.pth", weights_path)
            print("[Billy-ReID-Fast] Pesos baixados.")

        backbone = resnest50(pretrained=False)
        self.model = nn.Sequential(*list(backbone.children())[:-1])

        ckpt = torch.load(weights_path, map_location=self.device)
        state_dict = ckpt["model"]

        backbone_state = {
            k.replace("backbone.", ""): v
            for k, v in state_dict.items()
            if k.startswith("backbone.")
        }
        self.model.load_state_dict(backbone_state, strict=False)
        self.model.eval().to(self.device)

        self.transform = T.Compose([
            T.Resize(256),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406],
                        std=[0.229, 0.224, 0.225]),
        ])
        print("[Billy-ReID-Fast] Modelo ResNeSt-50 com pesos Pet-ReID-IMAG pronto.")

    @modal.method()
    def embed(self, image_b64: str) -> list[float]:
        import numpy as np
        import torch
        from PIL import Image

        img_bytes = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        tensor = self.transform(img).unsqueeze(0).to(self.device)

        with torch.no_grad():
            feat = self.model(tensor)
        vec = feat.squeeze().cpu().numpy()

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()


@app.function(gpu="T4", scaledown_window=300, secrets=[aws_secret])
@modal.fastapi_endpoint(method="POST")
def extract_embedding_fast(body: dict) -> dict:
    image_b64 = body.get("image_b64", "")
    if not image_b64:
        return {"error": "image_b64 is required"}, 400

    model = PetReIDModelFast()
    embedding = model.embed.remote(image_b64)
    return {"embedding": embedding, "dims": len(embedding)}


# ─────────────────────────────────────────────────────────────────────────────
# Warmup — acorda o container Fast sem GPU obrigatória no handler.
# Dispara um embed com imagem dummy para inicializar o container GPU.
# ─────────────────────────────────────────────────────────────────────────────

@app.function(scaledown_window=60)
@modal.fastapi_endpoint(method="GET")
def extract_embedding_warmup() -> dict:
    import numpy as np
    from PIL import Image as _Image

    arr = (np.zeros((64, 64, 3))).astype("uint8")
    img = _Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    dummy_b64 = base64.b64encode(buf.getvalue()).decode()

    PetReIDModelFast().embed.remote(dummy_b64)
    return {"status": "warm"}


@app.local_entrypoint()
def test():
    from PIL import Image
    import numpy as np

    arr = (np.random.rand(256, 256, 3) * 255).astype("uint8")
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    model = PetReIDModel()
    emb = model.embed.remote(b64)
    print(f"✅ Embedding shape: {len(emb)} dims")
    print(f"   First 5 values: {emb[:5]}")
    print(f"   L2 norm: {sum(x**2 for x in emb)**0.5:.6f} (deve ser ≈1.0)")
