import random
import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.database import get_db
from api.core.security import create_access_token, get_current_user_id, hash_password, verify_password
from api.models.pet import User

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

    user = User(
        name=body.name,
        email=body.email,
        hashed_password=hash_password(body.password),
        contact_phone=body.contact_phone,
        neighborhood=body.neighborhood,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer", "user_id": str(user.id)}


@router.post("/login", summary="Login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    token = create_access_token(str(user.id))
    return {"access_token": token, "token_type": "bearer", "user_id": str(user.id)}


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    contact_phone: str | None = None
    neighborhood: str | None = None


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

    await db.commit()
    await db.refresh(user)
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "contact_phone": user.contact_phone,
        "neighborhood": user.neighborhood,
    }


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
