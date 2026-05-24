from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.database import get_db
from api.core.security import get_current_user_id
from api.models.consent import UserConsent

router = APIRouter(prefix="/auth", tags=["auth"])


class ConsentRequest(BaseModel):
    terms_version: str
    privacy_version: str
    image_consent: bool
    model_improvement_consent: bool
    platform: str  # 'ios' | 'android' | 'web'


@router.post("/consents", status_code=status.HTTP_201_CREATED, summary="Registrar aceite de termos")
async def post_consents(
    body: ConsentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    ip = request.client.host if request.client else None
    consent = UserConsent(
        user_id=UUID(user_id),
        terms_version=body.terms_version,
        privacy_version=body.privacy_version,
        image_consent=body.image_consent,
        model_improvement_consent=body.model_improvement_consent,
        accepted_at=datetime.now(timezone.utc),
        platform=body.platform,
        ip_address=ip,
    )
    db.add(consent)
    await db.commit()
    await db.refresh(consent)
    return {
        "id": str(consent.id),
        "terms_version": consent.terms_version,
        "privacy_version": consent.privacy_version,
        "image_consent": consent.image_consent,
        "model_improvement_consent": consent.model_improvement_consent,
        "accepted_at": consent.accepted_at.isoformat(),
        "platform": consent.platform,
    }
