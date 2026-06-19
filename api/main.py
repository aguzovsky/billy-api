import html as _html
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import sentry_sdk

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.models.pet import Pet, PetFoundContact as _pfc_model  # noqa: F401 — registers with Base
from api.models.pet import User
from api.models.registration import PetRegistration
from api.models import pet_photo as _pet_photo_model  # noqa: F401 — registers PetPhoto with Base
from api.models import health as _health_model  # noqa: F401 — registers HealthEvent with Base
from api.models import consent as _consent_model  # noqa: F401 — registers UserConsent with Base
from api.routers import auth, alerts, biometry, pets, guardians, services, ai, pet_photos, health, consents, notify, pet_registrations
from api.routers import pro

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN", "https://80417d985fc75686827188afff05bce0@o4511469145423873.ingest.us.sentry.io/4511469149945856"),
    environment=os.getenv("ENVIRONMENT", "production"),
    traces_sample_rate=0.1,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MVP: scale-to-zero — sem warmup automático de GPU.
    # _keep_modal_warm foi removido: mantinha T4 viva 24/7 e gerou $93/mês.
    yield


app = FastAPI(
    title="Billy Pet API",
    description="Backend de biometria nasal e comunidade para tutores de pets",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(pets.router, prefix=API_PREFIX)
app.include_router(biometry.router, prefix=API_PREFIX)
app.include_router(alerts.router, prefix=API_PREFIX)
app.include_router(guardians.router, prefix=API_PREFIX)
app.include_router(services.router, prefix=API_PREFIX)
app.include_router(ai.router, prefix=API_PREFIX)
app.include_router(pet_photos.router, prefix=API_PREFIX)
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(consents.router, prefix=API_PREFIX)
app.include_router(notify.router, prefix=API_PREFIX)
app.include_router(pet_registrations.router, prefix=API_PREFIX)
app.include_router(pro.router, prefix=API_PREFIX)


@app.get("/pet/{pet_id}", response_class=HTMLResponse, tags=["public"], include_in_schema=False)
async def pet_public_page(pet_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uid = UUID(pet_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    result = await db.execute(select(Pet).where(Pet.id == uid))
    pet = result.scalar_one_or_none()
    if pet is None:
        raise HTTPException(status_code=404, detail="Pet not found")

    owner_result = await db.execute(select(User).where(User.id == pet.owner_id))
    owner = owner_result.scalar_one_or_none()

    reg_result = await db.execute(select(PetRegistration).where(PetRegistration.pet_id == uid))
    registrations = reg_result.scalars().all()

    return HTMLResponse(_render_pet_page(pet, owner, registrations))


def _render_pet_page(pet: Pet, owner, registrations=None) -> str:
    safe = _html.escape
    name = safe(pet.name or "")
    breed = safe(pet.breed or "")
    species_label = {"dog": "Cachorro", "cat": "Gato"}.get(pet.species or "", safe(pet.species or ""))
    breed_part = f" · {breed}" if breed else ""
    owner_name = safe(owner.name if owner else "Tutor")
    is_verified = owner.is_verified if owner else False
    is_lost = (pet.status or "home") == "lost"

    if pet.photo_url:
        photo_html = f'<img src="{safe(pet.photo_url)}" alt="{name}" loading="lazy">'
    else:
        emoji = "🐕" if pet.species == "dog" else "🐈" if pet.species == "cat" else "🐾"
        photo_html = f'<div class="hero-fallback">{emoji}</div>'

    verified_html = '<span class="verified-badge">Verificado ✓</span>' if is_verified else ""
    status_badge_html = '<div class="lost-badge">🚨 PET PERDIDO</div>' if is_lost else ""
    urgency_html = (
        '<div class="urgency-banner"><p>Este pet está perdido. O tutor está esperando notícias.'
        ' Por favor preencha o formulário abaixo.</p></div>'
    ) if is_lost else ""

    id_rows = []
    _type_labels = {"MICROCHIP": "Microchip", "SINPATINHAS": "SinPatinhas",
                    "RGA-SP": "RGA-SP", "SIA-CWB": "SIA-CWB"}
    for reg in (registrations or []):
        label = _type_labels.get(reg.type, reg.type_label or reg.type)
        id_rows.append(
            f'<div class="id-row"><span class="id-label">{safe(label)}</span>'
            f'<span class="id-value">#{safe(reg.number)}</span></div>'
        )

    ids_section_html = (
        '<div class="divider"></div><div class="section-title">Identificação</div>' + "".join(id_rows)
    ) if id_rows else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name} — Billy</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#FAF8F5;color:#3D2314;min-height:100vh}}
    .container{{max-width:480px;margin:0 auto}}
    .billy-bar{{background:#C98A4B;padding:14px 24px;display:flex;align-items:center;gap:8px}}
    .billy-bar span{{color:white;font-size:17px;font-weight:800;letter-spacing:-.3px}}
    .hero{{width:100%;height:280px;background:#FBF0E4;overflow:hidden;position:relative}}
    .hero img{{width:100%;height:100%;object-fit:cover;object-position:center top}}
    .hero-fallback{{display:flex;align-items:center;justify-content:center;height:100%;font-size:96px}}
    .lost-badge{{position:absolute;bottom:0;left:0;right:0;background:rgba(232,74,74,.92);color:white;text-align:center;padding:12px 16px;font-size:18px;font-weight:800;letter-spacing:.3px}}
    .content{{padding:24px}}
    .pet-name{{font-size:28px;font-weight:800;color:#3D2314;line-height:1.15;margin-bottom:4px}}
    .pet-meta{{font-size:15px;color:#8B6F5E;margin-bottom:10px}}
    .owner-row{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    .owner-text{{font-size:14px;color:#8B6F5E}}
    .verified-badge{{background:rgba(201,138,75,.12);color:#C98A4B;border:1px solid rgba(201,138,75,.25);padding:3px 10px;border-radius:6px;font-size:11px;font-weight:700}}
    .divider{{height:1px;background:#EDE5DB;margin:20px 0}}
    .section-title{{font-size:11px;font-weight:700;color:#8B6F5E;text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px}}
    .id-row{{display:flex;align-items:center;gap:8px;padding:10px 0;border-bottom:1px solid #EDE5DB}}
    .id-row:last-of-type{{border-bottom:none}}
    .id-label{{font-size:13px;color:#8B6F5E;width:100px;flex-shrink:0}}
    .id-value{{font-size:14px;font-weight:700;color:#3D2314}}
    .urgency-banner{{background:#FEE2E2;border:1.5px solid #FECACA;border-radius:12px;padding:16px 18px;margin-bottom:20px}}
    .urgency-banner p{{font-size:14px;font-weight:600;color:#B91C1C;line-height:1.5}}
    .found-card{{background:white;border:1px solid #EDE5DB;border-radius:16px;padding:24px}}
    .found-title{{font-size:19px;font-weight:800;color:#3D2314;margin-bottom:6px}}
    .found-sub{{font-size:14px;color:#8B6F5E;margin-bottom:22px;line-height:1.45}}
    .field{{margin-bottom:18px}}
    .field label{{display:block;font-size:12px;font-weight:700;color:#8B6F5E;margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px}}
    .field input,.field textarea{{width:100%;padding:13px 15px;border:1.5px solid #EDE5DB;border-radius:10px;font-size:15px;color:#3D2314;font-family:inherit;background:#FAF8F5;outline:none;transition:border-color .15s}}
    .field input:focus,.field textarea:focus{{border-color:#C98A4B}}
    .field textarea{{resize:none;height:88px}}
    .stay-group{{display:flex;gap:10px}}
    .stay-btn{{flex:1;padding:12px;border:1.5px solid #EDE5DB;border-radius:10px;font-size:14px;font-weight:700;color:#8B6F5E;background:#FAF8F5;cursor:pointer;font-family:inherit;transition:all .15s;text-align:center}}
    .stay-btn.selected{{border-color:#C98A4B;background:rgba(201,138,75,.08);color:#C98A4B}}
    .btn-submit{{width:100%;padding:15px;background:#C98A4B;color:white;border:none;border-radius:12px;font-size:16px;font-weight:800;cursor:pointer;font-family:inherit;transition:opacity .15s;margin-top:8px}}
    .btn-submit:hover{{opacity:.88}}
    .btn-submit:disabled{{opacity:.5;cursor:not-allowed}}
    .success{{display:none;text-align:center;padding:24px 0}}
    .success-icon{{font-size:56px;margin-bottom:14px}}
    .success-title{{font-size:22px;font-weight:800;color:#3D2314;margin-bottom:10px}}
    .success-text{{font-size:15px;color:#8B6F5E;line-height:1.6}}
    .footer{{padding:28px 24px 40px;text-align:center}}
    .footer-btn{{display:block;background:#3D2314;color:white;text-decoration:none;padding:16px 24px;border-radius:14px}}
    .footer-icon{{font-size:20px;display:block;margin-bottom:4px}}
    .footer-main{{display:block;font-size:15px;font-weight:800}}
    .footer-sub{{display:block;font-size:12px;opacity:.6;margin-top:3px;font-weight:400}}
  </style>
</head>
<body>
<div class="container">
  <div class="billy-bar"><span>🐾 billy</span></div>
  <div class="hero">
    {photo_html}
    {status_badge_html}
  </div>
  <div class="content">
    <div class="pet-name">{name}</div>
    <div class="pet-meta">{species_label}{breed_part}</div>
    <div class="owner-row">
      <span class="owner-text">Tutor: {owner_name}</span>
      {verified_html}
    </div>
    {ids_section_html}
    <div class="divider"></div>
    {urgency_html}
    <div class="found-card">
      <div id="form-wrap">
        <div class="found-title">Encontrei este pet 🐾</div>
        <div class="found-sub">Preencha seus dados para que o tutor possa entrar em contato com você.</div>
        <div class="field"><label>Seu nome</label><input type="text" id="fn" placeholder="João Silva"></div>
        <div class="field"><label>Telefone / WhatsApp</label><input type="tel" id="fp" placeholder="(11) 99999-9999"></div>
        <div class="field"><label>Onde encontrou?</label><textarea id="fl" placeholder="Rua das Flores, 123 — próximo ao parque"></textarea></div>
        <div class="field">
          <label>Você pode ficar com o pet? <span style="font-weight:400;text-transform:none;font-size:11px">(opcional)</span></label>
          <div class="stay-group">
            <button class="stay-btn" id="stay-yes" onclick="selectStay('yes')">✔ Sim, posso ficar</button>
            <button class="stay-btn" id="stay-no" onclick="selectStay('no')">✗ Não consigo ficar</button>
          </div>
        </div>
        <button class="btn-submit" id="btn" onclick="send()">Avisar o tutor</button>
      </div>
      <div class="success" id="ok">
        <div class="success-icon">🐾</div>
        <div class="success-title">Obrigado!</div>
        <div class="success-text">O tutor foi avisado.<br>Por favor, fique com o pet e aguarde o contato.</div>
      </div>
    </div>
  </div>
  <div class="footer">
    <a class="footer-btn" href="https://appbilly.com.br">
      <span class="footer-icon">⬇</span>
      <span class="footer-main">Baixar o app Billy</span>
      <span class="footer-sub">Identifique pets perdidos pela biometria nasal</span>
    </a>
  </div>
</div>
<script>
let stayVal=null;
function selectStay(v){{
  stayVal=v;
  document.getElementById('stay-yes').classList.toggle('selected',v==='yes');
  document.getElementById('stay-no').classList.toggle('selected',v==='no');
}}
async function send(){{
  const fn=document.getElementById('fn').value.trim();
  const fp=document.getElementById('fp').value.trim();
  const fl=document.getElementById('fl').value.trim();
  if(!fn||!fp||!fl){{alert('Preencha todos os campos obrigatórios.');return;}}
  const btn=document.getElementById('btn');
  btn.disabled=true;btn.textContent='Enviando...';
  try{{
    const r=await fetch('/api/v1/pets/{pet.id}/found-contact',{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{finder_name:fn,finder_phone:fp,location_text:fl,can_stay:stayVal}})
    }});
    if(r.ok){{document.getElementById('form-wrap').style.display='none';document.getElementById('ok').style.display='block';}}
    else{{btn.disabled=false;btn.textContent='Avisar o tutor';alert('Erro ao enviar. Tente novamente.');}}
  }}catch(e){{btn.disabled=false;btn.textContent='Avisar o tutor';alert('Erro de conexão.');}}
}}
</script>
</body>
</html>"""


@app.get("/health", tags=["infra"])
async def health():
    return {"status": "ok"}


@app.get("/api/v1/health", tags=["infra"])
async def api_health_check():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "billy-api",
    }
