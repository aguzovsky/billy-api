from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.core.config import settings

# hide_parameters=True (BIL-104 parte 3) — sem isso, uma exceção do
# SQLAlchemy inclui os valores reais dos parâmetros do SQL na mensagem
# ("[SQL: ...] [parameters: (...)]"), que vai pro Sentry mesmo com
# send_default_pii=False (esse flag só cobre IP/headers/corpo de requisição
# automático do SDK, não o texto da própria exceção capturada).
engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True, hide_parameters=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
