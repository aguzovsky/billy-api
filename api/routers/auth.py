import random
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import create_access_token, get_current_user_id, hash_password, verify_password
from api.models.pet import User
from api.services import storage

router = APIRouter(prefix="/auth", tags=["auth"])


def _validate_password_strength(password: str) -> str:
    """Valida força da senha: mín. 8 chars, 1 maiúscula, 1 número."""
    if len(password) < 8:
        raise ValueError("A senha deve ter pelo menos 8 caracteres.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("A senha deve conter pelo menos uma letra maiúscula.")
    if not re.search(r"[0-9]", password):
        raise ValueError("A senha deve conter pelo menos um número.")
    return password


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    contact_phone: str | None = None
    neighborhood: str | None = None
    gender: str | None = None
    birth_date: str | None = None  # ISO format YYYY-MM-DD
    city: str | None = None
    state: str | None = None
    whatsapp: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED, summary="Criar conta")
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email já cadastrado")

    verification_token = secrets.token_urlsafe(32)
    user = User(
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        contact_phone=body.contact_phone,
        neighborhood=body.neighborhood,
        gender=body.gender,
        birth_date=date.fromisoformat(body.birth_date) if body.birth_date else None,
        city=body.city,
        state=body.state,
        whatsapp=body.whatsapp,
        email_verified=False,
        email_verification_token=verification_token,
        email_verification_token_expires=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await _send_verification_email(user.email, user.name, verification_token)

    token = create_access_token(str(user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": str(user.id),
        "email_verification_required": True,
    }


@router.post("/login", summary="Login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    token = create_access_token(str(user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": str(user.id),
        "email_verified": user.email_verified,
    }


class BiometricLoginRequest(BaseModel):
    email: EmailStr


@router.post("/biometric-login", summary="Login biométrico")
async def biometric_login(body: BiometricLoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Emite token para usuário autenticado via biometria do dispositivo.
    A prova de identidade é a biometria local (Face ID / digital) — o servidor
    confia na asserção do cliente, que só chama este endpoint após authenticate()=true.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    token = create_access_token(str(user.id))
    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": str(user.id),
        "email_verified": user.email_verified,
    }


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    contact_phone: str | None = None
    neighborhood: str | None = None
    cpf: str | None = None
    gender: str | None = None
    birth_date: str | None = None  # ISO format YYYY-MM-DD
    city: str | None = None
    state: str | None = None
    whatsapp: str | None = None
    fcm_token: str | None = None

    @field_validator("cpf")
    @classmethod
    def cpf_format(cls, v: str | None) -> str | None:
        if v is None:
            return None
        digits = re.sub(r'\D', '', v)
        if len(digits) != 11:
            raise ValueError("CPF deve ter 11 dígitos.")
        return digits


@router.get("/me", summary="Meu perfil")
async def get_me(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "contact_phone": user.contact_phone,
        "neighborhood": user.neighborhood,
        "email_verified": user.email_verified,
        "cpf": user.cpf,
        "photo_url": user.photo_url,
        "is_verified": user.is_verified,
        "gender": user.gender,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "city": user.city,
        "state": user.state,
        "whatsapp": user.whatsapp,
    }


@router.patch("/me", summary="Atualizar perfil")
async def update_me(
    body: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.name is not None:
        user.name = body.name
    if body.contact_phone is not None:
        user.contact_phone = body.contact_phone
    if body.neighborhood is not None:
        user.neighborhood = body.neighborhood
    if body.cpf is not None:
        user.cpf = body.cpf
    if body.gender is not None:
        user.gender = body.gender
    if body.birth_date is not None:
        try:
            user.birth_date = date.fromisoformat(body.birth_date)
        except ValueError:
            pass
    if body.city is not None:
        user.city = body.city
    if body.state is not None:
        user.state = body.state
    if body.whatsapp is not None:
        user.whatsapp = body.whatsapp
    if body.fcm_token is not None:
        user.fcm_token = body.fcm_token

    await db.commit()
    await db.refresh(user)
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "contact_phone": user.contact_phone,
        "neighborhood": user.neighborhood,
        "cpf": user.cpf,
        "photo_url": user.photo_url,
        "is_verified": user.is_verified,
        "gender": user.gender,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "city": user.city,
        "state": user.state,
        "whatsapp": user.whatsapp,
    }


@router.patch("/me/photo", summary="Upload foto de perfil")
async def update_me_photo(
    photo: UploadFile = File(..., description="Foto de perfil (JPG/PNG)"),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    image_bytes = await photo.read()
    photo_url = await storage.upload_user_photo(image_bytes, photo.content_type or "image/jpeg")

    if photo_url:
        user.photo_url = photo_url
        await db.commit()
        await db.refresh(user)

    return {"photo_url": user.photo_url}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


async def _send_verification_email(to_email: str, name: str, token: str) -> None:
    if not settings.resend_api_key:
        return
    verify_url = f"{settings.api_base_url}/api/v1/auth/verify-email?token={token}"
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": "Confirme seu e-mail — Billy",
                "html": (
                    f"<p>Olá, {name}!</p>"
                    f"<p>Clique no botão abaixo para confirmar seu e-mail e ativar sua conta:</p>"
                    f"<p><a href='{verify_url}' style='background:#E8714A;color:#fff;padding:12px 24px;"
                    f"border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block'>"
                    f"Confirmar e-mail</a></p>"
                    f"<p>O link expira em <strong>24 horas</strong>.</p>"
                    f"<p>Se você não criou uma conta no Billy, ignore este e-mail.</p>"
                ),
            },
            timeout=10.0,
        )


@router.get("/verify-email", summary="Confirmar e-mail via link", response_class=HTMLResponse)
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email_verification_token == token)
    )
    user = result.scalar_one_or_none()

    if (
        not user
        or not user.email_verification_token_expires
        or user.email_verification_token_expires < datetime.now(timezone.utc)
    ):
        return HTMLResponse(
            content=_html_page(
                "Link inválido ou expirado",
                "Este link de verificação não é válido ou já expirou. "
                "Abra o app Billy e solicite um novo e-mail de confirmação.",
                success=False,
            ),
            status_code=400,
        )

    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    user.email_verification_token = None
    user.email_verification_token_expires = None
    await db.commit()

    return HTMLResponse(
        content=_html_page(
            "E-mail confirmado!",
            "Sua conta Billy está ativa. Você já pode fazer login no app.",
            success=True,
        )
    )


