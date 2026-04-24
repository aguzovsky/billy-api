"""
SinPatinhas / RG Animal BR integration stub.

TODO: implement OAuth Gov.br flow and POST to
      sinpatinhas.mma.gov.br/api/animais once the public API is released.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.pet import Pet

logger = logging.getLogger(__name__)


async def sync_pet(db: AsyncSession, pet_id: UUID, rg_animal_id: str) -> bool:
    """
    Register/update pet in RG Animal BR.
    Returns True when sync is confirmed by Gov.br (always False until API exists).
    """
    await db.execute(
        update(Pet).where(Pet.id == pet_id).values(rg_animal_id=rg_animal_id)
    )
    await db.commit()
    logger.info("SinPatinhas stub: saved rg_animal_id=%s for pet=%s", rg_animal_id, pet_id)
    return False  # synced = False until real integration
