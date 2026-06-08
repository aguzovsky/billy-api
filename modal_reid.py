"""
modal_reid.py — Billy App Pet-ReID endpoint com pesos reais Pet-ReID-IMAG

Deploy:
    modal deploy modal_reid.py

Test:
    modal run modal_reid.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVISO DE CUSTO MVP — LEIA ANTES DE ALTERAR QUALQUER PARÂMETRO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • min_containers=0 em TODAS as classes/funções GPU → escala para zero.
  • container_idle_timeout=20 → GPU desliga após 20s sem chamadas.
  • NÃO altere min_containers para 1 em GPU → cobrança contínua ~$70/mês.
  • NÃO crie warmup automático, cron ou loop que chame funções GPU.
  • Cold start esperado: 30–60 segundos (aceitável no MVP).
  • Handlers HTTP (extract_embedding*) são CPU-only; GPU fica nos .cls.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import base64
import io
import os

import modal

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

aws_secret = modal.Secret.from_name("billy-aws")


# MVP: scale-to-zero — GPU sobe sob demanda, desliga após 20s idle.
# NUNCA altere min_containers=1 aqui — T4 a $0.59/hr fica viva 24/7.
@app.cls(
    gpu="T4",
    scaledown_window=20,
    timeout=180,
    min_containers=0,
    secrets=[aws_secret],
)
class PetReIDModel:
    @modal.enter()
    def load_model(self):
        import torch
        import torch.nn as nn
        import boto3
        from resnest.torch import resnest101
        import torchvision.transforms as T

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print("[Billy-ReID] Modelo: ResNeSt-101 Pet-ReID-IMAG")
        print(f"[Billy-ReID] Device: {self.device}")

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

        backbone = resnest101(pretrained=False)
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

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec.tolist()


# Handler HTTP CPU-only — não usa GPU; despacha para PetReIDModel via .remote().
@app.function(container_idle_timeout=20, timeout=180, secrets=[aws_secret])
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
#
# MVP: scale-to-zero — GPU sobe sob demanda, desliga após 20s idle.
# NUNCA altere min_containers=1 aqui — T4 a $0.59/hr fica viva 24/7.
# ─────────────────────────────────────────────────────────────────────────────

@app.cls(
    gpu="T4",
    scaledown_window=20,
    timeout=180,
    min_containers=0,
    secrets=[aws_secret],
)
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


# Handler HTTP CPU-only — não usa GPU; despacha para PetReIDModelFast via .remote().
@app.function(container_idle_timeout=20, timeout=180, secrets=[aws_secret])
@modal.fastapi_endpoint(method="POST")
def extract_embedding_fast(body: dict) -> dict:
    image_b64 = body.get("image_b64", "")
    if not image_b64:
        return {"error": "image_b64 is required"}, 400

    model = PetReIDModelFast()
    embedding = model.embed.remote(image_b64)
    return {"embedding": embedding, "dims": len(embedding)}


# ─────────────────────────────────────────────────────────────────────────────
# extract_embedding_warmup — REMOVIDO INTENCIONALMENTE
#
# Por que foi removido:
#   • Era chamado pelo backend a cada 4min via _keep_modal_warm() em main.py
#   • Internamente chamava PetReIDModelFast().embed.remote() → GPU T4
#   • Com scaledown_window=300 (5min), a GPU NUNCA desligava entre chamadas
#   • 284 chamadas de warmup num mês = GPU quase contínua = $93 de $95 do total
#
# Agora: GPU sobe sob demanda (cold start 30–60s), desliga após 20s idle.
# Custo estimado MVP com volume baixo: $0–5/mês.
#
# NÃO recriar este endpoint sem revisar o MODAL_COST_SAFETY.md.
# ─────────────────────────────────────────────────────────────────────────────


@app.local_entrypoint()
def test():
    from PIL import Image
    import numpy as np

    arr = (np.random.rand(256, 256, 3) * 255).astype("uint8")
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    model = PetReIDModelFast()
    emb = model.embed.remote(b64)
    print(f"✅ Embedding shape: {len(emb)} dims")
    print(f"   First 5 values: {emb[:5]}")
    print(f"   L2 norm: {sum(x**2 for x in emb)**0.5:.6f} (deve ser ≈1.0)")