@router.post("/resend-verification", status_code=200, summary="Reenviar e-mail de verificação")
async def resend_verification(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Sempre retorna 200 para não vazar estado
    if not user.email_verified:
        verification_token = secrets.token_urlsafe(32)
        user.email_verification_token = verification_token
        user.email_verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=24)
        await db.commit()
        await _send_verification_email(user.email, user.name, verification_token)

    return {"message": "Se o e-mail ainda não foi confirmado, um novo link foi enviado."}


class _BypassVerifyRequest(BaseModel):
    email: EmailStr


@router.post(
    "/dev/verify-email-bypass",
    status_code=200,
    summary="[STAGING] Marcar e-mail como verificado sem token",
)
async def dev_verify_email_bypass(
    body: _BypassVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    if settings.app_env != "staging":
        raise HTTPException(status_code=403, detail="Endpoint disponível apenas em staging")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")

    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    user.email_verification_token = None
    user.email_verification_token_expires = None
    await db.commit()

    return {"email": user.email, "email_verified": True}


def _html_page(title: str, message: str, success: bool) -> str:
    color = "#E8714A" if success else "#E84A4A"
    icon = "✓" if success else "✗"
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Billy</title>
  <style>
    body {{ font-family: 'Nunito', sans-serif; background: #FAF8F5; display: flex;
            align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
    .card {{ background: #fff; border-radius: 16px; padding: 40px 32px; max-width: 400px;
             text-align: center; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }}
    .icon {{ width: 64px; height: 64px; border-radius: 50%; background: {color};
             color: #fff; font-size: 32px; line-height: 64px; margin: 0 auto 20px; }}
    h1 {{ color: #1E1A17; font-size: 22px; margin: 0 0 12px; }}
    p {{ color: #6B6460; font-size: 15px; line-height: 1.5; margin: 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p>{message}</p>
  </div>
</body>
</html>"""


async def _send_reset_email(to_email: str, code: str) -> None:
    if not settings.resend_api_key:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": "Seu código de recuperação — Billy",
                "html": (
                    f"<p>Olá!</p>"
                    f"<p>Seu código de recuperação de senha é:</p>"
                    f"<h2 style='letter-spacing:8px'>{code}</h2>"
                    f"<p>Este código expira em <strong>15 minutos</strong>.</p>"
                    f"<p>Se você não solicitou isso, ignore este e-mail.</p>"
                ),
            },
            timeout=10.0,
        )


@router.post("/forgot-password", status_code=200, summary="Solicitar código de recuperação")
async def forgot_password(body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Sempre retorna 200 para não vazar se o email existe
    if user:
        code = f"{random.randint(0, 999999):06d}"
        user.reset_token = code
        user.reset_token_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        await db.commit()
        await _send_reset_email(user.email, code)

    return {"message": "Se o e-mail estiver cadastrado, você receberá um código em instantes."}


@router.delete("/me", status_code=204, summary="Excluir conta (anonimização)")
async def delete_me(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.name = "Usuário removido"
    user.email = f"deleted_{user_id}@deleted.com"
    user.hashed_password = ""
    user.contact_phone = None
    user.neighborhood = None
    user.cpf = None
    user.photo_url = None
    user.whatsapp = None
    user.city = None
    user.state = None
    user.gender = None
    user.birth_date = None
    user.email_verified = False
    user.email_verification_token = None
    user.email_verification_token_expires = None
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()


class DeleteRequestBody(BaseModel):
    email: EmailStr


async def _send_deletion_confirmation_email(to_email: str) -> None:
    if not settings.resend_api_key:
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": "Solicitação de exclusão de conta recebida — Billy",
                "html": (
                    "<p>Olá!</p>"
                    "<p>Recebemos sua solicitação de exclusão de conta no Billy.</p>"
                    "<p>Seus dados pessoais identificáveis serão anonimizados em conformidade com a LGPD.</p>"
                    "<p>Caso tenha solicitado por engano ou mude de ideia, entre em contato: "
                    "<a href='mailto:privacidade@appbilly.com.br'>privacidade@appbilly.com.br</a></p>"
                    "<p>Obrigado por usar o Billy.</p>"
                ),
            },
            timeout=10.0,
        )


@router.post("/delete-request", status_code=200, summary="Solicitar exclusão de conta (público)")
async def delete_request(body: DeleteRequestBody, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user and not user.deletion_requested:
        user.deletion_requested = True
        user.deletion_requested_at = datetime.now(timezone.utc)
        await db.commit()
        await _send_deletion_confirmation_email(user.email)

    return {"message": "Solicitação recebida"}


@router.post("/reset-password", status_code=200, summary="Redefinir senha com código")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if (
        not user
        or not user.reset_token
        or user.reset_token != body.code
        or not user.reset_token_expires
        or user.reset_token_expires < datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=400, detail="Código inválido ou expirado.")

    user.hashed_password = hash_password(body.new_password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()

    return {"message": "Senha redefinida com sucesso."}
