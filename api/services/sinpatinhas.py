"""
SinPatinhas / RG Animal BR integration stub.

TODO: implement OAuth Gov.br flow and POST to
      sinpatinhas.mma.gov.br/api/animais once the public API is released.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.registration import PetRegistration

logger = logging.getLogger(__name__)


async def sync_pet(db: AsyncSession, pet_id: UUID, rg_animal_id: str) -> bool:
    """
    Register/update pet in RG Animal BR.
    Returns True when sync is confirmed by Gov.br (always False until API exists).
    """
    result = await db.execute(
        select(PetRegistration).where(
            PetRegistration.pet_id == pet_id,
            PetRegistration.type == "SINPATINHAS",
        )
    )
    reg = result.scalar_one_or_none()
    sinpatinhas_number = reg.number if reg else None  # used in future Gov.br POST
    # TODO: implement OAuth Gov.br flow and POST to
    #       sinpatinhas.mma.gov.br/api/animais once the public API is released.
    rga_result = await db.execute(
        select(PetRegistration).where(
            PetRegistration.pet_id == pet_id,
            PetRegistration.type == "RGA-SP",
        )
    )
    existing = rga_result.scalar_one_or_none()
    if existing:
        existing.number = rg_animal_id
    else:
        db.add(PetRegistration(pet_id=pet_id, type="RGA-SP", number=rg_animal_id))
    await db.commit()
    logger.info(
        "SinPatinhas stub: sinpatinhas=%s → rga=%s for pet=%s",
        sinpatinhas_number, rg_animal_id, pet_id,
    )
    return False  # synced = False until real integration
