#!/bin/bash
echo "=== PHASE 1: PORT=${PORT} ===" >&2
echo "=== PHASE 2: running alembic ===" >&2
alembic upgrade head
echo "=== PHASE 3: alembic done ===" >&2
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}
