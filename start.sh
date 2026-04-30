#!/bin/bash
set -e
python -c "
import asyncio, os
import asyncpg

async def migrate():
    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    await conn.execute('''
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS reset_token VARCHAR(6),
        ADD COLUMN IF NOT EXISTS reset_token_expires TIMESTAMPTZ
    ''')
    await conn.close()

asyncio.run(migrate())
"
alembic upgrade dfa2f2e1adb2
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
