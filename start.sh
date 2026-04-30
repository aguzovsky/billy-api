#!/bin/bash
set -e
python -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def migrate():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.begin() as conn:
        await conn.execute(text('''
            ALTER TABLE users 
            ADD COLUMN IF NOT EXISTS reset_token VARCHAR(6),
            ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMPTZ
        '''))
    await engine.dispose()

asyncio.run(migrate())
"
alembic upgrade dfa2f2e1adb2
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
